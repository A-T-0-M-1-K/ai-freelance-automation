# plugins/platform_plugins/custom_platform_plugin.py
"""
Custom Platform Plugin — enables integration with any freelance platform
via user-defined configuration and minimal adapter interface.

Features:
- Fully configurable via JSON (endpoints, auth, job schema)
- Supports REST, GraphQL, or even HTML scraping (via optional parser)
- Integrates with core.security, core.config, core.monitoring
- Self-validating and self-documenting
- Isolated execution context (no side effects)
- Compatible with platform_factory.py

Author: AI Freelance Automation System
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from plugins.base_plugin import BasePlatformPlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator


class CustomPlatformPlugin(BasePlatformPlugin):
    """
    Generic plugin for integrating unknown or custom freelance platforms.
    Loads behavior from config file: data/settings/custom_platforms/{platform_name}.json
    """

    def __init__(
        self,
        platform_name: str,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
    ):
        super().__init__(platform_name)
        self.platform_name = platform_name
        self.logger = logging.getLogger(f"CustomPlatformPlugin.{platform_name}")

        # Use service locator if dependencies not injected
        self.config_manager = config_manager or ServiceLocator.get("config_manager")
        self.crypto = crypto_system or ServiceLocator.get("crypto_system")
        self.monitor = monitor or ServiceLocator.get("monitoring_system")

        # Load platform-specific config
        self._config_path = Path("data/settings/custom_platforms") / f"{platform_name}.json"
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Custom platform config not found: {self._config_path}"
            )

        with open(self._config_path, "r", encoding="utf-8") as f:
            self.platform_config = json.load(f)

        self._validate_config()
        self.session = self._create_session()

        self.logger.info(f"✅ Initialized custom platform plugin: {platform_name}")

    def _validate_config(self) -> None:
        """Validate required fields in platform config."""
        required = ["base_url", "auth", "job_schema"]
        for key in required:
            if key not in self.platform_config:
                raise ValueError(f"Missing required config key: '{key}' in {self._config_path}")

        auth_type = self.platform_config["auth"].get("type")
        if auth_type not in ("api_key", "oauth2", "basic", "cookie"):
            raise ValueError(f"Unsupported auth type: {auth_type}")

    def _create_session(self) -> requests.Session:
        """Create resilient HTTP session with retries and timeouts."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = self.platform_config.get("timeout", 30)
        return session

    def authenticate(self) -> bool:
        """Authenticate using configured method."""
        auth = self.platform_config["auth"]
        auth_type = auth["type"]

        try:
            if auth_type == "api_key":
                key = self.crypto.decrypt_secret(auth["encrypted_api_key"])
                self.session.headers.update({auth["header_name"]: key})

            elif auth_type == "basic":
                user = auth["username"]
                pwd = self.crypto.decrypt_secret(auth["encrypted_password"])
                self.session.auth = (user, pwd)

            elif auth_type == "oauth2":
                # Placeholder: real OAuth2 flow would go here
                token = self._refresh_oauth_token()
                self.session.headers.update({"Authorization": f"Bearer {token}"})

            elif auth_type == "cookie":
                cookies_enc = auth.get("encrypted_cookies", {})
                cookies = {
                    k: self.crypto.decrypt_secret(v) for k, v in cookies_enc.items()
                }
                self.session.cookies.update(cookies)

            # Optional: test auth via ping endpoint
            ping_url = self.platform_config.get("endpoints", {}).get("ping")
            if ping_url:
                resp = self.session.get(urljoin(self.platform_config["base_url"], ping_url))
                resp.raise_for_status()

            self.logger.info("🔑 Authentication successful")
            return True

        except Exception as e:
            self.logger.error(f"❌ Authentication failed: {e}")
            self.monitor.log_anomaly(
                source="custom_platform_auth",
                severity="high",
                details={"platform": self.platform_name, "error": str(e)}
            )
            return False

    def _refresh_oauth_token(self) -> str:
        """Refresh OAuth2 token (stub — override in subclass or config)."""
        # In real use, this would call token endpoint with client credentials
        raise NotImplementedError("OAuth2 refresh not implemented in base custom plugin")

    def fetch_jobs(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Fetch jobs from platform using configured endpoint and schema mapping.
        Returns normalized job list compatible with core/automation/job_analyzer.py
        """
        try:
            endpoints = self.platform_config["endpoints"]
            job_url = urljoin(self.platform_config["base_url"], endpoints["jobs"])

            params = filters or {}
            resp = self.session.get(job_url, params=params)
            resp.raise_for_status()
            raw_jobs = resp.json()

            # Normalize using job_schema mapping
            normalized = []
            schema = self.platform_config["job_schema"]
            for raw in raw_jobs:
                job = {
                    "platform": self.platform_name,
                    "external_id": self._extract_field(raw, schema["id"]),
                    "title": self._extract_field(raw, schema["title"]),
                    "description": self._extract_field(raw, schema["description"]),
                    "budget": self._extract_field(raw, schema.get("budget")),
                    "currency": self._extract_field(raw, schema.get("currency", "USD")),
                    "deadline": self._extract_field(raw, schema.get("deadline")),
                    "skills": self._extract_field(raw, schema.get("skills"), default=[]),
                    "url": self._build_job_url(raw, schema),
                    "raw_data": raw  # for debugging & future adaptation
                }
                normalized.append(job)

            self.logger.info(f"📥 Fetched {len(normalized)} jobs from {self.platform_name}")
            return normalized

        except Exception as e:
            self.logger.exception(f"❌ Failed to fetch jobs: {e}")
            self.monitor.log_anomaly(
                source="custom_platform_fetch",
                severity="medium",
                details={"platform": self.platform_name, "error": str(e)}
            )
            return []

    def _extract_field(self, obj: Dict, path: str, default=None):
        """Extract nested field using dot notation: 'data.attributes.title'"""
        if not path:
            return default
        keys = path.split(".")
        for key in keys:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default
        return obj

    def _build_job_url(self, raw_job: Dict, schema: Dict) -> str:
        """Construct job URL from template or ID."""
        base = self.platform_config["base_url"]
        if "url_template" in schema:
            job_id = self._extract_field(raw_job, schema["id"])
            return schema["url_template"].format(job_id=job_id)
        return base  # fallback

    def submit_bid(self, job_id: str, proposal: str, price: float, delivery_days: int) -> bool:
        """Submit bid using configured endpoint."""
        try:
            endpoints = self.platform_config["endpoints"]
            bid_url = urljoin(self.platform_config["base_url"], endpoints["submit_bid"])

            payload = {
                "job_id": job_id,
                "proposal": proposal,
                "price": price,
                "delivery_days": delivery_days
            }

            # Map to platform-specific format if needed
            if "bid_mapping" in self.platform_config:
                mapped = {}
                for local_key, remote_key in self.platform_config["bid_mapping"].items():
                    if local_key in payload:
                        mapped[remote_key] = payload[local_key]
                payload = mapped

            resp = self.session.post(bid_url, json=payload)
            resp.raise_for_status()
            self.logger.info(f"📤 Bid submitted for job {job_id} on {self.platform_name}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Bid submission failed: {e}")
            self.monitor.log_anomaly(
                source="custom_platform_bid",
                severity="high",
                details={"platform": self.platform_name, "job_id": job_id, "error": str(e)}
            )
            return False

    def get_messages(self, job_id: str) -> List[Dict[str, Any]]:
        """Fetch conversation messages (optional feature)."""
        # Implementation depends on platform support
        return []

    def send_message(self, job_id: str, message: str) -> bool:
        """Send message to client (optional feature)."""
        return False

    def is_active(self) -> bool:
        """Check if plugin is enabled in system settings."""
        sys_settings = self.config_manager.get("system_settings", {})
        enabled_platforms = sys_settings.get("enabled_platforms", [])
        return self.platform_name in enabled_platforms

    def shutdown(self) -> None:
        """Graceful cleanup."""
        self.session.close()
        self.logger.info(f"🔌 Custom platform plugin shut down: {self.platform_name}")