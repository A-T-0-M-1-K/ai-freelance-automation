# AI_FREELANCE_AUTOMATION/tests/unit/test_cache_system.py
"""
Unit tests for the intelligent cache system.
Validates correctness, performance, and integration with core components.
"""

import asyncio
import tempfile
import os
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

# Import the actual cache system under test
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.config.unified_config_manager import UnifiedConfigManager


class TestIntelligentCacheSystem(IsolatedAsyncioTestCase):
    """Test suite for IntelligentCacheSystem."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create a temporary config file
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = os.path.join(self.temp_dir.name, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Mock minimal config
        self.mock_config_data = {
            "performance": {
                "cache": {
                    "enabled": True,
                    "max_size_mb": 100,
                    "ttl_seconds": 3600,
                    "strategy": "lru",
                    "storage_path": self.cache_dir,
                    "compression": True,
                    "metrics_collection": True
                }
            }
        }

        # Mock config manager
        self.mock_config = MagicMock(spec=UnifiedConfigManager)
        self.mock_config.get.return_value = self.mock_config_data["performance"]["cache"]
        self.mock_config.get_nested.return_value = self.mock_config_data

    def tearDown(self):
        """Clean up after each test."""
        self.temp_dir.cleanup()

    async def test_cache_initialization(self):
        """Test that cache initializes correctly with valid config."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        self.assertTrue(cache.is_initialized)
        self.assertEqual(cache.storage_path, self.cache_dir)
        self.assertEqual(cache.max_size_bytes, 100 * 1024 * 1024)

    async def test_cache_set_and_get(self):
        """Test basic set/get functionality."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        key = "test_key"
        value = {"data": "example", "metadata": {"type": "job_analysis"}}

        await cache.set(key, value)
        retrieved = await cache.get(key)

        self.assertEqual(retrieved, value)

    async def test_cache_miss_returns_none(self):
        """Test that missing keys return None."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        result = await cache.get("nonexistent_key")
        self.assertIsNone(result)

    async def test_cache_eviction_lru(self):
        """Test LRU eviction when cache exceeds size limit."""
        # Configure tiny cache (1 KB)
        tiny_config = {
            "performance": {
                "cache": {
                    "enabled": True,
                    "max_size_mb": 0.001,  # ~1 KB
                    "ttl_seconds": 3600,
                    "strategy": "lru",
                    "storage_path": self.cache_dir,
                    "compression": False,
                    "metrics_collection": False
                }
            }
        }
        mock_config = MagicMock()
        mock_config.get.return_value = tiny_config["performance"]["cache"]

        cache = IntelligentCacheSystem(config=mock_config)
        await cache.initialize()

        # Add two large items (~600 bytes each)
        item1 = {"data": "x" * 600}
        item2 = {"data": "y" * 600}

        await cache.set("key1", item1)
        await cache.set("key2", item2)

        # key1 should be evicted (LRU)
        self.assertIsNone(await cache.get("key1"))
        self.assertIsNotNone(await cache.get("key2"))

    async def test_cache_ttl_expiration(self):
        """Test that entries expire after TTL."""
        with patch("core.performance.intelligent_cache_system.time") as mock_time:
            mock_time.time.return_value = 1000  # Fixed start time

            cache = IntelligentCacheSystem(config=self.mock_config)
            await cache.initialize()

            await cache.set("temp_key", {"value": 42}, ttl=10)

            # Simulate time passing
            mock_time.time.return_value = 1005
            self.assertIsNotNone(await cache.get("temp_key"))  # Not expired

            mock_time.time.return_value = 1015
            self.assertIsNone(await cache.get("temp_key"))  # Expired

    async def test_cache_clear(self):
        """Test cache clearing functionality."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        self.assertIsNotNone(await cache.get("key1"))
        self.assertIsNotNone(await cache.get("key2"))

        await cache.clear()

        self.assertIsNone(await cache.get("key1"))
        self.assertIsNone(await cache.get("key2"))

    async def test_cache_disabled_behavior(self):
        """Test that cache behaves as passthrough when disabled."""
        disabled_config = {
            "performance": {
                "cache": {
                    "enabled": False,
                    "max_size_mb": 100,
                    "ttl_seconds": 3600,
                    "strategy": "lru",
                    "storage_path": self.cache_dir
                }
            }
        }
        mock_config = MagicMock()
        mock_config.get.return_value = disabled_config["performance"]["cache"]

        cache = IntelligentCacheSystem(config=mock_config)
        await cache.initialize()

        # Should not store or retrieve anything
        await cache.set("key", "value")
        result = await cache.get("key")
        self.assertIsNone(result)

    async def test_cache_metrics_collection(self):
        """Test that cache collects metrics when enabled."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        await cache.set("a", 1)
        await cache.get("a")
        await cache.get("b")  # miss

        metrics = cache.get_metrics()
        self.assertEqual(metrics["hits"], 1)
        self.assertEqual(metrics["misses"], 1)
        self.assertEqual(metrics["writes"], 1)

    async def test_concurrent_access_safety(self):
        """Test that cache handles concurrent access safely."""
        cache = IntelligentCacheSystem(config=self.mock_config)
        await cache.initialize()

        key = "concurrent_key"
        value = {"counter": 0}

        async def writer():
            for i in range(10):
                await cache.set(key, {"counter": i})

        async def reader():
            results = []
            for _ in range(10):
                val = await cache.get(key)
                if val is not None:
                    results.append(val["counter"])
            return results

        # Run concurrent tasks
        await asyncio.gather(
            writer(),
            reader(),
            reader()
        )

        # No crash = success (basic thread safety via asyncio locks assumed)
        final_val = await cache.get(key)
        self.assertIsInstance(final_val, dict)

    async def test_persistence_across_restarts(self):
        """Test that cache persists to disk and reloads."""
        cache1 = IntelligentCacheSystem(config=self.mock_config)
        await cache1.initialize()
        await cache1.set("persistent", {"data": "saved"})
        await cache1.shutdown()

        # Reinitialize
        cache2 = IntelligentCacheSystem(config=self.mock_config)
        await cache2.initialize()

        restored = await cache2.get("persistent")
        self.assertEqual(restored, {"data": "saved"})


if __name__ == "__main__":
    import unittest
    unittest.main()