"""Friday AI Runtime Harness — Integrations.

Dedicated integration modules for connecting with Friday's existing
infrastructure: Brain, Executive, and MCP server.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Optional


class BrainIntegration:
    """Integration with Friday Brain — the agent's knowledge core."""

    def __init__(self):
        self._brain = None
        self._connected = False
        self._fallback_mode = True

    def connect(self, **kwargs) -> bool:
        """Attempt to connect to Brain module."""
        try:
            module = importlib.import_module("brain")
            self._brain = module.Brain(**kwargs)
            self._connected = True
            self._fallback_mode = False
            return True
        except (ImportError, Exception):
            self._connected = False
            self._fallback_mode = True
            return False

    @property
    def available(self) -> bool:
        return self._connected

    def query(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Query the brain for information."""
        if not self._connected:
            return {"success": False, "error": "Brain not connected", "fallback": True}
        try:
            result = self._brain.process(prompt, **kwargs)
            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def store_memory(self, key: str, value: Any, **kwargs) -> bool:
        """Store a memory in the brain."""
        if not self._connected:
            return False
        try:
            self._brain.store(key, value, **kwargs)
            return True
        except Exception:
            return False

    def retrieve_memory(self, key: str) -> Optional[Any]:
        """Retrieve a memory from the brain."""
        if not self._connected:
            return None
        try:
            return self._brain.retrieve(key)
        except Exception:
            return None


class ExecutiveIntegration:
    """Integration with Friday Executive — task and workflow orchestration."""

    def __init__(self):
        self._executive = None
        self._connected = False

    def connect(self, **kwargs) -> bool:
        """Attempt to connect to Executive module."""
        try:
            module = importlib.import_module("executive")
            self._executive = module.Executive(**kwargs)
            self._connected = True
            return True
        except (ImportError, Exception):
            self._connected = False
            return False

    @property
    def available(self) -> bool:
        return self._connected

    def create_task(self, task_def: Dict[str, Any]) -> Dict[str, Any]:
        """Create a task via the Executive."""
        if not self._connected:
            return {"success": False, "error": "Executive not connected"}
        try:
            result = self._executive.create_task(task_def)
            return {"success": True, "task_id": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self, task_id: str) -> Dict[str, Any]:
        """Get task status."""
        if not self._connected:
            return {"success": False, "error": "Executive not connected"}
        try:
            return {"success": True, "status": self._executive.get_status(task_id)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if not self._connected:
            return False
        try:
            self._executive.cancel(task_id)
            return True
        except Exception:
            return False


class MCPIntegration:
    """Integration with MCP (Model Context Protocol) server."""

    def __init__(self):
        self._server = None
        self._connected = False
        self._tools: List[Dict[str, Any]] = []

    def connect(self, server_path: Optional[str] = None, **kwargs) -> bool:
        """Attempt to connect to MCP server."""
        try:
            module = importlib.import_module("mcp_server")
            self._server = module.MCPServer(server_path, **kwargs)
            self._connected = True
            self._tools = self._server.list_tools() if hasattr(self._server, "list_tools") else []
            return True
        except (ImportError, Exception):
            self._connected = False
            return False

    @property
    def available(self) -> bool:
        return self._connected

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available MCP tools."""
        if not self._connected:
            return []
        return self._tools

    def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an MCP tool."""
        if not self._connected:
            return {"success": False, "error": "MCP not connected"}
        try:
            result = self._server.execute(tool_name, params)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def register_tool(self, name: str, handler: Callable, **kwargs) -> bool:
        """Register a tool with the MCP server."""
        if not self._connected:
            return False
        try:
            self._server.register_tool(name, handler, **kwargs)
            return True
        except Exception:
            return False


class IntegrationManager:
    """Manages all external integrations."""

    def __init__(self):
        self.brain = BrainIntegration()
        self.executive = ExecutiveIntegration()
        self.mcp = MCPIntegration()
        self._custom: Dict[str, Any] = {}

    def connect_all(self, **kwargs) -> Dict[str, bool]:
        """Attempt to connect all integrations."""
        return {
            "brain": self.brain.connect(**kwargs.get("brain", {})),
            "executive": self.executive.connect(**kwargs.get("executive", {})),
            "mcp": self.mcp.connect(**kwargs.get("mcp", {})),
        }

    def register_custom(self, name: str, integration: Any) -> None:
        """Register a custom integration."""
        self._custom[name] = integration

    def get_status(self) -> Dict[str, bool]:
        """Get connection status of all integrations."""
        return {
            "brain": self.brain.available,
            "executive": self.executive.available,
            "mcp": self.mcp.available,
            **{name: hasattr(ig, "available") and ig.available for name, ig in self._custom.items()},
        }

    def disconnect_all(self) -> None:
        """Disconnect all integrations."""
        self.brain._connected = False
        self.executive._connected = False
        self.mcp._connected = False
