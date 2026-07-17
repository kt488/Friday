"""Friday AI Runtime Harness — Error Recovery & Resilience.

Handles runtime errors gracefully with retry logic, fallback strategies,
state preservation, and graceful degradation.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, Type


class RecoveryHandler:
    """Handles runtime errors with retry, fallback, and graceful degradation."""

    def __init__(self, max_retries: int = 3, retry_delay_base: float = 1.0):
        self._max_retries = max_retries
        self._retry_delay_base = retry_delay_base
        self._recovery_history: List[Dict[str, Any]] = []
        self._fallback_handlers: Dict[str, Callable] = {}
        self._error_patterns: Dict[str, Dict[str, Any]] = {}

    def register_fallback(self, error_type: str, handler: Callable) -> None:
        """Register a fallback handler for a specific error type."""
        self._fallback_handlers[error_type] = handler

    def register_error_pattern(
        self, pattern_name: str, retry_count: int = 3, fallback_to: Optional[str] = None
    ) -> None:
        """Register an error pattern with recovery config."""
        self._error_patterns[pattern_name] = {
            "retry_count": retry_count,
            "fallback_to": fallback_to,
        }

    def execute_with_retry(
        self,
        fn: Callable,
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    ) -> Dict[str, Any]:
        """Execute a function with retry logic."""
        kwargs = kwargs or {}
        max_retries = max_retries or self._max_retries
        retryable_exceptions = retryable_exceptions or (Exception,)
        last_error: Optional[str] = None
        start = time.time()

        for attempt in range(max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                duration = round((time.time() - start) * 1000, 2)

                entry = {
                    "function": fn.__name__,
                    "attempts": attempt + 1,
                    "success": True,
                    "duration_ms": duration,
                }
                self._recovery_history.append(entry)

                return {
                    "success": True,
                    "result": result,
                    "attempts": attempt + 1,
                    "duration_ms": duration,
                }
            except retryable_exceptions as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < max_retries:
                    delay = self._retry_delay_base * (2 ** attempt)
                    self._recovery_history.append({
                        "function": fn.__name__,
                        "attempt": attempt + 1,
                        "success": False,
                        "error": last_error,
                        "will_retry": True,
                    })
                    time.sleep(delay)
                else:
                    self._recovery_history.append({
                        "function": fn.__name__,
                        "attempt": attempt + 1,
                        "success": False,
                        "error": last_error,
                        "will_retry": False,
                    })

        duration = round((time.time() - start) * 1000, 2)
        return {
            "success": False,
            "error": last_error or "Unknown error",
            "attempts": max_retries + 1,
            "duration_ms": duration,
        }

    def execute_with_fallback(
        self,
        primary: Callable,
        fallback: Callable,
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute with a primary function, falling back on failure."""
        result = self.execute_with_retry(primary, args, kwargs, max_retries=1)
        if result["success"]:
            return result

        # Try fallback
        try:
            fallback_result = fallback(*args, **(kwargs or {}))
            return {
                "success": True,
                "result": fallback_result,
                "fallback_used": True,
                "primary_error": result.get("error"),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Primary: {result.get('error')}, Fallback: {e}",
                "fallback_used": True,
            }

    def degrade(self, component: str, fallback_level: str = "basic") -> Dict[str, Any]:
        """Gracefully degrade a component when it fails."""
        levels = {"basic": 1, "reduced": 2, "full": 3}
        level = levels.get(fallback_level, 1)

        degradation = {
            "component": component,
            "previous_level": "full",
            "new_level": fallback_level,
            "capabilities_affected": self._get_degraded_capabilities(component),
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }

        self._recovery_history.append({
            "event": "degradation",
            "component": component,
            "fallback_level": fallback_level,
        })

        return degradation

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._recovery_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        total = len([h for h in self._recovery_history if "function" in h])
        successes = sum(1 for h in self._recovery_history if h.get("success"))
        failures = total - successes
        return {
            "total_attempts": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total * 100, 1) if total > 0 else 0,
            "fallbacks_registered": len(self._fallback_handlers),
            "error_patterns": len(self._error_patterns),
        }

    def _get_degraded_capabilities(self, component: str) -> List[str]:
        mapping = {
            "vision": ["image_analysis", "document_ocr"],
            "search": ["web_search", "source_citation"],
            "memory": ["long_term_recall", "cross_session_context"],
            "tools": ["external_tool_execution"],
        }
        return mapping.get(component, [f"{component}_functions"])
