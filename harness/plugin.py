"""Friday AI Runtime Harness — Plugin System.

Discover, load, and manage plugins that extend harness functionality.
Supports lifecycle hooks, dependency declarations, and isolation.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .models import PluginHook, PluginPriority


class PluginManager:
    """Discovers, loads, and manages runtime plugins."""

    def __init__(self, plugin_dir: str = "plugins", auto_load: bool = True):
        self._plugin_dir = Path(plugin_dir)
        self._plugins: Dict[str, Dict[str, Any]] = {}
        self._hooks: Dict[str, List[Dict[str, Any]]] = {}
        self._hook_registry: Dict[str, PluginHook] = {}

        if auto_load and self._plugin_dir.exists():
            self.discover()

    def discover(self) -> List[str]:
        """Discover plugins in the plugin directory."""
        if not self._plugin_dir.exists():
            return []

        discovered = []
        sys.path.insert(0, str(self._plugin_dir.parent))

        for entry in sorted(self._plugin_dir.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").exists():
                name = entry.name
                if name not in self._plugins:
                    discovered.append(name)

        sys.path.pop(0)
        return discovered

    def load_plugin(self, name: str) -> bool:
        """Load a plugin by name."""
        if name in self._plugins:
            return True  # Already loaded

        try:
            sys.path.insert(0, str(self._plugin_dir.parent))
            module = importlib.import_module(f"{self._plugin_dir.name}.{name}")
            sys.path.pop(0)

            plugin_info = {
                "name": name,
                "module": module,
                "hooks": [],
                "priority": PluginPriority.NORMAL,
                "loaded": True,
                "error": None,
            }

            # Extract plugin metadata
            if hasattr(module, "__plugin_name__"):
                plugin_info["name"] = module.__plugin_name__
            if hasattr(module, "__plugin_priority__"):
                plugin_info["priority"] = getattr(module, "__plugin_priority__")
            if hasattr(module, "__plugin_version__"):
                plugin_info["version"] = module.__plugin_version__
            if hasattr(module, "__plugin_description__"):
                plugin_info["description"] = module.__plugin_description__

            # Register hooks defined in plugin
            if hasattr(module, "register_hooks"):
                hook_registrations = module.register_hooks()
                for hook_name, handler in hook_registrations:
                    self.register_hook(hook_name, name, handler)
                    plugin_info["hooks"].append(hook_name)

            self._plugins[name] = plugin_info
            return True

        except Exception as e:
            self._plugins[name] = {
                "name": name,
                "module": None,
                "hooks": [],
                "priority": PluginPriority.NORMAL,
                "loaded": False,
                "error": f"{type(e).__name__}: {e}",
            }
            return False

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        if name not in self._plugins:
            return False
        del self._plugins[name]
        # Remove hook registrations for this plugin
        for hook_name in list(self._hooks.keys()):
            self._hooks[hook_name] = [
                h for h in self._hooks[hook_name] if h.get("plugin") != name
            ]
        return True

    def register_hook(self, hook_name: str, plugin_name: str, handler: Callable) -> None:
        """Register a hook handler from a plugin."""
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append({
            "plugin": plugin_name,
            "handler": handler,
        })

    def trigger_hook(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """Trigger all handlers for a hook."""
        results = []
        handlers = self._hooks.get(hook_name, [])
        for registration in handlers:
            try:
                result = registration["handler"](*args, **kwargs)
                results.append({
                    "plugin": registration["plugin"],
                    "success": True,
                    "result": result,
                })
            except Exception as e:
                results.append({
                    "plugin": registration["plugin"],
                    "success": False,
                    "error": f"{type(e).__name__}: {e}",
                })
        return results

    def get_plugin(self, name: str) -> Optional[Dict[str, Any]]:
        return self._plugins.get(name)

    def list_plugins(self, loaded_only: bool = False) -> List[Dict[str, Any]]:
        plugins = []
        for name, info in self._plugins.items():
            if loaded_only and not info.get("loaded", False):
                continue
            plugins.append({
                "name": name,
                "loaded": info.get("loaded", False),
                "hooks": info.get("hooks", []),
                "priority": info.get("priority", PluginPriority.NORMAL).value,
                "version": info.get("version", "unknown"),
                "description": info.get("description", ""),
                "error": info.get("error"),
            })
        return sorted(plugins, key=lambda p: (-p["priority"], p["name"]))

    def list_hooks(self) -> Dict[str, List[str]]:
        """List all registered hooks and their handlers."""
        return {
            hook: [h["plugin"] for h in handlers]
            for hook, handlers in self._hooks.items()
        }

    def get_stats(self) -> Dict[str, Any]:
        plugins = self.list_plugins()
        loaded = [p for p in plugins if p["loaded"]]
        return {
            "total_plugins": len(plugins),
            "loaded": len(loaded),
            "failed": len(plugins) - len(loaded),
            "total_hooks": len(self._hooks),
        }
