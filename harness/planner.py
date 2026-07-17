"""Friday AI Runtime Harness — DAG-based Intelligent Task Planner."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .models import (
    ExecutionMode,
    Plan,
    PlanStatus,
    Step,
    StepType,
    TaskStatus,
    ToolCall,
    ToolDef,
    ToolStatus,
)


class PlanningStrategy(enum.Enum):
    TOP_DOWN = "top_down"
    BOTTOM_UP = "bottom_up"
    DYNAMIC = "dynamic"


class Planner:
    """Intelligent task planner that decomposes goals into DAG-based plans."""

    def __init__(self, strategy: PlanningStrategy = PlanningStrategy.DYNAMIC):
        self._strategy = strategy
        self._plans: Dict[str, Plan] = {}
        self._custom_decomposers: Dict[str, Callable] = {}

    def register_decomposer(self, domain: str, fn: Callable) -> None:
        """Register a custom decomposition function for a domain."""
        self._custom_decomposers[domain] = fn

    def create_plan(
        self,
        goal: str,
        context: Optional[str] = None,
        mode: ExecutionMode = ExecutionMode.STANDARD,
        available_tools: Optional[List[ToolDef]] = None,
        max_steps: int = 25,
    ) -> Plan:
        """Decompose a goal into a DAG-based execution plan."""
        if self._strategy == PlanningStrategy.DYNAMIC:
            strategy = self._select_strategy(goal, mode)
        else:
            strategy = self._strategy

        steps: List[Step] = []
        if strategy == PlanningStrategy.TOP_DOWN:
            steps = self._top_down_decompose(goal, mode, available_tools)
        else:
            steps = self._bottom_up_decompose(goal, mode, available_tools)

        # Trim if over limit
        if len(steps) > max_steps:
            steps = self._consolidate_steps(steps, max_steps)

        # Resolve dependency graph
        self._resolve_dag(steps)

        plan = Plan(
            id=uuid.uuid4().hex[:12],
            title=self._extract_title(goal),
            goal=goal,
            steps=steps,
            status=PlanStatus.DRAFT,
            mode=mode,
            context_id=context,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self._plans[plan.id] = plan
        return plan

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Retrieve a plan by ID."""
        return self._plans.get(plan_id)

    def update_step_status(
        self, plan_id: str, step_id: str, status: TaskStatus, result: Any = None, error: Optional[str] = None
    ) -> bool:
        """Update the status of a step within a plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        for step in plan.steps:
            if step.id == step_id:
                step.status = status
                step.result = result
                step.error = error
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    plan.updated_at = datetime.utcnow()
                if status == TaskStatus.FAILED and plan.status == PlanStatus.ACTIVE:
                    plan.status = PlanStatus.FAILED
                    plan.error = error
                return True
        return False

    def get_ready_steps(self, plan_id: str) -> List[Step]:
        """Get all steps whose dependencies are satisfied."""
        plan = self._plans.get(plan_id)
        if not plan or plan.status != PlanStatus.ACTIVE:
            return []

        completed = {s.id for s in plan.steps if s.status == TaskStatus.COMPLETED}
        ready = []
        for step in plan.steps:
            if step.status == TaskStatus.PENDING:
                if all(dep in completed for dep in step.depends_on):
                    ready.append(step)
        return ready

    def evaluate_plan(self, plan_id: str) -> Dict[str, Any]:
        """Evaluate plan health and progress."""
        plan = self._plans.get(plan_id)
        if not plan:
            return {"error": "plan not found"}

        total = len(plan.steps)
        completed = sum(1 for s in plan.steps if s.status == TaskStatus.COMPLETED)
        failed = sum(1 for s in plan.steps if s.status in (TaskStatus.FAILED, TaskStatus.BLOCKED))
        running = sum(1 for s in plan.steps if s.status == TaskStatus.RUNNING)

        return {
            "plan_id": plan_id,
            "status": plan.status.value,
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": total - completed - failed - running,
            "progress_pct": round((completed / total) * 100, 1) if total > 0 else 0,
            "total_tokens": plan.total_tokens,
            "total_cost": plan.total_cost,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _select_strategy(self, goal: str, mode: ExecutionMode) -> PlanningStrategy:
        """Dynamically select the best planning strategy."""
        keywords_top_down = ["architect", "design", "framework", "migration", "refactor"]
        keywords_bottom_up = ["debug", "fix", "investigate", "optimize", "profile"]

        goal_lower = goal.lower()
        if any(k in goal_lower for k in keywords_top_down):
            return PlanningStrategy.TOP_DOWN
        if any(k in goal_lower for k in keywords_bottom_up):
            return PlanningStrategy.BOTTOM_UP
        if mode in (ExecutionMode.AUTONOMOUS, ExecutionMode.CODING):
            return PlanningStrategy.TOP_DOWN
        return PlanningStrategy.TOP_DOWN

    def _top_down_decompose(
        self, goal: str, mode: ExecutionMode, tools: Optional[List[ToolDef]] = None
    ) -> List[Step]:
        """Decompose from high-level goal to fine-grained steps."""
        steps: List[Step] = []
        domain_hint = self._detect_domain(goal)

        # Check for custom decomposer
        if domain_hint in self._custom_decomposers:
            return self._custom_decomposers[domain_hint](goal, mode, tools)

        # Default decomposition
        steps.append(Step(
            description=f"Analyze request: {self._truncate(goal, 80)}",
            step_type=StepType.THINK,
        ))
        steps.append(Step(
            description="Gather necessary context and information",
            step_type=StepType.REASON,
            depends_on=[steps[0].id],
        ))
        steps.append(Step(
            description="Execute primary actions",
            step_type=StepType.TOOL if mode != ExecutionMode.CODING else StepType.CODE,
            depends_on=[steps[1].id],
        ))
        steps.append(Step(
            description="Verify results and validate output",
            step_type=StepType.VERIFY,
            depends_on=[steps[2].id],
        ))

        if mode == ExecutionMode.RESEARCH:
            steps.insert(2, Step(
                description="Conduct multi-source research",
                step_type=StepType.RESEARCH,
                depends_on=[steps[1].id],
            ))
        return steps

    def _bottom_up_decompose(
        self, goal: str, mode: ExecutionMode, tools: Optional[List[ToolDef]] = None
    ) -> List[Step]:
        """Decompose from concrete actions upward to verification."""
        steps: List[Step] = [
            Step(description=f"Investigate: {self._truncate(goal, 80)}", step_type=StepType.REASON),
            Step(description="Collect diagnostic data", step_type=StepType.TOOL, depends_on=[0]),
            Step(description="Analyze findings", step_type=StepType.REASON, depends_on=[1]),
            Step(description="Implement fix or optimization", step_type=StepType.CODE, depends_on=[2]),
            Step(description="Verify resolution", step_type=StepType.VERIFY, depends_on=[3]),
        ]

        # Map step IDs
        step_ids = [s.id for s in steps]
        for i, step in enumerate(steps):
            if i > 0:
                step.depends_on = [step_ids[i - 1]]

        return steps

    def _resolve_dag(self, steps: List[Step]) -> None:
        """Validate and resolve the dependency graph (detect cycles)."""
        adj: Dict[str, Set[str]] = {s.id: set(s.depends_on) for s in steps}

        # Simple cycle detection via DFS
        visited: Set[str] = set()
        stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            stack.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in stack:
                    return True
            stack.discard(node)
            return False

        for s in steps:
            if s.id not in visited:
                if dfs(s.id):
                    # Break cycle by removing last dependency
                    for step in reversed(steps):
                        if step.depends_on:
                            step.depends_on.pop()
                            break

    def _consolidate_steps(self, steps: List[Step], max_steps: int) -> List[Step]:
        """Consolidate steps when plan exceeds max_steps."""
        if len(steps) <= max_steps:
            return steps
        # Merge consecutive think/reason steps
        merged: List[Step] = []
        for step in steps:
            if merged and merged[-1].step_type in (StepType.THINK, StepType.REASON) and \
               step.step_type in (StepType.THINK, StepType.REASON):
                merged[-1].description += f"; {step.description}"
            else:
                merged.append(step)
        return merged[:max_steps]

    @staticmethod
    def _detect_domain(goal: str) -> str:
        goal_lower = goal.lower()
        if any(w in goal_lower for w in ["code", "function", "class", "bug", "fix", "refactor"]):
            return "coding"
        if any(w in goal_lower for w in ["search", "research", "find", "lookup", "investigate"]):
            return "research"
        if any(w in goal_lower for w in ["write", "draft", "create", "generate"]):
            return "creation"
        return "general"

    @staticmethod
    def _extract_title(goal: str) -> str:
        return goal[:60] + "..." if len(goal) > 60 else goal

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text[:max_len] + "..." if len(text) > max_len else text
