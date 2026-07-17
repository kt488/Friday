"""Friday AI Runtime Harness — Validation & Self-Check."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import Plan, PlanStatus, Step, StepType, TaskStatus, ValidationResult


class SelfValidator:
    """Self-validation and quality checking for plans and outputs."""

    def __init__(self):
        self._checks_run = 0
        self._checks_passed = 0

    def validate_plan(self, plan: Plan) -> ValidationResult:
        """Run all validation checks on a completed plan."""
        issues: List[str] = []
        suggestions: List[str] = []
        score = 1.0

        # Check 1: Step completion
        total = len(plan.steps)
        failed = sum(1 for s in plan.steps if s.status == TaskStatus.FAILED)
        blocked = sum(1 for s in plan.steps if s.status == TaskStatus.BLOCKED)

        if failed > 0:
            score -= 0.2 * failed
            issues.append(f"{failed} step(s) failed")
        if blocked > 0:
            score -= 0.15 * blocked
            issues.append(f"{blocked} step(s) blocked")

        # Check 2: No empty steps
        empty = [s for s in plan.steps if not s.description]
        if empty:
            score -= 0.05 * len(empty)
            suggestions.append(f"{len(empty)} step(s) have empty descriptions")

        # Check 3: Dependency integrity
        all_ids = {s.id for s in plan.steps}
        for step in plan.steps:
            missing = [d for d in step.depends_on if d not in all_ids]
            if missing:
                score -= 0.1
                issues.append(f"Step '{step.id}' references missing dependencies: {missing}")

        # Check 4: Token usage
        if plan.total_tokens > 100_000:
            suggestions.append(f"High token usage ({plan.total_tokens}). Consider optimization.")
        if plan.total_tokens == 0 and plan.status == PlanStatus.COMPLETED:
            suggestions.append("No token usage recorded. Metrics may be incomplete.")

        # Check 5: Execution mode appropriateness
        if plan.mode.value == "standard" and any(s.step_type == StepType.RESEARCH for s in plan.steps):
            suggestions.append("Research step present in 'standard' mode — consider using RESEARCH mode")

        self._checks_run += 5
        self._checks_passed += (5 - len(issues))

        return ValidationResult(
            passed=score >= 0.5,
            score=max(0.0, round(score, 2)),
            issues=issues,
            suggestions=suggestions,
            details=f"Validated {len(plan.steps)} steps — {len(issues)} issue(s), {len(suggestions)} suggestion(s)",
        )

    def validate_response(
        self,
        response: str,
        plan: Plan,
    ) -> ValidationResult:
        """Validate the final response quality."""
        issues: List[str] = []
        score = 1.0

        if not response.strip():
            issues.append("Empty response")
            score -= 0.5
        elif len(response) < 10:
            issues.append("Response too short (< 10 chars)")
            score -= 0.2

        if plan.total_tokens > 0 and plan.total_cost == 0:
            score -= 0.1
            issues.append("Token usage recorded but cost is zero")

        self._checks_run += 1
        if not issues:
            self._checks_passed += 1

        return ValidationResult(
            passed=score >= 0.5,
            score=max(0.0, score),
            issues=issues,
            details=f"Response validation: {len(response)} chars",
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        return {
            "checks_run": self._checks_run,
            "checks_passed": self._checks_passed,
            "pass_rate": round(
                self._checks_passed / self._checks_run * 100, 1
            ) if self._checks_run > 0 else 100.0,
        }
