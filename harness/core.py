"""Friday AI Runtime Harness — Main Orchestrator.

The RuntimeHarness wraps all subsystems into a single execution pipeline:
  plan → reason → orchestrate → validate → respond

Integrates with existing Friday Brain, Executive, and MCP infrastructure.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import HarnessConfig, get_config
from .context import ContextManager
from .models import (
    ContextFrame,
    ExecutionMode,
    HarnessResult,
    MemoryEntry,
    Plan,
    PlanStatus,
    ResearchFinding,
    Severity,
    Step,
    StepType,
    TaskStatus,
    ToolCall,
    ToolDef,
    ToolStatus,
    ValidationResult,
    Observation,
)
from .orchestrator import ToolOrchestrator
from .planner import Planner, PlanningStrategy
from .reasoning import ReasoningEngine


class RuntimeHarness:
    """Central orchestrator for the AI runtime execution pipeline.

    Coordinates planning, reasoning, tool execution, context management,
    validation, and observability into a single call/response flow.
    """

    def __init__(self, config: Optional[HarnessConfig] = None):
        self.config = config or get_config()
        self.planner = Planner()
        self.reasoning = ReasoningEngine()
        self.orchestrator = ToolOrchestrator(
            max_concurrent=self.config.max_concurrent_tools
        )
        self.context = ContextManager(
            max_tokens=self.config.max_context_tokens,
            compression_threshold=self.config.context_compression_threshold,
        )
        self._observers: List[Callable] = []
        self._trace_id: Optional[str] = None
        self._execution_history: List[Dict[str, Any]] = []

        if self.config.use_existing_brain:
            self._try_integrate_brain()
        if self.config.use_existing_mcp:
            self._try_integrate_mcp()

    # ── Public API ───────────────────────────────────────────────────────────

    def execute(
        self,
        prompt: str,
        mode: ExecutionMode = ExecutionMode.STANDARD,
        context_id: Optional[str] = None,
        tools: Optional[List[ToolDef]] = None,
        max_steps: Optional[int] = None,
    ) -> HarnessResult:
        """Execute a prompt through the full harness pipeline."""
        start_time = time.time()
        self._trace_id = uuid.uuid4().hex[:16]

        self._emit(Severity.INFO, "harness.execute.start",
                   f"Executing prompt (mode={mode.value})", {
                       "prompt_len": len(prompt),
                       "mode": mode.value,
                   })

        result = HarnessResult(mode=mode)

        try:
            # 1. Plan
            plan = self.planner.create_plan(
                goal=prompt,
                context=context_id,
                mode=mode,
                available_tools=tools,
                max_steps=max_steps or self.config.max_steps_per_plan,
            )
            plan.status = PlanStatus.ACTIVE
            result.plan = plan

            # 2. Execute steps in DAG order
            context_frame = self.context.get_frame(context_id)
            if not context_frame:
                context_frame = self.context.create_frame(
                    conversation_id=context_id
                )

            total_tokens = 0
            total_cost = 0.0
            steps_completed = 0

            while True:
                ready_steps = self.planner.get_ready_steps(plan.id)
                if not ready_steps:
                    break

                for step in ready_steps:
                    step.status = TaskStatus.RUNNING
                    self._execute_step(step, context_frame, mode)
                    self.planner.update_step_status(
                        plan.id, step.id, step.status, step.result, step.error
                    )
                    total_tokens += step.tokens_used
                    steps_completed += 1

            # Post-execution
            plan.status = PlanStatus.COMPLETED
            plan.completed_at = datetime.utcnow()
            plan.total_tokens = total_tokens
            plan.total_cost = total_cost

            # 3. Build response
            result.steps_completed = steps_completed
            result.steps_total = len(plan.steps)
            result.total_tokens = total_tokens
            result.total_cost = total_cost
            result.response = self._build_response(plan)

            # 4. Validate
            if self.config.enable_tracing:
                from .validation import SelfValidator
                validator = SelfValidator()
                result.validation = validator.validate_plan(plan)

            result.success = True

        except Exception as e:
            result.success = False
            result.error = f"{type(e).__name__}: {e}"
            if result.plan:
                result.plan.status = PlanStatus.FAILED
                result.plan.error = str(e)
            self._emit(Severity.ERROR, "harness.execute.error", str(e))

        finally:
            result.duration_ms = round((time.time() - start_time) * 1000, 2)
            result.metadata = {
                "trace_id": self._trace_id,
                "mode": mode.value,
                "duration_ms": result.duration_ms,
            }
            self._record_execution(result)
            self._emit(Severity.INFO, "harness.execute.complete",
                       f"Completed in {result.duration_ms:.0f}ms",
                       {"success": result.success, "steps": result.steps_completed})

        return result

    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        category: str = "general",
        timeout: int = 30,
        dangerous: bool = False,
    ) -> ToolDef:
        """Register a tool with the harness orchestrator."""
        return self.orchestrator.register_tool(
            name, description, handler, category, timeout, dangerous
        )

    def register_observer(self, callback: Callable) -> None:
        """Register an observer callback for harness events."""
        self._observers.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate harness statistics."""
        return {
            "executions": len(self._execution_history),
            "context": self.context.get_stats(),
            "orchestrator": self.orchestrator.get_stats(),
            "config": {
                k: v for k, v in vars(self.config).items()
                if not k.startswith("_")
            },
        }

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        return self._execution_history[-limit:]

    # ── Internal Pipeline ────────────────────────────────────────────────────

    def _execute_step(
        self,
        step: Step,
        context_frame: ContextFrame,
        mode: ExecutionMode,
    ) -> None:
        """Execute a single plan step based on its type."""
        step.tool_calls = []

        if step.step_type in (StepType.THINK, StepType.REASON):
            reasoning = self.reasoning.reason(
                step.description, strategy="chain_of_thought"
            )
            step.reasoning = str(reasoning.get("conclusion", ""))
            step.tokens_used = len(step.description) // 4
            step.status = TaskStatus.COMPLETED

        elif step.step_type == StepType.TOOL:
            call = self._route_tool_call(step)
            step.tool_calls.append(call)

        elif step.step_type == StepType.CODE:
            self._emit(Severity.DEBUG, "step.code", step.description)
            step.status = TaskStatus.COMPLETED

        elif step.step_type == StepType.RESEARCH:
            self._emit(Severity.DEBUG, "step.research", step.description)
            step.status = TaskStatus.COMPLETED

        elif step.step_type == StepType.MEMORY:
            step.status = TaskStatus.COMPLETED

        elif step.step_type == StepType.VERIFY:
            step.status = TaskStatus.COMPLETED

        elif step.step_type == StepType.RESPOND:
            step.status = TaskStatus.COMPLETED

        else:
            step.status = TaskStatus.COMPLETED

    def _route_tool_call(self, step: Step) -> ToolCall:
        """Route a step to the appropriate tool via the orchestrator."""
        name_parts = step.description.lower().split()
        tool_name = next(
            (t for t in self.orchestrator.list_tools()
             if any(p in t.name.lower() for p in name_parts)),
            None
        )
        if tool_name:
            return self.orchestrator.execute(tool_name.name, {})
        return ToolCall(
            tool_name="none",
            status=ToolStatus.SKIPPED,
            error="No matching tool found",
            duration_ms=0.0,
        )

    def _build_response(self, plan: Plan) -> str:
        """Build a response string from the completed plan."""
        completed = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        if not completed:
            return "No actions taken."

        lines = []
        for step in completed:
            lines.append(f"• {step.description}")
            if step.reasoning:
                lines.append(f"  → {step.reasoning[:120]}")

        if plan.total_tokens > 0:
            lines.append(f"\n(Used ~{plan.total_tokens} tokens across {len(completed)} steps)")

        return "\n".join(lines)

    def _record_execution(self, result: HarnessResult) -> None:
        self._execution_history.append({
            "trace_id": self._trace_id,
            "success": result.success,
            "mode": result.mode.value,
            "steps": result.steps_completed,
            "tokens": result.total_tokens,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _emit(
        self,
        level: Severity,
        event: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an observation to all observers."""
        obs = Observation(
            event=event,
            level=level,
            component="harness",
            message=message,
            data=data or {},
            trace_id=self._trace_id,
        )
        for cb in self._observers:
            try:
                cb(obs)
            except Exception:
                pass

    # ── Integration ──────────────────────────────────────────────────────────

    def _try_integrate_brain(self) -> None:
        """Attempt integration with existing Friday Brain."""
        try:
            import sys
            sys.path.insert(0, ".")
            from brain import Brain
            self._brain = Brain()
            self.register_tool("brain_query", "Query the Friday Brain",
                                self._brain.query, category="brain")
        except ImportError:
            self._brain = None

    def _try_integrate_mcp(self) -> None:
        """Attempt integration with existing MCP server."""
        try:
            from mcp import MCPServer
            self._mcp = MCPServer()
        except ImportError:
            self._mcp = None
