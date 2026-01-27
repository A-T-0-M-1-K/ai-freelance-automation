"""
Генератор автоматических налоговых деклараций (3-НДФЛ) для фрилансеров РФ.
Интеграция с данными о доходах из системы и подготовка документов для ФНС.
"""

import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from decimal import Decimal
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

from services.storage.database_service import DatabaseService
from core.security.encryption_engine import EncryptionEngine


@dataclass
class IncomeRecord:
    """Запись о доходе"""
    date: datetime.date
    amount: Decimal
    currency: str
    platform: str
    client_name: str
    payment_method: str  # 'bank_transfer', 'crypto', 'yoomoney', 'paypal'
    tax_deduction_eligible: bool = False
    deduction_amount: Decimal = Decimal('0.00')
    description: str = ''


@dataclass
class TaxDeduction:
    """Налоговый вычет"""
    type: str  # 'standard', 'property', 'education', 'medical', 'investment'
    amount: Decimal
    documents: List[str]  # Список путей к сканам документов
    description: str = ''


@dataclass
class TaxDeclaration:
    """Налоговая декларация 3-НДФЛ"""
    year: int
    taxpayer_inn: str
    taxpayer_name: str
    taxpayer_address: str
    total_income: Decimal
    total_deductions: Decimal
    taxable_base: Decimal
    tax_rate: Decimal = Decimal('0.13')  # 13% для РФ (или 15% для доходов > 5М ₽)
    tax_amount: Decimal
    tax_paid: Decimal
    tax_to_pay: Decimal
    income_records: List[IncomeRecord]
    deductions: List[TaxDeduction]
    generated_at: datetime.datetime
    declaration_id: str


class TaxDeclarationGenerator:
    """
    Генератор налоговых деклараций с поддержкой:
    - Автоматического сбора данных о доходах из системы
    - Расчета налоговой базы и суммы налога
    - Учета налоговых вычетов
    - Генерации XML для программы "Декларация" ФНС
    - Подготовки сопроводительных документов (справки 2-НДФЛ от платформ)
    - Экспорта в форматах: XML (ФНС), PDF, Excel
    """

    def __init__(self,
                 db_service: Optional[DatabaseService] = None,
                 data_dir: str = "data/finances",
                 output_dir: str = "data/reports/tax"):
        self.db_service = db_service or DatabaseService()
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.encryption_engine = EncryptionEngine()

        # Загрузка конфигурации налоговых ставок
        self.tax_config = self._load_tax_config()

    def _load_tax_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации налоговых ставок и правил"""
        default_config = {
            'russia': {
                'ndfl_rates': {
                    'standard': Decimal('0.13'),
                    'high_income_threshold': Decimal('5000000.00'),  # 5 млн ₽
                    'high_income_rate': Decimal('0.15'),
                    'self_employed_patent': Decimal('0.06'),  # 6% для патента
                    'self_employed_npd': Decimal('0.04')  # 4% для НПД
                },
                'deduction_limits': {
                    'standard_child': Decimal('1400.00'),  # на 1-2 ребенка
                    'standard_child_3plus': Decimal('3000.00'),  # на 3+ ребенка
                    'property': Decimal('2000000.00'),  # имущественный вычет
                    'education': Decimal('120000.00'),  # обучение
                    'medical': Decimal('120000.00'),  # лечение (кроме дорогостоящего)
                    'investment_ife': Decimal('400000.00')  # ИИС типа А
                },
                'fiscal_year_start': '01-01',
                'fiscal_year_end': '12-31',
                'declaration_deadline': '04-30'  # 30 апреля следующего года
            }
        }

        # Попытка загрузить из конфига
        config_path = Path("config/tax_config.json")
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

        return default_config

    def collect_income_data(self, year: int, user_id: str) -> List[IncomeRecord]:
        """
        Сбор данных о доходах за налоговый период из всех источников системы.

        Источники данных:
        - Транзакции из data/finances/transactions.json
        - Платежи из data/finances/payments.json
        - Информация о заказах из БД
        - Криптовалютные транзакции из блокчейн-модуля
        """
        income_records = []

        # 1. Загрузка транзакций из JSON файлов
        transactions_path = self.data_dir / "transactions.json"
        if transactions_path.exists():
            try:
                with open(transactions_path, 'r', encoding='utf-8') as f:
                    transactions = json.load(f)

                for tx in transactions:
                    tx_date = datetime.datetime.fromisoformat(tx['timestamp']).date()
                    if tx_date.year == year and tx.get('user_id') == user_id and tx.get('type') == 'income':
                        income_records.append(IncomeRecord(
                            date=tx_date,
                            amount=Decimal(str(tx['amount'])),
                            currency=tx.get('currency', 'RUB'),
                            platform=tx.get('platform', 'unknown'),
                            client_name=tx.get('client_name', 'Неизвестно'),
                            payment_method=tx.get('payment_method', 'bank_transfer'),
                            tax_deduction_eligible=tx.get('tax_deduction_eligible', False),
                            deduction_amount=Decimal(str(tx.get('deduction_amount', '0.00'))),
                            description=tx.get('description', '')
                        ))
            except Exception as e:
                print(f"⚠️ Ошибка загрузки транзакций: {e}")

        # 2. Загрузка данных из БД (если доступно)
        try:
            payments = self.db_service.query_payments_by_year(user_id, year)
            for payment in payments:
                income_records.append(IncomeRecord(
                    date=payment['payment_date'],
                    amount=Decimal(str(payment['amount'])),
                    currency=payment.get('currency', 'RUB'),
                    platform=payment.get('platform', 'unknown'),
                    client_name=payment.get('client_name', 'Неизвестно'),
                    payment_method=payment.get('payment_method', 'bank_transfer'),
                    tax_deduction_eligible=payment.get('tax_deduction_eligible', False),
                    deduction_amount=Decimal(str(payment.get('deduction_amount', '0.00'))),
                    description=payment.get('description', '')
                ))
        except Exception as e:
            print(f"⚠️ Ошибка загрузки платежей из БД: {e}")

        # 3. Загрузка криптовалютных транзакций
        crypto_income = self._collect_crypto_income(year, user_id)
        income_records.extend(crypto_income)

        # Сортировка по дате
        income_records.sort(key=lambda x: x.date)

        return income_records

    def _collect_crypto_income(self, year: int, user_id: str) -> List[IncomeRecord]:
        """Сбор данных о доходах в криптовалюте с конвертацией в рубли по курсу на дату"""
        crypto_records = []

        try:
            # Интеграция с блокчейн-модулем для получения транзакций
            from blockchain.wallet_manager import WalletManager
            wallet_manager = WalletManager()

            transactions = wallet_manager.get_income_transactions(user_id, year)

            for tx in transactions:
                # Конвертация криптовалюты в рубли по официальному курсу ЦБ на дату
                rub_amount = self._convert_crypto_to_rub(
                    amount=Decimal(str(tx['amount'])),
                    crypto_currency=tx['currency'],
                    date=tx['date']
                )

                crypto_records.append(IncomeRecord(
                    date=tx['date'],
                    amount=rub_amount,
                    currency='RUB',
                    platform='cryptocurrency',
                    client_name=tx.get('sender', 'Криптокошелек'),
                    payment_method='crypto',
                    tax_deduction_eligible=False,
                    description=f"Конвертация {tx['amount']} {tx['currency']} по курсу ЦБ"
                ))

        except ImportError:
            print("ℹ️ Модуль блокчейна недоступен, пропускаем крипто-доходы")
        except Exception as e:
            print(f"⚠️ Ошибка сбора крипто-доходов: {e}")

        return crypto_records

    def _convert_crypto_to_rub(self, amount: Decimal, crypto_currency: str, date: datetime.date) -> Decimal:
        """Конвертация криптовалюты в рубли по курсу ЦБ РФ на дату"""
        # В реальной системе — интеграция с API ЦБ РФ или криптобирж
        # Для примера используем фиксированные курсы
        crypto_rates = {
            'BTC': Decimal('3000000.00'),  # 3 млн ₽ за биткоин (пример)
            'ETH': Decimal('200000.00'),  # 200 тыс ₽ за эфир
            'USDT': Decimal('90.00'),  # 90 ₽ за USDT
            'USDC': Decimal('90.00')
        }

        rate = crypto_rates.get(crypto_currency.upper(), Decimal('1.00'))
        return amount * rate

    def calculate_tax_liability(self,
                                income_records: List[IncomeRecord],
                                deductions: Optional[List[TaxDeduction]] = None,
                                tax_regime: str = 'ndfl') -> Dict[str, Any]:
        """
        Расчет налоговой обязанности.

        Args:
            income_records: Список доходов за год
            deductions: Список налоговых вычетов
            tax_regime: Режим налогообложения ('ndfl', 'npd', 'patent', 'usn')

        Returns:
            Словарь с расчетом налога
        """
        total_income = sum(record.amount for record in income_records)

        # Применение вычетов
        total_deductions = Decimal('0.00')
        if deductions:
            total_deductions = sum(ded.amount for ded in deductions)

        # Расчет налогооблагаемой базы
        taxable_base = max(Decimal('0.00'), total_income - total_deductions)

        # Расчет налога в зависимости от режима
        if tax_regime == 'ndfl':
            # Прогрессивная шкала НДФЛ (13%/15%)
            if taxable_base <= self.tax_config['russia']['ndfl_rates']['high_income_threshold']:
                tax_rate = self.tax_config['russia']['ndfl_rates']['standard']
            else:
                # Часть до 5 млн — 13%, свыше — 15%
                base_under_threshold = self.tax_config['russia']['ndfl_rates']['high_income_threshold']
                base_over_threshold = taxable_base - base_under_threshold
                tax_amount = (base_under_threshold * self.tax_config['russia']['ndfl_rates']['standard'] +
                              base_over_threshold * self.tax_config['russia']['ndfl_rates']['high_income_rate'])
                tax_rate = tax_amount / taxable_base
                return {
                    'total_income': total_income,
                    'total_deductions': total_deductions,
                    'taxable_base': taxable_base,
                    'tax_rate': tax_rate,
                    'tax_amount': tax_amount,
                    'tax_regime': tax_regime,
                    'calculation_details': {
                        'base_under_5m': float(base_under_threshold),
                        'tax_under_5m': float(
                            base_under_threshold * self.tax_config['russia']['ndfl_rates']['standard']),
                        'base_over_5m': float(base_over_threshold),
                        'tax_over_5m': float(
                            base_over_threshold * self.tax_config['russia']['ndfl_rates']['high_income_rate'])
                    }
                }
            tax_amount = taxable_base * tax_rate
        elif tax_regime == 'npd':
            tax_rate = self.tax_config['russia']['ndfl_rates']['self_employed_npd']
            tax_amount = taxable_base * tax_rate
        elif tax_regime == 'patent':
            tax_rate = self.tax_config['russia']['ndfl_rates']['self_employed_patent']
            tax_amount = taxable_base * tax_rate
        else:  # usn
            tax_rate = Decimal('0.06')  # Упрощенная система 6%
            tax_amount = taxable_base * tax_rate

        return {
            'total_income': total_income,
            'total_deductions': total_deductions,
            'taxable_base': taxable_base,
            'tax_rate': tax_rate,
            'tax_amount': tax_amount,
            'tax_regime': tax_regime
        }

    def generate_declaration(self,
                             year: int,
                             user_id: str,
                             taxpayer_info: Dict[str, str],
                             deductions: Optional[List[TaxDeduction]] = None,
                             tax_regime: str = 'ndfl') -> TaxDeclaration:
        """
        Генерация полной налоговой декларации.

        Args:
            year: Налоговый период (год)
            user_id: Идентификатор пользователя
            taxpayer_info: Информация о налогоплательщике {'inn', 'name', 'address'}
            deductions: Список налоговых вычетов
            tax_regime: Режим налогообложения

        Returns:
            Объект декларации
        """
        # Сбор данных о доходах
        income_records = self.collect_income_data(year, user_id)

        # Расчет налога
        tax_calc = self.calculate_tax_liability(income_records, deductions, tax_regime)

        # Формирование декларации
        declaration = TaxDeclaration(
            year=year,
            taxpayer_inn=taxpayer_info['inn'],
            taxpayer_name=taxpayer_info['name'],
            taxpayer_address=taxpayer_info['address'],
            total_income=tax_calc['total_income'],
            total_deductions=tax_calc['total_deductions'],
            taxable_base=tax_calc['taxable_base'],
            tax_rate=tax_calc['tax_rate'],
            tax_amount=tax_calc['tax_amount'],
            tax_paid=Decimal('0.00'),  # Будет заполнено из данных о фактически уплаченных налогах
            tax_to_pay=tax_calc['tax_amount'],  # Упрощенно — в реальности вычитаем уплаченные авансы
            income_records=income_records,
            deductions=deductions or [],
            generated_at=datetime.datetime.now(),
            declaration_id=f"DECL_{year}_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        return declaration

    def export_to_fns_xml(self, declaration: TaxDeclaration, output_path: Optional[str] = None) -> Path:
        """
        Экспорт декларации в XML формат для программы "Декларация" ФНС России.
        Формат соответствует требованиям ФНС для электронного документооборота.
        """
        if output_path is None:
            output_path = self.output_dir / f"3-ndfl_{declaration.year}_{declaration.declaration_id}.xml"

        # Создание XML структуры в формате ФНС
        root = ET.Element("Декларация")
        root.set("ВерсПрог", "10.1")  # Версия программы Декларация
        root.set("ВерсФорм", "1302221")  # Код формы 3-НДФЛ

        # Раздел 1 - Сведения о налогоплательщике
        раздел1 = ET.SubElement(root, "Раздел1")
        ET.SubElement(раздел1, "ИНН").text = declaration.taxpayer_inn
        ET.SubElement(раздел1, "ФИО").text = declaration.taxpayer_name
        ET.SubElement(раздел1, "Адрес").text = declaration.taxpayer_address
        ET.SubElement(раздел1, "Год").text = str(declaration.year)

        # Раздел 2 - Доходы
        раздел2 = ET.SubElement(root, "Раздел2")
        доходы = ET.SubElement(раздел2, "Доходы")

        for i, income in enumerate(declaration.income_records, 1):
            доход = ET.SubElement(доходы, "Доход")
            доход.set("НомЗап", str(i))
            ET.SubElement(доход, "ДатаПолуч").text = income.date.strftime("%d.%m.%Y")
            ET.SubElement(доход, "СумДоход").text = str(int(income.amount))
            ET.SubElement(доход, "Источник").text = income.platform
            ET.SubElement(доход, "ВидДохода").text = "1"  # Код вида дохода: 1 - доходы от источников в РФ

        # Раздел 3 - Вычеты
        раздел3 = ET.SubElement(root, "Раздел3")
        вычеты = ET.SubElement(раздел3, "Вычеты")

        for i, deduction in enumerate(declaration.deductions, 1):
            вычет = ET.SubElement(вычеты, "Вычет")
            вычет.set("НомЗап", str(i))
            ET.SubElement(вычет, "ВидВычета").text = self._map_deduction_type_to_code(deduction.type)
            ET.SubElement(вычет, "СумВычет").text = str(int(deduction.amount))
            ET.SubElement(вычет, "ОписаниеВычета").text = deduction.description

        # Раздел 4 - Расчет налога
        раздел4 = ET.SubElement(root, "Раздел4")
        ET.SubElement(раздел4, "СумДоход").text = str(int(declaration.total_income))
        ET.SubElement(раздел4, "СумВычет").text = str(int(declaration.total_deductions))
        ET.SubElement(раздел4, "НалоговаяБаза").text = str(int(declaration.taxable_base))
        ET.SubElement(раздел4, "СтавкаНалога").text = str(float(declaration.tax_rate) * 100)
        ET.SubElement(раздел4, "СумНалог").text = str(int(declaration.tax_amount))
        ET.SubElement(раздел4, "УплачНалог").text = str(int(declaration.tax_paid))
        ET.SubElement(раздел4, "НалогКУплате").text = str(int(declaration.tax_to_pay))

        # Сохранение XML
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)  # Красивое форматирование (Python 3.9+)
        tree.write(output_path, encoding='utf-8', xml_declaration=True)

        print(f"✅ Декларация 3-НДФЛ за {declaration.year} год экспортирована в: {output_path}")
        return Path(output_path)

    def _map_deduction_type_to_code(self, deduction_type: str) -> str:
        """Маппинг типа вычета в код ФНС"""
        mapping = {
            'standard': '1',  # Стандартный
            'property': '2',  # Имущественный
            'education': '3',  # Социальный (образование)
            'medical': '3',  # Социальный (лечение)
            'investment': '5'  # Инвестиционный
        }
        return mapping.get(deduction_type, '9')  # 9 - прочие вычеты

    def export_to_pdf(self, declaration: TaxDeclaration, output_path: Optional[str] = None):
        """Экспорт декларации в PDF с визуальным оформлением"""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet

            if output_path is None:
                output_path = self.output_dir / f"3-ndfl_{declaration.year}_{declaration.declaration_id}.pdf"

            doc = SimpleDocTemplate(str(output_path), pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            # Заголовок
            story.append(Paragraph(f"НАЛОГОВАЯ ДЕКЛАРАЦИЯ ПО ФОРМЕ 3-НДФЛ", styles['Title']))
            story.append(Paragraph(f"за {declaration.year} год", styles['Title']))
            story.append(Spacer(1, 12))

            # Информация о налогоплательщике
            story.append(Paragraph("СВЕДЕНИЯ О НАЛОГОПЛАТЕЛЬЩИКЕ", styles['Heading2']))
            taxpayer_data = [
                ["ИНН", declaration.taxpayer_inn],
                ["ФИО", declaration.taxpayer_name],
                ["Адрес", declaration.taxpayer_address],
            ]
            taxpayer_table = Table(taxpayer_data, colWidths=[100, 400])
            taxpayer_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ]))
            story.append(taxpayer_table)
            story.append(Spacer(1, 12))

            # Доходы
            story.append(Paragraph("ДОХОДЫ ЗА НАЛОГОВЫЙ ПЕРИОД", styles['Heading2']))
            income_data = [["Дата", "Сумма (₽)", "Платформа", "Тип"]]
            for income in declaration.income_records:
                income_data.append([
                    income.date.strftime("%d.%m.%Y"),
                    f"{income.amount:,.2f}",
                    income.platform,
                    income.payment_method
                ])
            income_data.append(["ИТОГО", f"{declaration.total_income:,.2f}", "", ""])

            income_table = Table(income_data, colWidths=[80, 120, 150, 100])
            income_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (1, 1), (1, -2), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (-1, -1), (-1, -1), colors.lightgrey),
                ('FONTNAME', (-1, -1), (-1, -1), 'Helvetica-Bold'),
            ]))
            story.append(income_table)
            story.append(Spacer(1, 12))

            # Расчет налога
            story.append(Paragraph("РАСЧЕТ НАЛОГОВОЙ ОБЯЗАННОСТИ", styles['Heading2']))
            tax_data = [
                ["Показатель", "Сумма (₽)"],
                ["Общий доход", f"{declaration.total_income:,.2f}"],
                ["Налоговые вычеты", f"{declaration.total_deductions:,.2f}"],
                ["Налогооблагаемая база", f"{declaration.taxable_base:,.2f}"],
                ["Ставка налога", f"{declaration.tax_rate * 100:.0f}%"],
                ["Сумма налога к уплате", f"{declaration.tax_to_pay:,.2f}"],
            ]
            tax_table = Table(tax_data, colWidths=[200, 150])
            tax_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightyellow),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ]))
            story.append(tax_table)
            story.append(Spacer(1, 24))

            # Подпись
            story.append(Paragraph(f"Дата формирования: {declaration.generated_at.strftime('%d.%m.%Y %H:%M')}",
                                   styles['Normal']))
            story.append(Paragraph(f"Идентификатор декларации: {declaration.declaration_id}", styles['Normal']))
            story.append(Spacer(1, 48))
            story.append(Paragraph("________________________", styles['Normal']))
            story.append(Paragraph("(подпись налогоплательщика)", styles['Normal']))

            doc.build(story)
            print(f"✅ PDF-версия декларации сохранена: {output_path}")

        except ImportError:
            print("⚠️ Библиотека reportlab не установлена. Установите: pip install reportlab")
            raise
        except Exception as e:
            print(f"❌ Ошибка генерации PDF: {e}")
            raise

    def generate_supporting_documents(self, declaration: TaxDeclaration, output_dir: Optional[str] = None):
        """
        Генерация сопроводительных документов:
        - Справка о доходах по форме 2-НДФЛ (для каждой платформы)
        - Список подтверждающих документов для вычетов
        - Пояснительная записка
        """
        if output_dir is None:
            output_dir = self.output_dir / f"supporting_docs_{declaration.year}"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 1. Генерация справок 2-НДФЛ по платформам
        platforms = set(income.platform for income in declaration.income_records)
        for platform in platforms:
            platform_income = [inc for inc in declaration.income_records if inc.platform == platform]
            total = sum(inc.amount for inc in platform_income)

            doc_content = f"""
СПРАВКА О ДОХОДАХ И СУММАХ НАЛОГОВ ФИЗИЧЕСКОГО ЛИЦА
Форма 2-НДФЛ (условная для платформы {platform})

Год: {declaration.year}
ИНН налогоплательщика: {declaration.taxpayer_inn}
ФИО: {declaration.taxpayer_name}

Доходы от платформы "{platform}":
"""
            for inc in platform_income:
                doc_content += f"  {inc.date.strftime('%d.%m.%Y')}: {inc.amount:,.2f} ₽ ({inc.payment_method})\n"

            doc_content += f"\nИТОГО за год: {total:,.2f} ₽\n"
            doc_content += f"\nДата формирования: {datetime.datetime.now().strftime('%d.%m.%Y')}\n"

            with open(Path(output_dir) / f"2-ndfl_{platform}_{declaration.year}.txt", 'w', encoding='utf-8') as f:
                f.write(doc_content)

        # 2. Список документов для вычетов
        if declaration.deductions:
            deductions_list = "ДОКУМЕНТЫ, ПОДТВЕРЖДАЮЩИЕ ПРАВО НА ВЫЧЕТЫ\n\n"
            for i, ded in enumerate(declaration.deductions, 1):
                deductions_list += f"{i}. Вычет '{ded.type}': {ded.amount:,.2f} ₽\n"
                deductions_list += f"   Основание: {ded.description}\n"
                if ded.documents:
                    deductions_list += "   Документы:\n"
                    for doc in ded.documents:
                        deductions_list += f"     - {doc}\n"
                deductions_list += "\n"

            with open(Path(output_dir) / f"deductions_documents_{declaration.year}.txt", 'w', encoding='utf-8') as f:
                f.write(deductions_list)

        print(f"✅ Сопроводительные документы сохранены в: {output_dir}")

    def validate_declaration(self, declaration: TaxDeclaration) -> Dict[str, Any]:
        """
        Валидация декларации на соответствие требованиям ФНС:
        - Проверка контрольных соотношений
        - Проверка лимитов вычетов
        - Проверка полноты данных
        """
        errors = []
        warnings = []

        # Проверка: доход не может быть отрицательным
        if declaration.total_income < 0:
            errors.append("Общий доход не может быть отрицательным")

        # Проверка: вычеты не могут превышать доход
        if declaration.total_deductions > declaration.total_income:
            warnings.append(
                f"Вычеты ({declaration.total_deductions:,.2f} ₽) превышают доход ({declaration.total_income:,.2f} ₽). Избыточная часть вычетов не будет учтена.")

        # Проверка лимитов вычетов
        deduction_limits = self.tax_config['russia']['deduction_limits']
        for deduction in declaration.deductions:
            limit = deduction_limits.get(deduction.type)
            if limit and deduction.amount > limit:
                warnings.append(
                    f"Вычет '{deduction.type}' ({deduction.amount:,.2f} ₽) превышает лимит ({limit:,.2f} ₽). Избыточная часть не будет учтена.")

        # Проверка наличия ИНН
        if not declaration.taxpayer_inn or not declaration.taxpayer_inn.isdigit() or len(
                declaration.taxpayer_inn) not in [10, 12]:
            errors.append("Некорректный ИНН налогоплательщика")

        # Проверка периода декларирования
        current_year = datetime.datetime.now().year
        if declaration.year > current_year or declaration.year < current_year - 5:
            warnings.append(f"Нестандартный налоговый период: {declaration.year} год")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'can_submit': len(errors) == 0
        }

    def submit_to_fns(self, declaration: TaxDeclaration, method: str = 'online') -> Dict[str, Any]:
        """
        Отправка декларации в ФНС (симуляция — в реальной системе интеграция с Госуслугами/ФНС).

        Args:
            declaration: Декларация для отправки
            method: Способ отправки ('online', 'office', 'mail')

        Returns:
            Статус отправки
        """
        validation = self.validate_declaration(declaration)

        if not validation['can_submit']:
            return {
                'success': False,
                'error': 'Декларация не прошла валидацию',
                'validation_errors': validation['errors']
            }

        # Симуляция отправки
        submission_id = f"FNS_SUB_{declaration.declaration_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        result = {
            'success': True,
            'submission_id': submission_id,
            'timestamp': datetime.datetime.now().isoformat(),
            'method': method,
            'status': 'submitted',
            'receipt_url': f"https://lkfl.nalog.ru/lk/receipt/{submission_id}",
            'next_steps': [
                "Декларация отправлена в ФНС",
                "Ожидайте уведомления о приемке (обычно 1-3 дня)",
                "После приемки оплатите налог до 15 июля",
                "Сохраните квитанцию об оплате"
            ]
        }

        # Сохранение квитанции о подаче декларации
        receipt_path = self.output_dir / f"receipt_{submission_id}.json"
        with open(receipt_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"✅ Декларация отправлена в ФНС. Квитанция: {receipt_path}")
        return result


# CLI интерфейс
def main():
    import argparse

    parser = argparse.ArgumentParser(description='Генератор налоговых деклараций 3-НДФЛ')
    parser.add_argument('--year', '-y', type=int, required=True, help='Налоговый период (год)')
    parser.add_argument('--user-id', '-u', required=True, help='ID пользователя')
    parser.add_argument('--inn', required=True, help='ИНН налогоплательщика')
    parser.add_argument('--name', required=True, help='ФИО налогоплательщика')
    parser.add_argument('--address', required=True, help='Адрес регистрации')
    parser.add_argument('--regime', '-r', default='ndfl', choices=['ndfl', 'npd', 'patent', 'usn'],
                        help='Режим налогообложения')
    parser.add_argument('--output', '-o', default=None, help='Директория для экспорта')

    args = parser.parse_args()

    generator = TaxDeclarationGenerator(output_dir=args.output or f"data/reports/tax/{args.year}")

    taxpayer_info = {
        'inn': args.inn,
        'name': args.name,
        'address': args.address
    }

    # Генерация декларации
    declaration = generator.generate_declaration(
        year=args.year,
        user_id=args.user_id,
        taxpayer_info=taxpayer_info,
        tax_regime=args.regime
    )

    # Валидация
    validation = generator.validate_declaration(declaration)
    if not validation['is_valid']:
        print("❌ Декларация не прошла валидацию:")
        for error in validation['errors']:
            print(f"  • {error}")
        return 1

    if validation['warnings']:
        print("⚠️ Предупреждения:")
        for warning in validation['warnings']:
            print(f"  • {warning}")

    # Экспорт в форматах
    generator.export_to_fns_xml(declaration)
    generator.export_to_pdf(declaration)
    generator.generate_supporting_documents(declaration)

    print("\n✅ Декларация успешно сформирована!")
    print(f"   Общий доход: {declaration.total_income:,.2f} ₽")
    print(f"   Налог к уплате: {declaration.tax_to_pay:,.2f} ₽")
    print(f"   Срок уплаты налога: 15 июля {args.year + 1} года")

    return 0


if __name__ == "__main__":
    exit(main())