"""Friday AI Runtime Harness — Tool Orchestration.

Manages tool registration, validation, dependency injection, chaining,
and parallel execution. Integrates with existing MCP and system tools.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import ToolCall, ToolDef, ToolStatus


class ToolOrchestrator:
    """Orchestrates tool execution including registration, validation, and chaining."""

    def __init__(self, max_concurrent: int = 3):
        self._tools: Dict[str, ToolDef] = {}
        self._handlers: Dict[str, Callable] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._execution_history: List[Dict[str, Any]] = []

    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        category: str = "general",
        timeout: int = 30,
        dangerous: bool = False,
        parameters: Optional[Dict[str, Any]] = None,
        required_params: Optional[List[str]] = None,
    ) -> ToolDef:
        """Register a tool with metadata and handler."""
        tool_def = ToolDef(
            name=name,
            description=description,
            parameters=parameters or {},
            required_params=required_params or [],
            category=category,
            timeout=timeout,
            dangerous=dangerous,
        )
        self._tools[name] = tool_def
        self._handlers[name] = handler
        return tool_def

    def unregister_tool(self, name: str) -> bool:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
        return self._handlers.pop(name, None) is not None

    def get_tool(self, name: str) -> Optional[ToolDef]:
        """Get tool definition by name."""
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[ToolDef]:
        """List registered tools, optionally filtered by category."""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def validate_call(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate a tool call against its definition."""
        tool = self._tools.get(tool_name)
        if not tool:
            return False, f"Unknown tool: {tool_name}"
        if not tool.enabled:
            return False, f"Tool '{tool_name}' is disabled"

        for param in tool.required_params:
            if param not in args:
                return False, f"Missing required parameter '{param}' for tool '{tool_name}'"

        return True, None

    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        timeout: Optional[int] = None,
    ) -> ToolCall:
        """Execute a tool synchronously with validation and timeout."""
        call = ToolCall(
            id=uuid.uuid4().hex[:12],
            tool_name=tool_name,
            args=args,
            status=ToolStatus.RUNNING,
            started_at=__import__("datetime").datetime.utcnow(),
        )

        valid, error = self.validate_call(tool_name, args)
        if not valid:
            call.status = ToolStatus.ERROR
            call.error = error
            call.finished_at = __import__("datetime").datetime.utcnow()
            self._record(call)
            return call

        handler = self._handlers.get(tool_name)
        if not handler:
            call.status = ToolStatus.ERROR
            call.error = f"No handler registered for '{tool_name}'"
            call.finished_at = __import__("datetime").datetime.utcnow()
            self._record(call)
            return call

        effective_timeout = timeout or self._tools[tool_name].timeout or 30
        start = time.time()

        try:
            future = self._executor.submit(handler, **args)
            result = future.result(timeout=effective_timeout)
            call.status = ToolStatus.SUCCESS
            call.result = result
        except __import__("concurrent").futures.TimeoutError:
            call.status = ToolStatus.TIMEOUT
            call.error = f"Tool '{tool_name}' timed out after {effective_timeout}s"
        except Exception as e:
            call.status = ToolStatus.ERROR
            call.error = f"{type(e).__name__}: {e}"
        finally:
            call.finished_at = __import__("datetime").datetime.utcnow()
            call.duration_ms = round((time.time() - start) * 1000, 2)
            self._record(call)

        return call

    def execute_chain(
        self,
        chain: List[Tuple[str, Dict[str, Any]]],
        stop_on_error: bool = True,
    ) -> List[ToolCall]:
        """Execute a chain of tools sequentially, passing results as context."""
        results: List[ToolCall] = []
        for tool_name, args in chain:
            call = self.execute(tool_name, args)
            results.append(call)
            if call.status in (ToolStatus.ERROR, ToolStatus.TIMEOUT) and stop_on_error:
                break
        return results

    def execute_parallel(
        self, calls: List[Tuple[str, Dict[str, Any]]]
    ) -> List[ToolCall]:
        """Execute multiple tool calls in parallel using asyncio."""
        loop = asyncio.new_event_loop()
        try:
            async def run_all():
                tasks = []
                for tool_name, args in calls:
                    tasks.append(
                        asyncio.get_event_loop().run_in_executor(
                            self._executor,
                            self._execute_sync,
                            tool_name,
                            args,
                        )
                    )
                return await asyncio.gather(*tasks)

            results = loop.run_until_complete(run_all())
        finally:
            loop.close()
        return results

    def get_history(
        self,
        tool_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get execution history, optionally filtered by tool."""
        history = self._execution_history
        if tool_name:
            history = [h for h in history if h["tool_name"] == tool_name]
        return history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate execution statistics."""
        total = len(self._execution_history)
        successes = sum(1 for h in self._execution_history if h["status"] == ToolStatus.SUCCESS.value)
        errors = sum(1 for h in self._execution_history if h["status"] == ToolStatus.ERROR.value)
        timeouts = sum(1 for h in self._execution_history if h["status"] == ToolStatus.TIMEOUT.value)
        avg_duration = (
            sum(h["duration_ms"] for h in self._execution_history) / total
            if total > 0 else 0
        )

        return {
            "total_calls": total,
            "successes": successes,
            "errors": errors,
            "timeouts": timeouts,
            "success_rate": round(successes / total * 100, 1) if total > 0 else 0,
            "avg_duration_ms": round(avg_duration, 2),
            "tools_registered": len(self._tools),
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _execute_sync(self, tool_name: str, args: Dict[str, Any]) -> ToolCall:
        """Synchronous execution wrapper."""
        return self.execute(tool_name, args)

    def _record(self, call: ToolCall) -> None:
        self._execution_history.append({
            "id": call.id,
            "tool_name": call.tool_name,
            "status": call.status.value,
            "duration_ms": call.duration_ms,
            "error": call.error,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })
