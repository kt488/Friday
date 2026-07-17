"""Friday AI Runtime Harness — Observability Module.

Tracing, metrics collection, logging, cost tracking, and performance
monitoring for the entire runtime.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import Observation, Severity


class Observer:
    """Central observability: tracing, metrics, logging, cost tracking."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._observations: List[Observation] = []
        self._traces: Dict[str, List[Observation]] = {}
        self._active_traces: Dict[str, Observation] = {}
        self._metrics: Dict[str, List[float]] = defaultdict(list)
        self._costs: List[float] = []
        self._counters: Dict[str, int] = defaultdict(int)

    # ── Logging ──────────────────────────────────────────────────────────────

    def log(
        self,
        event: str,
        message: str,
        level: Severity = Severity.INFO,
        component: str = "system",
        data: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        """Record a log observation."""
        obs = Observation(
            event=event,
            level=level,
            component=component,
            message=message,
            data=data or {},
        )
        if self._enabled:
            self._observations.append(obs)
        return obs

    def debug(self, event: str, message: str, component: str = "system") -> Observation:
        return self.log(event, message, Severity.DEBUG, component)

    def info(self, event: str, message: str, component: str = "system") -> Observation:
        return self.log(event, message, Severity.INFO, component)

    def warn(self, event: str, message: str, component: str = "system") -> Observation:
        return self.log(event, message, Severity.WARN, component)

    def error(self, event: str, message: str, component: str = "system") -> Observation:
        return self.log(event, message, Severity.ERROR, component)

    def critical(self, event: str, message: str, component: str = "system") -> Observation:
        return self.log(event, message, Severity.CRITICAL, component)

    # ── Tracing ──────────────────────────────────────────────────────────────

    def start_trace(self, name: str) -> str:
        """Start a named trace and return its ID."""
        trace_id = uuid.uuid4().hex[:12]
        obs = Observation(
            event=f"trace_start:{name}",
            level=Severity.INFO,
            component="trace",
            message=f"Trace started: {name}",
            trace_id=trace_id,
        )
        self._active_traces[trace_id] = obs
        if self._enabled:
            self._observations.append(obs)
        return trace_id

    def end_trace(self, trace_id: str) -> Optional[Observation]:
        """End a trace and record its duration."""
        start_obs = self._active_traces.pop(trace_id, None)
        if start_obs:
            obs = Observation(
                event=f"trace_end:{start_obs.event.replace('trace_start:', '')}",
                level=Severity.INFO,
                component="trace",
                message=f"Trace completed: {start_obs.event}",
                trace_id=trace_id,
            )
            if self._enabled:
                self._observations.append(obs)
            return obs
        return None

    # ── Metrics ──────────────────────────────────────────────────────────────

    def record_metric(self, name: str, value: float) -> None:
        """Record a metric value."""
        self._metrics[name].append(value)

    def record_duration(self, name: str, duration_ms: float) -> None:
        """Record a duration metric (convenience wrapper)."""
        self.record_metric(f"duration:{name}", duration_ms)

    def increment_counter(self, name: str, count: int = 1) -> None:
        """Increment a named counter."""
        self._counters[name] += count

    def record_token_usage(self, tokens: int, model: str = "default") -> None:
        """Record token usage."""
        self.record_metric(f"tokens:{model}", tokens)
        self.increment_counter("total_tokens", tokens)

    def record_cost(self, cost: float) -> None:
        """Record a cost metric."""
        self._costs.append(cost)
        self.record_metric("cost", cost)

    # ── Query ────────────────────────────────────────────────────────────────

    def get_observations(
        self,
        level: Optional[Severity] = None,
        component: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 100,
    ) -> List[Observation]:
        """Get observations with optional filtering."""
        results = self._observations
        if level:
            results = [o for o in results if o.level == level]
        if component:
            results = [o for o in results if o.component == component]
        if event:
            results = [o for o in results if event in o.event]
        return results[-limit:]

    def get_metrics(self, name: Optional[str] = None) -> Dict[str, Any]:
        if name:
            values = self._metrics.get(name, [])
            return {
                "name": name,
                "count": len(values),
                "sum": round(sum(values), 4) if values else 0,
                "avg": round(sum(values) / len(values), 4) if values else 0,
                "min": round(min(values), 4) if values else 0,
                "max": round(max(values), 4) if values else 0,
            } if values else {"error": f"No metrics for {name}"}

        return {
            name: {
                "count": len(v),
                "avg": round(sum(v) / len(v), 4) if v else 0,
            }
            for name, v in self._metrics.items()
        }

    def get_counters(self) -> Dict[str, int]:
        return dict(self._counters)

    # ── Reporting ────────────────────────────────────────────────────────────

    def get_log_summary(self) -> Dict[str, Any]:
        """Get summary of log levels."""
        counts = defaultdict(int)
        for obs in self._observations:
            counts[obs.level.value] += 1
        return {
            "total_observations": len(self._observations),
            "by_level": dict(counts),
        }

    def get_cost_summary(self) -> Dict[str, Any]:
        total_cost = sum(self._costs)
        total_tokens = self._counters.get("total_tokens", 0)
        return {
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "avg_cost_per_token": round(total_cost / total_tokens, 8) if total_tokens > 0 else 0,
        }

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary."""
        duration_metrics = {k: v for k, v in self._metrics.items() if k.startswith("duration:")}
        return {
            "recorded_metrics": len(self._metrics),
            "traces_active": len(self._active_traces),
            "avg_durations": {
                k.replace("duration:", ""): round(sum(v) / len(v), 2)
                for k, v in duration_metrics.items()
            } if duration_metrics else {},
        }

    def clear(self) -> None:
        """Clear all observations and metrics."""
        self._observations.clear()
        self._traces.clear()
        self._active_traces.clear()
        self._metrics.clear()
        self._costs.clear()
        self._counters.clear()
