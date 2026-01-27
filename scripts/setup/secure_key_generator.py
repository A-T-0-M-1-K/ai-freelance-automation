#!/usr/bin/env python3
"""
Безопасная генерация SSL/TLS сертификатов и ключей при развёртывании.
Удаляет захардкоженные ключи из репозитория и генерирует новые уникальные.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import argparse
import secrets


class SecureKeyGenerator:
    """
    Генератор безопасных SSL/TLS ключей и самоподписанных сертификатов.
    Предназначен для автоматического запуска при первом развёртывании системы.
    """

    def __init__(self,
                 ssl_dir: str = "docker/nginx/ssl",
                 backup_dir: str = "backup/automatic/ssl_backup"):
        self.ssl_dir = Path(ssl_dir)
        self.backup_dir = Path(backup_dir)
        self.ssl_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def check_existing_keys(self) -> Dict[str, Any]:
        """Проверка существующих ключей и сертификатов"""
        cert_path = self.ssl_dir / "cert.pem"
        key_path = self.ssl_dir / "key.pem"
        dhparam_path = self.ssl_dir / "dhparam.pem"

        return {
            'cert_exists': cert_path.exists(),
            'key_exists': key_path.exists(),
            'dhparam_exists': dhparam_path.exists(),
            'cert_path': str(cert_path),
            'key_path': str(key_path),
            'dhparam_path': str(dhparam_path),
            'cert_in_git': self._is_file_tracked_by_git(cert_path),
            'key_in_git': self._is_file_tracked_by_git(key_path)
        }

    def _is_file_tracked_by_git(self, file_path: Path) -> bool:
        """Проверка, отслеживается ли файл системой контроля версий"""
        if not shutil.which('git'):
            return False

        try:
            result = subprocess.run(
                ['git', 'ls-files', '--error-unmatch', str(file_path)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent.parent  # Корень репозитория
            )
            return result.returncode == 0
        except Exception:
            return False

    def backup_existing_keys(self) -> Optional[Path]:
        """Резервное копирование существующих ключей перед заменой"""
        cert_path = self.ssl_dir / "cert.pem"
        key_path = self.ssl_dir / "key.pem"

        if not (cert_path.exists() and key_path.exists()):
            return None

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_subdir = self.backup_dir / f"ssl_backup_{timestamp}"
        backup_subdir.mkdir(parents=True, exist_ok=True)

        # Копирование с сохранением прав доступа
        shutil.copy2(cert_path, backup_subdir / "cert.pem.backup")
        shutil.copy2(key_path, backup_subdir / "key.pem.backup")

        # Установка строгих прав доступа на бэкап
        os.chmod(backup_subdir / "key.pem.backup", 0o600)

        print(f"✅ Создан бэкап существующих ключей: {backup_subdir}")
        return backup_subdir

    def remove_insecure_keys(self):
        """Удаление небезопасных (захардкоженных) ключей из рабочей директории"""
        cert_path = self.ssl_dir / "cert.pem"
        key_path = self.ssl_dir / "key.pem"

        removed = []

        if cert_path.exists():
            cert_path.unlink()
            removed.append(str(cert_path))

        if key_path.exists():
            key_path.unlink()
            removed.append(str(key_path))

        if removed:
            print(f"🗑️  Удалены небезопасные ключи:\n   " + "\n   ".join(removed))

    def add_keys_to_gitignore(self):
        """Добавление ключей в .gitignore если их там нет"""
        gitignore_path = Path(".gitignore")

        if not gitignore_path.exists():
            return

        with open(gitignore_path, 'r', encoding='utf-8') as f:
            gitignore_content = f.read()

        patterns_to_add = [
            "docker/nginx/ssl/cert.pem",
            "docker/nginx/ssl/key.pem",
            "docker/nginx/ssl/dhparam.pem",
            "ssl/",
            "*.pem",
            "*.key",
            "*.crt"
        ]

        added_patterns = []
        for pattern in patterns_to_add:
            if pattern not in gitignore_content:
                gitignore_content += f"\n# SSL keys (auto-generated)\n{pattern}\n"
                added_patterns.append(pattern)

        if added_patterns:
            with open(gitignore_path, 'w', encoding='utf-8') as f:
                f.write(gitignore_content)
            print(f"✅ Добавлены паттерны в .gitignore: {', '.join(added_patterns)}")

    def generate_dhparam(self, bits: int = 2048) -> Path:
        """Генерация параметров Диффи-Хеллмана для Perfect Forward Secrecy"""
        dhparam_path = self.ssl_dir / "dhparam.pem"

        if dhparam_path.exists():
            print(f"ℹ️  Параметры DH уже существуют: {dhparam_path}")
            return dhparam_path

        print(f"🔐 Генерация параметров Диффи-Хеллмана ({bits} бит)...")
        print("   Это может занять 5-15 минут в зависимости от мощности CPU...")

        try:
            subprocess.run(
                ['openssl', 'dhparam', '-out', str(dhparam_path), str(bits)],
                check=True,
                capture_output=True
            )
            os.chmod(dhparam_path, 0o644)
            print(f"✅ Параметры DH сгенерированы: {dhparam_path}")
            return dhparam_path
        except FileNotFoundError:
            print("❌ OpenSSL не установлен. Установите: sudo apt-get install openssl")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"❌ Ошибка генерации параметров DH: {e.stderr.decode()}")
            sys.exit(1)

    def generate_self_signed_cert(self,
                                  common_name: str = "localhost",
                                  country: str = "RU",
                                  state: str = "Moscow",
                                  locality: str = "Moscow",
                                  organization: str = "AI Freelance Automation",
                                  validity_days: int = 365) -> Tuple[Path, Path]:
        """
        Генерация самоподписанного SSL-сертификата для разработки и тестирования.
        Для продакшена рекомендуется использовать Let's Encrypt или коммерческий сертификат.
        """
        cert_path = self.ssl_dir / "cert.pem"
        key_path = self.ssl_dir / "key.pem"

        # Генерация приватного ключа
        print("🔐 Генерация приватного ключа RSA (2048 бит)...")
        subprocess.run(
            ['openssl', 'genrsa', '-out', str(key_path), '2048'],
            check=True,
            capture_output=True
        )
        os.chmod(key_path, 0o600)  # Только владелец может читать

        # Генерация самоподписанного сертификата
        print(f"📜 Генерация самоподписанного сертификата (действителен {validity_days} дней)...")

        # Создание конфигурационного файла OpenSSL для корректного заполнения полей
        openssl_cnf = self.ssl_dir / "openssl.cnf"
        openssl_cnf.write_text(f"""
[req]
default_bits = 2048
default_md = sha256
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
C = {country}
ST = {state}
L = {locality}
O = {organization}
CN = {common_name}

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = {common_name}
DNS.2 = localhost
IP.1 = 127.0.0.1
""")

        subprocess.run(
            [
                'openssl', 'req', '-x509', '-new',
                '-key', str(key_path),
                '-out', str(cert_path),
                '-days', str(validity_days),
                '-config', str(openssl_cnf),
                '-extensions', 'v3_req'
            ],
            check=True,
            capture_output=True
        )
        os.chmod(cert_path, 0o644)

        # Удаление временного конфигурационного файла
        openssl_cnf.unlink(missing_ok=True)

        print(f"✅ SSL-сертификат сгенерирован: {cert_path}")
        print(f"✅ Приватный ключ сохранён: {key_path}")
        print(f"\n⚠️  ВАЖНО: Это самоподписанный сертификат для разработки.")
        print(f"   Для продакшена используйте Let's Encrypt (certbot) или коммерческий сертификат.")

        return cert_path, key_path

    def generate_production_ready_setup(self, domain: str, email: str):
        """
        Настройка для продакшена с автоматическим получением сертификата от Let's Encrypt.
        Требует установленного certbot и настроенного домена.
        """
        print(f"🚀 Настройка продакшн SSL для домена: {domain}")

        # Проверка наличия certbot
        if not shutil.which('certbot'):
            print("❌ Certbot не установлен. Установите:")
            print("   Ubuntu/Debian: sudo apt-get install certbot python3-certbot-nginx")
            print("   CentOS/RHEL: sudo yum install certbot python3-certbot-nginx")
            return

        # Резервное копирование текущих ключей
        self.backup_existing_keys()
        self.remove_insecure_keys()

        # Генерация временного самоподписанного сертификата для запуска Nginx
        self.generate_self_signed_cert(common_name=domain)

        print("\n🔧 Запуск получения сертификата от Let's Encrypt...")
        print("   Убедитесь, что:")
        print(f"   • Домен {domain} указывает на этот сервер")
        print("   • Порт 80 открыт и доступен из интернета")
        print("   • Nginx запущен и слушает порт 80")

        # Команда для получения сертификата (требует ручного подтверждения)
        certbot_cmd = [
            'sudo', 'certbot', '--nginx',
            '--domain', domain,
            '--email', email,
            '--agree-tos',
            '--non-interactive',
            '--redirect'  # Автоматическое перенаправление HTTP → HTTPS
        ]

        print(f"\nВыполнение команды:\n{' '.join(certbot_cmd)}\n")

        try:
            subprocess.run(certbot_cmd, check=True)
            print(f"\n✅ Сертификат от Let's Encrypt успешно получен для {domain}")
            print("   Автоматическое обновление настроено (certbot renew --quiet)")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Ошибка получения сертификата: {e}")
            print("   Проверьте логи: /var/log/letsencrypt/letsencrypt.log")

    def verify_certificate(self, cert_path: Path, key_path: Path) -> Dict[str, Any]:
        """Верификация корректности сгенерированных сертификата и ключа"""
        print("\n🔍 Верификация SSL-сертификата...")

        results = {
            'cert_exists': cert_path.exists(),
            'key_exists': key_path.exists(),
            'cert_readable': False,
            'key_readable': False,
            'key_permissions': False,
            'cert_valid': False,
            'key_matches_cert': False,
            'errors': []
        }

        if not results['cert_exists']:
            results['errors'].append("Сертификат не найден")
        if not results['key_exists']:
            results['errors'].append("Приватный ключ не найден")

        if results['cert_exists']:
            try:
                result = subprocess.run(
                    ['openssl', 'x509', '-in', str(cert_path), '-noout', '-text'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                results['cert_readable'] = True
                # Извлечение срока действия
                if 'notBefore' in result.stdout and 'notAfter' in result.stdout:
                    results['cert_valid'] = True
            except Exception as e:
                results['errors'].append(f"Ошибка чтения сертификата: {e}")

        if results['key_exists']:
            try:
                # Проверка прав доступа (должны быть 600)
                stat_info = os.stat(key_path)
                permissions = oct(stat_info.st_mode)[-3:]
                results['key_permissions'] = (permissions == '600')

                if not results['key_permissions']:
                    results['errors'].append(f"Некорректные права доступа к ключу: {permissions} (должно быть 600)")

                # Проверка читаемости ключа
                subprocess.run(
                    ['openssl', 'rsa', '-in', str(key_path), '-check', '-noout'],
                    capture_output=True,
                    check=True
                )
                results['key_readable'] = True
            except Exception as e:
                results['errors'].append(f"Ошибка проверки ключа: {e}")

        # Проверка соответствия ключа сертификату
        if results['cert_readable'] and results['key_readable']:
            try:
                cert_modulus = subprocess.run(
                    ['openssl', 'x509', '-in', str(cert_path), '-noout', '-modulus'],
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout

                key_modulus = subprocess.run(
                    ['openssl', 'rsa', '-in', str(key_path), '-noout', '-modulus'],
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout

                results['key_matches_cert'] = (cert_modulus == key_modulus)
                if not results['key_matches_cert']:
                    results['errors'].append("Приватный ключ не соответствует сертификату")
            except Exception as e:
                results['errors'].append(f"Ошибка проверки соответствия ключа и сертификата: {e}")

        # Вывод результатов
        print("   Статус сертификата:")
        print(f"     • Существует: {'✅' if results['cert_exists'] else '❌'}")
        print(f"     • Читаем: {'✅' if results['cert_readable'] else '❌'}")
        print(f"     • Валиден: {'✅' if results['cert_valid'] else '❌'}")

        print("   Статус ключа:")
        print(f"     • Существует: {'✅' if results['key_exists'] else '❌'}")
        print(f"     • Читаем: {'✅' if results['key_readable'] else '❌'}")
        print(f"     • Права 600: {'✅' if results['key_permissions'] else '❌'}")
        print(f"     • Соответствует сертификату: {'✅' if results['key_matches_cert'] else '❌'}")

        if results['errors']:
            print("\n   Ошибки:")
            for error in results['errors']:
                print(f"     ❌ {error}")
        else:
            print("\n   ✅ Все проверки пройдены успешно")

        return results

    def run_secure_setup(self,
                         common_name: str = "localhost",
                         production: bool = False,
                         domain: Optional[str] = None,
                         email: Optional[str] = None):
        """Полный цикл безопасной настройки SSL"""
        print("=" * 80)
        print("🔐 БЕЗОПАСНАЯ ГЕНЕРАЦИЯ SSL-КЛЮЧЕЙ")
        print("=" * 80)

        # 1. Проверка существующих ключей
        status = self.check_existing_keys()
        print("\n🔍 Проверка текущего состояния:")
        print(f"   Сертификат: {'найден' if status['cert_exists'] else 'отсутствует'} "
              f"({'в Git' if status['cert_in_git'] else 'не в Git'})")
        print(f"   Ключ: {'найден' if status['key_exists'] else 'отсутствует'} "
              f"({'в Git' if status['key_in_git'] else 'не в Git'})")

        # 2. Предупреждение если ключи в репозитории
        if status['cert_in_git'] or status['key_in_git']:
            print("\n⚠️  ВНИМАНИЕ: Обнаружены SSL-ключи в системе контроля версий!")
            print("   Это критическая уязвимость безопасности.")
            print("   Ключи будут удалены из рабочей директории и добавлены в .gitignore.")

            response = input("\nПродолжить удаление ключей? (да/нет): ").strip().lower()
            if response not in ['да', 'yes', 'y']:
                print("❌ Операция отменена пользователем")
                return

        # 3. Резервное копирование
        self.backup_existing_keys()

        # 4. Удаление небезопасных ключей
        self.remove_insecure_keys()

        # 5. Добавление в .gitignore
        self.add_keys_to_gitignore()

        # 6. Генерация новых ключей
        if production:
            if not domain or not email:
                print("❌ Для продакшн-режима требуются параметры --domain и --email")
                return
            self.generate_production_ready_setup(domain, email)
        else:
            # Разработка/тестирование — самоподписанный сертификат
            cert_path, key_path = self.generate_self_signed_cert(common_name=common_name)

            # 7. Генерация параметров DH
            self.generate_dhparam()

            # 8. Верификация
            self.verify_certificate(cert_path, key_path)

        print("\n" + "=" * 80)
        print("✅ Настройка SSL завершена успешно")
        print("=" * 80)

        if not production:
            print("\nℹ️  Для разработки:")
            print("   • Сертификат самоподписанный — браузер будет показывать предупреждение")
            print("   • Примите исключение безопасности для доступа к https://localhost")
            print("\nℹ️  Для продакшена:")
            print("   • Используйте --production --domain yourdomain.com --email admin@yourdomain.com")
            print("   • Или настройте Let's Encrypt вручную через certbot")


# CLI интерфейс
def main():
    parser = argparse.ArgumentParser(
        description='Генератор безопасных SSL-ключей для AI Freelance Automation',
        epilog='Примеры:\n'
               '  # Разработка (самоподписанный сертификат для localhost)\n'
               '  python secure_key_generator.py\n\n'
               '  # Разработка с кастомным именем хоста\n'
               '  python secure_key_generator.py --common-name my-dev-server.local\n\n'
               '  # Продакшн (требует настроенного домена и открытого порта 80)\n'
               '  python secure_key_generator.py --production --domain example.com --email admin@example.com',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--common-name', '-cn', default='localhost',
                        help='Common Name для самоподписанного сертификата (по умолчанию: localhost)')
    parser.add_argument('--production', '-p', action='store_true',
                        help='Режим продакшена с получением сертификата от Let\'s Encrypt')
    parser.add_argument('--domain', '-d', help='Доменное имя для Let\'s Encrypt (требуется для --production)')
    parser.add_argument('--email', '-e', help='Email для уведомлений Let\'s Encrypt (требуется для --production)')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Принудительная генерация без подтверждения')
    parser.add_argument('--check', '-c', action='store_true',
                        help='Только проверить текущее состояние ключей без генерации')

    args = parser.parse_args()

    generator = SecureKeyGenerator()

    if args.check:
        status = generator.check_existing_keys()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    # Проверка критической уязвимости — ключи в репозитории
    status = generator.check_existing_keys()
    if status['cert_in_git'] or status['key_in_git']:
        print("\n" + "!" * 80)
        print("!!! КРИТИЧЕСКАЯ УЯЗВИМИОСТЬ БЕЗОПАСНОСТИ !!!")
        print("!!! Обнаружены приватные SSL-ключи в системе контроля версий !!!")
        print("!" * 80)

        if not args.force:
            print("\nЭто позволяет любому получить доступ к зашифрованному трафику.")
            print("Ключи БУДУТ удалены из рабочей директории и добавлены в .gitignore.")
            response = input("\nПодтвердите удаление ключей (да/нет): ").strip().lower()
            if response not in ['да', 'yes', 'y']:
                print("❌ Операция отменена")
                return 1

    generator.run_secure_setup(
        common_name=args.common_name,
        production=args.production,
        domain=args.domain,
        email=args.email
    )

    return 0


if __name__ == "__main__":
    exit(main())