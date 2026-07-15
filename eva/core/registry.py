"""
Plugin registry for EVA evaluation harness.

Thread-safe registry for evaluators, datasets, reporters, and test suites.
Supports auto-discovery via module scanning.
"""

import importlib
import inspect
import logging
import pkgutil
import threading
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

PluginClass = TypeVar("PluginClass")


class RegistryError(Exception):
    """Raised on plugin registry operations errors."""


class PluginRegistry:
    """Thread-safe plugin registry for evaluators, datasets, reporters, and tests.

    Categories:
        - evaluator: Scoring/evaluation plugins
        - dataset: Dataset format loaders
        - reporter: Report generation plugins
        - test: Test suite plugins
    """

    _registries: Dict[str, Dict[str, Type]] = {
        "evaluator": {},
        "dataset": {},
        "reporter": {},
        "test": {},
    }
    _lock = threading.RLock()

    @classmethod
    def register(cls, category: str, name: str, plugin_class: Type) -> None:
        """Register a plugin class.

        Args:
            category: Plugin category (evaluator, dataset, reporter, test).
            name: Plugin name (used for lookup).
            plugin_class: The class to register.

        Raises:
            RegistryError: If category is invalid or name already registered.
        """
        if category not in cls._registries:
            raise RegistryError(f"Invalid category: {category}. "
                                f"Valid: {list(cls._registries.keys())}")

        with cls._lock:
            if name in cls._registries[category]:
                logger.warning("Overwriting existing %s '%s'", category, name)
            cls._registries[category][name] = plugin_class
            logger.debug("Registered %s '%s': %s", category, name, plugin_class.__name__)

    @classmethod
    def get(cls, category: str, name: str) -> Optional[Type]:
        """Get a registered plugin class by category and name.

        Args:
            category: Plugin category.
            name: Plugin name.

        Returns:
            Plugin class or None if not found.
        """
        with cls._lock:
            return cls._registries.get(category, {}).get(name)

    @classmethod
    def list(cls, category: str) -> List[str]:
        """List all registered plugin names in a category.

        Args:
            category: Plugin category.

        Returns:
            List of plugin names.
        """
        with cls._lock:
            return list(cls._registries.get(category, {}).keys())

    @classmethod
    def unregister(cls, category: str, name: str) -> bool:
        """Unregister a plugin.

        Args:
            category: Plugin category.
            name: Plugin name.

        Returns:
            True if plugin was removed, False if not found.
        """
        with cls._lock:
            if category in cls._registries and name in cls._registries[category]:
                del cls._registries[category][name]
                logger.debug("Unregistered %s '%s'", category, name)
                return True
            return False

    @classmethod
    def discover(cls, package_name: str = "eva") -> int:
        """Auto-discover plugins by scanning modules.

        Scans all submodules of the given package for classes that
        inherit from known base classes and register themselves.

        Args:
            package_name: Root package to scan.

        Returns:
            Number of plugins discovered.
        """
        count = 0
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning("Package '%s' not found, skipping discovery", package_name)
            return 0

        def _scan_module(mod_name: str, mod) -> None:
            discovered = 0
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if obj.__module__ != mod.__name__:
                    continue
                # Check for registration markers
                if hasattr(obj, "_eva_plugin_category") and hasattr(obj, "_eva_plugin_name"):
                    cat = obj._eva_plugin_category
                    pname = obj._eva_plugin_name
                    cls.register(cat, pname, obj)
                    discovered += 1
            return discovered

        # Walk all submodules
        if hasattr(package, "__path__"):
            for importer, modname, ispkg in pkgutil.walk_packages(
                package.__path__, package.__name__ + "."
            ):
                try:
                    module = importlib.import_module(modname)
                    count += _scan_module(modname, module)
                except Exception as e:
                    logger.debug("Error scanning module %s: %s", modname, e)

        logger.info("Plugin discovery complete: %d plugins found", count)
        return count

    @classmethod
    def create(cls, category: str, name: str, **kwargs: Any) -> Any:
        """Create an instance of a registered plugin.

        Args:
            category: Plugin category.
            name: Plugin name.
            **kwargs: Arguments to pass to the constructor.

        Returns:
            Instance of the plugin class.

        Raises:
            KeyError: If plugin not found.
        """
        plugin_class = cls.get(category, name)
        if plugin_class is None:
            raise KeyError(f"Plugin '{name}' not found in category '{category}'")
        return plugin_class(**kwargs)

    @classmethod
    def get_all_instances(cls, category: str, **kwargs: Any) -> Dict[str, Any]:
        """Create instances of all registered plugins in a category.

        Args:
            category: Plugin category.
            **kwargs: Arguments to pass to each constructor.

        Returns:
            Dict mapping plugin name to instance.
        """
        instances = {}
        for name in cls.list(category):
            try:
                instances[name] = cls.create(category, name, **kwargs)
            except Exception as e:
                logger.error("Failed to create %s '%s': %s", category, name, e)
        return instances


def plugin(category: str, name: str):
    """Decorator to register a class as a plugin.

    Usage:
        @plugin("evaluator", "exact_match")
        class ExactMatchEvaluator(BaseEvaluator):
            ...
    """
    def decorator(cls):
        cls._eva_plugin_category = category
        cls._eva_plugin_name = name
        # Auto-register on import
        try:
            PluginRegistry.register(category, name, cls)
        except RegistryError:
            pass
        return cls
    return decorator
