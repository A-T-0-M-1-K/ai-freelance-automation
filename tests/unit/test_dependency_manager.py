# AI_FREELANCE_AUTOMATION/tests/unit/test_dependency_manager.py
"""
Unit tests for the DependencyManager in core/dependency/dependency_manager.py.
Ensures proper registration, resolution, and lifecycle management of dependencies
without circular imports or conflicts.
"""

import pytest
from unittest.mock import Mock, MagicMock
from core.dependency.dependency_manager import DependencyManager


class TestServiceA:
    def __init__(self, name: str = "ServiceA"):
        self.name = name

    def do_work(self) -> str:
        return f"{self.name} working"


class TestServiceB:
    def __init__(self, service_a: TestServiceA):
        self.service_a = service_a

    def delegate_work(self) -> str:
        return f"ServiceB delegates to {self.service_a.do_work()}"


class TestServiceC:
    """Service with no dependencies."""
    def ping(self) -> str:
        return "pong"


@pytest.fixture
def dependency_manager():
    """Fresh DependencyManager instance for each test."""
    return DependencyManager()


def test_register_and_resolve_simple_service(dependency_manager):
    """Test basic registration and resolution of a service with no dependencies."""
    dependency_manager.register("service_c", TestServiceC)

    instance = dependency_manager.resolve("service_c")
    assert isinstance(instance, TestServiceC)
    assert instance.ping() == "pong"


def test_register_singleton_vs_transient(dependency_manager):
    """Test that singleton returns same instance, transient returns new instances."""
    dependency_manager.register("service_a_singleton", TestServiceA, singleton=True)
    instance1 = dependency_manager.resolve("service_a_singleton")
    instance2 = dependency_manager.resolve("service_a_singleton")
    assert instance1 is instance2  # Same object

    dependency_manager.register("service_a_transient", TestServiceA, singleton=False)
    instance3 = dependency_manager.resolve("service_a_transient")
    instance4 = dependency_manager.resolve("service_a_transient")
    assert instance3 is not instance4  # Different objects


def test_automatic_dependency_injection(dependency_manager):
    """Test that dependencies are auto-resolved when constructor hints are present."""
    dependency_manager.register("service_a", TestServiceA, singleton=True)
    dependency_manager.register("service_b", TestServiceB, singleton=True)

    service_b = dependency_manager.resolve("service_b")
    assert isinstance(service_b, TestServiceB)
    assert isinstance(service_b.service_a, TestServiceA)
    assert service_b.delegate_work() == "ServiceB delegates to ServiceA working"


def test_resolve_nonexistent_service_raises_error(dependency_manager):
    """Test that resolving unregistered service raises KeyError."""
    with pytest.raises(KeyError, match="Service 'nonexistent' not registered"):
        dependency_manager.resolve("nonexistent")


def test_register_with_factory_function(dependency_manager):
    """Test registration using a custom factory."""
    def factory():
        return TestServiceA(name="CustomFactoryService")

    dependency_manager.register("factory_service", factory, use_factory=True)
    instance = dependency_manager.resolve("factory_service")
    assert instance.name == "CustomFactoryService"


def test_clear_dependencies(dependency_manager):
    """Test that clear() removes all registered services."""
    dependency_manager.register("temp", TestServiceC)
    assert "temp" in dependency_manager._registry

    dependency_manager.clear()
    assert len(dependency_manager._registry) == 0

    with pytest.raises(KeyError):
        dependency_manager.resolve("temp")


def test_is_registered_method(dependency_manager):
    """Test the is_registered helper method."""
    dependency_manager.register("checker", TestServiceC)
    assert dependency_manager.is_registered("checker") is True
    assert dependency_manager.is_registered("missing") is False


def test_dependency_manager_is_thread_safe_under_normal_load():
    """
    Basic check that the manager doesn't crash under concurrent access.
    Full thread-safety requires deeper testing (e.g., with stress tests),
    but this ensures no obvious race conditions in simple usage.
    """
    import threading

    dependency_manager.register("shared", TestServiceA, singleton=True)

    results = []

    def worker():
        try:
            inst = dependency_manager.resolve("shared")
            results.append(inst.name)
        except Exception as e:
            results.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All should succeed and refer to the same instance
    assert all(r == "ServiceA" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])