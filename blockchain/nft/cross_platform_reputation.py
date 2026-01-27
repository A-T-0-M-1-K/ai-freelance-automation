"""
Децентрализованная система репутации "кросс-платформенно" через NFT.
Единый рейтинг фрилансера на всех площадках, закрепленный в блокчейне.
"""

import json
import hashlib
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import time

from blockchain.wallet_manager import WalletManager
from blockchain.smart_contract_manager import SmartContractManager
from core.security.encryption_engine import EncryptionEngine


@dataclass
class ReputationScore:
    """Оценка репутации на одной платформе"""
    platform: str
    rating: float  # 0.0 - 5.0
    reviews_count: int
    completion_rate: float  # % успешно завершенных заказов
    on_time_delivery_rate: float
    dispute_rate: float  # % спорных ситуаций
    timestamp: datetime
    platform_signature: str  # Подпись платформы для верификации


@dataclass
class CrossPlatformReputation:
    """Кросс-платформенная репутация"""
    freelancer_wallet: str
    reputation_nft_id: str
    overall_score: float  # Взвешенный средний рейтинг по всем платформам
    scores: List[ReputationScore]
    total_reviews: int
    total_earnings_usd: float
    active_since: datetime
    last_updated: datetime
    metadata_hash: str  # Хеш метаданных для верификации целостности


class CrossPlatformReputationSystem:
    """
    Система кросс-платформенной репутации с использованием NFT:
    - Агрегация рейтингов со всех платформ (Upwork, Freelance.ru, Kwork и др.)
    - Расчет единого взвешенного рейтинга
    - Выпуск уникального NFT с репутацией в блокчейне
    - Верификация подлинности рейтингов через криптографические подписи платформ
    - Возможность демонстрации репутации на любой платформе через ссылку на NFT
    """

    def __init__(self,
                 blockchain_network: str = 'polygon',  # Polygon для низких комиссий
                 contract_address: Optional[str] = None):
        self.wallet_manager = WalletManager()
        self.smart_contract_manager = SmartContractManager(network=blockchain_network)
        self.encryption_engine = EncryptionEngine()
        self.contract_address = contract_address or self._get_default_contract_address(blockchain_network)

        # ABI контракта репутационных NFT
        self.contract_abi = self._load_contract_abi()

    def _get_default_contract_address(self, network: str) -> str:
        """Получение адреса контракта по сети"""
        addresses = {
            'polygon': '0x1234567890abcdef1234567890abcdef12345678',
            'ethereum': '0xabcdef1234567890abcdef1234567890abcdef12',
            'binance': '0x7890abcdef1234567890abcdef1234567890abcd'
        }
        return addresses.get(network, addresses['polygon'])

    def _load_contract_abi(self) -> List[Dict[str, Any]]:
        """Загрузка ABI контракта репутационных NFT"""
        # Упрощенный ABI для примера
        return [
            {
                "inputs": [
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "string", "name": "tokenURI", "type": "string"},
                    {"internalType": "uint256", "name": "score", "type": "uint256"}
                ],
                "name": "mintReputationNFT",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
                "name": "getReputationScore",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

    def collect_platform_scores(self, freelancer_id: str, platforms: List[str]) -> List[ReputationScore]:
        """
        Сбор рейтингов со всех подключенных платформ.
        Интеграция через официальные API или скрапинг с верификацией.
        """
        scores = []

        for platform in platforms:
            try:
                score = self._fetch_platform_reputation(freelancer_id, platform)
                if score:
                    scores.append(score)
            except Exception as e:
                print(f"⚠️ Ошибка сбора рейтинга с {platform}: {e}")

        return scores

    def _fetch_platform_reputation(self, freelancer_id: str, platform: str) -> Optional[ReputationScore]:
        """Получение рейтинга с конкретной платформы"""
        # Интеграция с адаптерами платформ
        from platforms.platform_factory import PlatformFactory

        try:
            platform_adapter = PlatformFactory.get_adapter(platform)
            profile = platform_adapter.get_freelancer_profile(freelancer_id)

            return ReputationScore(
                platform=platform,
                rating=float(profile.get('rating', 0.0)),
                reviews_count=int(profile.get('reviews_count', 0)),
                completion_rate=float(profile.get('completion_rate', 0.0)),
                on_time_delivery_rate=float(profile.get('on_time_rate', 0.0)),
                dispute_rate=float(profile.get('dispute_rate', 0.0)),
                timestamp=datetime.now(),
                platform_signature=self._generate_platform_signature(platform, profile)
            )
        except Exception as e:
            print(f"⚠️ Ошибка получения профиля с {platform}: {e}")
            return None

    def _generate_platform_signature(self, platform: str, profile: Dict[str, Any]) -> str:
        """Генерация криптографической подписи платформы для верификации данных"""
        # В реальной системе — подпись приватным ключом платформы
        # Для примера — хеш критических полей
        signature_data = f"{platform}:{profile.get('freelancer_id')}:{profile.get('rating')}:{profile.get('reviews_count')}"
        return hashlib.sha256(signature_data.encode()).hexdigest()

    def calculate_overall_score(self, scores: List[ReputationScore]) -> float:
        """
        Расчет взвешенного общего рейтинга с учетом:
        - Количества отзывов (больше отзывов = выше вес)
        - Давности данных (свежие данные важнее)
        - Надежности платформы (проверенные платформы имеют больший вес)
        """
        if not scores:
            return 0.0

        # Веса платформ по надежности (упрощенно)
        platform_weights = {
            'upwork': 1.0,
            'freelancer_com': 1.0,
            'toptal': 1.2,  # Премиум платформа — выше вес
            'freelance_ru': 0.9,
            'kwork': 0.85,
            'habr_freelance': 0.9,
            'profi_ru': 0.8
        }

        total_weighted_score = 0.0
        total_weight = 0.0

        for score in scores:
            # Базовый вес платформы
            platform_weight = platform_weights.get(score.platform.lower(), 0.7)

            # Вес по количеству отзывов (логарифмический рост)
            reviews_weight = min(1.0 + (score.reviews_count / 100) ** 0.5, 2.0)

            # Вес по свежести данных (данные старше года теряют вес)
            days_old = (datetime.now() - score.timestamp).days
            freshness_weight = max(0.5, 1.0 - (days_old / 365) * 0.5)

            # Итоговый вес записи
            weight = platform_weight * reviews_weight * freshness_weight

            # Взвешенный вклад в общий рейтинг
            weighted_score = score.rating * weight

            total_weighted_score += weighted_score
            total_weight += weight

        overall_score = total_weighted_score / total_weight if total_weight > 0 else 0.0

        # Нормализация в диапазон 0-5
        return min(5.0, max(0.0, overall_score))

    def mint_reputation_nft(self,
                            freelancer_wallet: str,
                            scores: List[ReputationScore],
                            overall_score: float,
                            total_earnings_usd: float) -> CrossPlatformReputation:
        """
        Выпуск NFT с кросс-платформенной репутацией в блокчейне.
        NFT содержит метаданные с агрегированным рейтингом и ссылками на профили.
        """
        # Формирование метаданных NFT
        metadata = {
            'name': f'Reputation Score #{freelancer_wallet[:8]}',
            'description': 'Кросс-платформенный рейтинг фрилансера',
            'image': 'https://ai-freelance-automation.io/nft/reputation-badge.png',
            'attributes': [
                {'trait_type': 'Overall Score', 'value': round(overall_score, 2)},
                {'trait_type': 'Total Reviews', 'value': sum(s.reviews_count for s in scores)},
                {'trait_type': 'Platforms', 'value': len(scores)},
                {'trait_type': 'Total Earnings (USD)', 'value': round(total_earnings_usd, 0)},
                {'trait_type': 'Active Since', 'value': min(s.timestamp for s in scores).strftime('%Y-%m-%d')}
            ],
            'platform_scores': [asdict(score) for score in scores],
            'freelancer_wallet': freelancer_wallet,
            'minted_at': datetime.now().isoformat(),
            'contract_address': self.contract_address
        }

        # Хеширование метаданных для верификации целостности
        metadata_json = json.dumps(metadata, sort_keys=True)
        metadata_hash = hashlib.sha256(metadata_json.encode()).hexdigest()

        # Сохранение метаданных в IPFS (симуляция)
        ipfs_hash = self._upload_to_ipfs(metadata_json)

        # Выпуск NFT через смарт-контракт
        try:
            contract = self.smart_contract_manager.get_contract(self.contract_address, self.contract_abi)

            # Вызов функции минта
            tx_hash = contract.functions.mintReputationNFT(
                freelancer_wallet,
                f"ipfs://{ipfs_hash}",
                int(overall_score * 100)  # Конвертация в целое число (0-500)
            ).transact({'from': freelancer_wallet})

            # Ожидание подтверждения транзакции
            receipt = self.smart_contract_manager.wait_for_transaction(tx_hash)
            token_id = receipt.get('logs', [{}])[0].get('topics', [None, None])[1]  # Упрощенно

            reputation = CrossPlatformReputation(
                freelancer_wallet=freelancer_wallet,
                reputation_nft_id=str(int(token_id, 16)) if token_id else f"pending_{int(time.time())}",
                overall_score=overall_score,
                scores=scores,
                total_reviews=sum(s.reviews_count for s in scores),
                total_earnings_usd=total_earnings_usd,
                active_since=min(s.timestamp for s in scores),
                last_updated=datetime.now(),
                metadata_hash=metadata_hash
            )

            # Сохранение локальной копии репутации
            self._save_reputation_locally(reputation)

            print(f"✅ NFT репутации выпущен! Token ID: {reputation.reputation_nft_id}")
            print(f"   Общий рейтинг: {overall_score:.2f}/5.0")
            print(
                f"   Ссылка на NFT: https://polygonscan.com/token/{self.contract_address}?a={reputation.reputation_nft_id}")

            return reputation

        except Exception as e:
            print(f"❌ Ошибка выпуска NFT: {e}")
            raise

    def _upload_to_ipfs(self, data: str) -> str:
        """Загрузка метаданных в IPFS (симуляция)"""
        # В реальной системе — интеграция с Pinata/IPFS HTTP client
        # Для примера возвращаем хеш данных
        return hashlib.sha256(data.encode()).hexdigest()[:46]  # Симуляция CID

    def _save_reputation_locally(self, reputation: CrossPlatformReputation):
        """Сохранение локальной копии репутации для быстрого доступа"""
        reputation_dir = Path("data/reputation")
        reputation_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{reputation.freelancer_wallet[:8]}_{reputation.last_updated.strftime('%Y%m%d')}.json"
        filepath = reputation_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(asdict(reputation), f, indent=2, ensure_ascii=False, default=str)

    def verify_reputation_nft(self, token_id: str) -> Dict[str, Any]:
        """
        Верификация подлинности NFT репутации:
        - Проверка существования токена в блокчейне
        - Проверка целостности метаданных через хеш
        - Проверка подписей платформ
        """
        try:
            contract = self.smart_contract_manager.get_contract(self.contract_address, self.contract_abi)

            # Получение данных из блокчейна
            score = contract.functions.getReputationScore(int(token_id)).call()
            owner = contract.functions.ownerOf(int(token_id)).call()

            # Загрузка метаданных из IPFS
            metadata = self._fetch_metadata_from_ipfs(token_id)

            # Проверка целостности
            metadata_json = json.dumps(metadata, sort_keys=True)
            calculated_hash = hashlib.sha256(metadata_json.encode()).hexdigest()

            verification_result = {
                'token_id': token_id,
                'exists': True,
                'owner': owner,
                'on_chain_score': score / 100.0,
                'metadata_integrity': calculated_hash == metadata.get('metadata_hash', ''),
                'platform_signatures_valid': self._verify_platform_signatures(metadata.get('platform_scores', [])),
                'verified_at': datetime.now().isoformat()
            }

            return verification_result

        except Exception as e:
            return {
                'token_id': token_id,
                'exists': False,
                'error': str(e),
                'verified_at': datetime.now().isoformat()
            }

    def _fetch_metadata_from_ipfs(self, token_id: str) -> Dict[str, Any]:
        """Получение метаданных NFT из IPFS"""
        # Симуляция — в реальной системе запрос к IPFS шлюзу
        return {
            'name': f'Reputation Score #{token_id}',
            'overall_score': 4.85,
            'platform_scores': [],
            'metadata_hash': 'abc123...'
        }

    def _verify_platform_signatures(self, platform_scores: List[Dict[str, Any]]) -> bool:
        """Верификация подписей всех платформ"""
        # В реальной системе — криптографическая проверка подписей публичными ключами платформ
        return all(score.get('platform_signature') for score in platform_scores)

    def generate_reputation_badge(self, reputation: CrossPlatformReputation) -> str:
        """
        Генерация визуального бейджа репутации для размещения на сайтах/платформах.
        Возвращает HTML/SVG код бейджа со ссылкой на NFT в блокчейне.
        """
        # Определение уровня репутации
        if reputation.overall_score >= 4.8:
            level = "Platinum"
            color = "#e5e4e2"
            badge_color = "#b1b2b3"
        elif reputation.overall_score >= 4.5:
            level = "Gold"
            color = "#FFD700"
            badge_color = "#FFA500"
        elif reputation.overall_score >= 4.0:
            level = "Silver"
            color = "#C0C0C0"
            badge_color = "#808080"
        elif reputation.overall_score >= 3.5:
            level = "Bronze"
            color = "#CD7F32"
            badge_color = "#8B4513"
        else:
            level = "Emerging"
            color = "#B87333"
            badge_color = "#654321"

        # Генерация SVG бейджа
        badge_svg = f"""
<svg width="200" height="60" xmlns="http://www.w3.org/2000/svg">
  <rect width="200" height="60" rx="8" fill="{badge_color}" />
  <rect x="5" y="5" width="190" height="50" rx="6" fill="#ffffff" />

  <text x="15" y="20" font-family="Arial, sans-serif" font-size="14" fill="#333333" font-weight="bold">
    CROSS-PLATFORM REPUTATION
  </text>

  <text x="15" y="40" font-family="Arial, sans-serif" font-size="24" fill="{color}" font-weight="bold">
    {reputation.overall_score:.1f}/5.0
  </text>

  <text x="120" y="40" font-family="Arial, sans-serif" font-size="12" fill="#666666">
    {level} LEVEL
  </text>

  <text x="15" y="55" font-family="Arial, sans-serif" font-size="8" fill="#999999">
    NFT: {reputation.reputation_nft_id[:6]}... | Verified on Blockchain
  </text>
</svg>
        """

        # Генерация HTML виджета с ссылкой на блокчейн-эксплорер
        badge_html = f"""
<div class="reputation-badge" style="display: inline-block; font-family: Arial, sans-serif;">
  {badge_svg}
  <div style="text-align: center; margin-top: 4px; font-size: 10px;">
    <a href="https://polygonscan.com/token/{self.contract_address}?a={reputation.reputation_nft_id}" 
       target="_blank" 
       style="color: #0066cc; text-decoration: none;">
      View on Blockchain →
    </a>
  </div>
</div>
        """

        return badge_html


# Пример использования
if __name__ == "__main__":
    # Инициализация системы
    reputation_system = CrossPlatformReputationSystem(blockchain_network='polygon')

    # Сбор рейтингов со всех платформ
    freelancer_id = "freelancer_12345"
    platforms = ['upwork', 'freelance_ru', 'kwork', 'habr_freelance']

    scores = reputation_system.collect_platform_scores(freelancer_id, platforms)

    if not scores:
        print("❌ Не удалось собрать рейтинги ни с одной платформы")
        exit(1)

    # Расчет общего рейтинга
    overall_score = reputation_system.calculate_overall_score(scores)
    total_earnings = 15000.0  # Суммарный доход в USD (для примера)

    print(f"📊 Собраны рейтинги с {len(scores)} платформ")
    print(f"⭐ Общий кросс-платформенный рейтинг: {overall_score:.2f}/5.0")

    # Выпуск NFT (требуется кошелек)
    wallet_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"

    reputation = reputation_system.mint_reputation_nft(
        freelancer_wallet=wallet_address,
        scores=scores,
        overall_score=overall_score,
        total_earnings_usd=total_earnings
    )

    # Генерация бейджа для размещения на сайте
    badge_html = reputation_system.generate_reputation_badge(reputation)

    badge_file = Path("data/reputation/badge.html")
    badge_file.write_text(badge_html, encoding='utf-8')
    print(f"✅ Бейдж репутации сохранен: {badge_file}")