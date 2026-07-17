"""Friday AI Runtime Harness — Self-Checking Module.

Validates LLM outputs for correctness, consistency, safety, and completeness
before they are returned to the user.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .models import Severity, ValidationResult


class SelfChecker:
    """Validates and verifies LLM outputs before delivery."""

    def __init__(self):
        self._checks: Dict[str, dict] = {}
        self._history: List[Dict[str, Any]] = []
        self._register_default_checks()

    def _register_default_checks(self) -> None:
        """Register built-in validation checks."""
        self.register_check("factual_consistency", {
            "description": "Check for internal contradictions",
            "enabled": True,
            "severity": Severity.WARN,
        })
        self.register_check("safety", {
            "description": "Check for harmful or unsafe content",
            "enabled": True,
            "severity": Severity.ERROR,
        })
        self.register_check("completeness", {
            "description": "Check if the response is complete",
            "enabled": True,
            "severity": Severity.WARN,
        })
        self.register_check("code_quality", {
            "description": "Check code snippets for obvious issues",
            "enabled": True,
            "severity": Severity.WARN,
        })
        self.register_check("tool_call_validity", {
            "description": "Validate tool call formatting",
            "enabled": True,
            "severity": Severity.ERROR,
        })

    def register_check(self, name: str, config: Dict[str, Any]) -> None:
        """Register a new validation check."""
        self._checks[name] = config

    def enable_check(self, name: str) -> bool:
        """Enable a specific check."""
        if name in self._checks:
            self._checks[name]["enabled"] = True
            return True
        return False

    def disable_check(self, name: str) -> bool:
        """Disable a specific check."""
        if name in self._checks:
            self._checks[name]["enabled"] = False
            return True
        return False

    def validate(self, text: str, context: Optional[str] = None) -> ValidationResult:
        """Run all enabled validation checks on output text."""
        issues: List[str] = []
        suggestions: List[str] = []
        total_score = 1.0
        deductions = 0.0

        for name, config in self._checks.items():
            if not config.get("enabled", True):
                continue

            result = self._run_check(name, text, context)
            if not result["passed"]:
                issues.extend(result.get("issues", []))
                suggestions.extend(result.get("suggestions", []))
                deductions += result.get("deduction", 0.1)

        score = max(0.0, total_score - deductions)
        passed = score >= 0.6 and len(issues) == 0

        result = ValidationResult(
            passed=passed,
            score=round(score, 2),
            issues=issues[:10],
            suggestions=suggestions[:5],
        )

        self._history.append({
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            "passed": passed,
            "score": score,
            "issues_count": len(issues),
            "text_length": len(text),
        })

        return result

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._history)
        passed = sum(1 for h in self._history if h["passed"])
        return {
            "total_validations": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 100,
        }

    # ── Individual Checks ────────────────────────────────────────────────────

    def _run_check(self, name: str, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Run a single validation check by name."""
        checker = getattr(self, f"_check_{name}", None)
        if checker:
            return checker(text, context)
        return {"passed": True}

    def _check_factual_consistency(self, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Check for contradictions within the response."""
        issues = []
        # Simple self-contradiction: conflicting statements
        negation_patterns = [
            (r"(is|are|was|were)\s+not", r"(is|are|was|were)\s+indeed"),
            (r"cannot\s+be", r"can\s+be"),
        ]
        for neg, pos in negation_patterns:
            if re.search(neg, text, re.I) and re.search(pos, text, re.I):
                issues.append("Possible self-contradiction detected")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "deduction": 0.15 if issues else 0,
        }

    def _check_safety(self, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Check for harmful content."""
        harmful_patterns = [
            r"(?i)(how\s+to\s+(build|make|create)\s+(a\s+)?(bomb|weapon|explosive))",
            r"(?i)(instructions\s+for\s+(illegal|unlawful))",
        ]
        issues = []
        for pattern in harmful_patterns:
            if re.search(pattern, text):
                issues.append("Potentially harmful content detected")
                break

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "deduction": 0.5 if issues else 0,
        }

    def _check_completeness(self, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Check if the response seems complete."""
        issues = []
        suggestions = []

        # Truncation indicators
        if text.rstrip().endswith(("...", "to be continued", "incomplete")):
            issues.append("Response appears truncated")
            suggestions.append("Consider completing the response")

        length = len(text.strip())
        if length < 10:
            issues.append("Response is very short")
            suggestions.append("Consider providing a more detailed response")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "suggestions": suggestions,
            "deduction": 0.1 if issues else 0,
        }

    def _check_code_quality(self, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Check code blocks for obvious issues."""
        issues = []
        code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        for block in code_blocks:
            lines = block.strip().split("\n")
            for i, line in enumerate(lines):
                if "TODO" in line or "FIXME" in line:
                    issues.append(f"Incomplete code (TODO/FIXME) at line {i + 1}")
                    break

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "suggestions": ["Remove TODO/FIXME markers before finalizing"] if issues else [],
            "deduction": 0.1 if issues else 0,
        }

    def _check_tool_call_validity(self, text: str, context: Optional[str]) -> Dict[str, Any]:
        """Validate tool call formatting."""
        issues = []
        tool_calls = re.findall(r"\[TOOL:\s*(\w+)\((.*?)\)\]", text)

        for name, args_str in tool_calls:
            if not name:
                issues.append("Empty tool name in [TOOL:] call")
            if args_str.strip() and not args_str.strip().startswith(("{", "[")):
                try:
                    eval(args_str.strip())
                except Exception:
                    issues.append(f"Invalid arguments in tool call '{name}': {args_str[:50]}")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "deduction": 0.2 if issues else 0,
        }
