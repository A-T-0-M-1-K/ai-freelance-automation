# AI_FREELANCE_AUTOMATION/tests/unit/test_monitoring_system.py
"""
Unit tests for the Intelligent Monitoring System.
Validates core functionality: metrics collection, anomaly detection,
threshold management, and alert triggering.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
import os
from datetime import datetime

# Import the system under test
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.anomaly_detection import AnomalyDetector
from core.monitoring.alert_manager import AlertManager


class TestIntelligentMonitoringSystem(unittest.TestCase):
    """Test suite for IntelligentMonitoringSystem."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a minimal valid config mock
        self.mock_config = Mock(spec=UnifiedConfigManager)
        self.mock_config.get.return_value = {
            "metrics": {
                "enabled": True,
                "collection_interval_sec": 10,
                "retention_days": 7
            },
            "anomaly_detection": {
                "enabled": True,
                "sensitivity": 0.85
            },
            "alerts": {
                "enabled": True,
                "channels": ["log"]
            }
        }

        # Mock dependencies
        self.mock_anomaly_detector = Mock(spec=AnomalyDetector)
        self.mock_alert_manager = Mock(spec=AlertManager)

        # Patch constructor dependencies to avoid real initialization
        with patch('core.monitoring.anomaly_detection.AnomalyDetector', return_value=self.mock_anomaly_detector), \
             patch('core.monitoring.alert_manager.AlertManager', return_value=self.mock_alert_manager):
            self.monitoring_system = IntelligentMonitoringSystem(config=self.mock_config)

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'temp_log_file') and os.path.exists(self.temp_log_file):
            os.unlink(self.temp_log_file)

    def test_initialization_success(self):
        """Test that the monitoring system initializes correctly with valid config."""
        self.assertIsNotNone(self.monitoring_system)
        self.assertTrue(self.monitoring_system.is_active)
        self.mock_config.get.assert_any_call("metrics")

    def test_collect_metric_valid_input(self):
        """Test metric collection with valid data."""
        metric_name = "cpu_usage"
        value = 42.5
        tags = {"component": "transcription_service"}

        self.monitoring_system.collect_metric(metric_name, value, tags)

        # Verify internal state or side effects
        collected = self.monitoring_system._get_recent_metrics(metric_name, limit=1)
        self.assertEqual(len(collected), 1)
        self.assertAlmostEqual(collected[0]["value"], value, places=1)
        self.assertEqual(collected[0]["tags"], tags)
        self.assertIn("timestamp", collected[0])

    def test_collect_metric_invalid_value(self):
        """Test that invalid metric values are rejected."""
        with self.assertRaises(ValueError):
            self.monitoring_system.collect_metric("invalid_metric", "not_a_number")

    def test_anomaly_detection_triggered(self):
        """Test that anomalies trigger alert pipeline."""
        # Simulate high CPU usage
        self.mock_anomaly_detector.detect.return_value = {
            "is_anomaly": True,
            "score": 0.92,
            "metric": "memory_usage",
            "threshold": 0.8
        }

        self.monitoring_system.collect_metric("memory_usage", 95.0, {"host": "worker-1"})

        # Force anomaly check (in real system this would be async or periodic)
        self.monitoring_system._run_anomaly_check()

        self.mock_anomaly_detector.detect.assert_called()
        self.mock_alert_manager.send_alert.assert_called_once()

    def test_anomaly_detection_not_triggered(self):
        """Test normal metrics do not trigger alerts."""
        self.mock_anomaly_detector.detect.return_value = {"is_anomaly": False}

        self.monitoring_system.collect_metric("disk_io", 12.3)

        self.monitoring_system._run_anomaly_check()

        self.mock_alert_manager.send_alert.assert_not_called()

    def test_export_metrics_to_file(self):
        """Test exporting metrics to JSON file."""
        self.monitoring_system.collect_metric("test_metric", 100.0, {"env": "test"})

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
            self.temp_log_file = tmp.name

        self.monitoring_system.export_metrics(filepath=self.temp_log_file)

        with open(self.temp_log_file, 'r') as f:
            data = json.load(f)

        self.assertIn("metrics", data)
        self.assertEqual(len(data["metrics"]), 1)
        self.assertEqual(data["metrics"][0]["name"], "test_metric")
        self.assertEqual(data["metrics"][0]["value"], 100.0)

    def test_system_health_status(self):
        """Test health status reporting."""
        status = self.monitoring_system.get_health_status()
        self.assertIsInstance(status, dict)
        self.assertIn("status", status)
        self.assertIn("last_updated", status)
        self.assertEqual(status["status"], "healthy")

    def test_disable_monitoring_via_config(self):
        """Test that monitoring can be disabled via config."""
        self.mock_config.get.return_value = {"enabled": False}
        with patch('core.monitoring.anomaly_detection.AnomalyDetector'), \
             patch('core.monitoring.alert_manager.AlertManager'):
            disabled_system = IntelligentMonitoringSystem(config=self.mock_config)

        self.assertFalse(disabled_system.is_active)
        disabled_system.collect_metric("should_ignore", 1.0)
        # Should not raise, but also not store
        self.assertEqual(len(disabled_system._get_recent_metrics("should_ignore")), 0)

    @patch('core.monitoring.intelligent_monitoring_system.logging')
    def test_error_handling_in_collection(self, mock_logging):
        """Test graceful error handling during metric collection."""
        # Simulate internal error
        original_func = self.monitoring_system._store_metric
        self.monitoring_system._store_metric = Mock(side_effect=Exception("Storage failure"))

        self.monitoring_system.collect_metric("risky_metric", 50.0)

        mock_logging.error.assert_called()
        self.assertIn("Failed to collect metric", mock_logging.error.call_args[0][0])


if __name__ == '__main__':
    unittest.main()