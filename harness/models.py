"""Friday AI Runtime Harness — Data Models & Type Definitions."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PlanStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class ToolStatus(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class StepType(enum.Enum):
    THINK = "think"
    REASON = "reason"
    CODE = "code"
    TOOL = "tool"
    RESEARCH = "research"
    MEMORY = "memory"
    VERIFY = "verify"
    RESPOND = "respond"


class ExecutionMode(enum.Enum):
    STANDARD = "standard"
    RESEARCH = "research"
    CODING = "coding"
    REASONING = "reasoning"
    DEBUG = "debug"
    AUTONOMOUS = "autonomous"


class MemoryType(enum.Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    WORKFLOW = "workflow"
    CONTEXT = "context"
    DECISION = "decision"
    ERROR = "error"


class Severity(enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


# ── Core Data Models ──────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    """Definition of a tool available for execution."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_params: List[str] = field(default_factory=list)
    category: str = "general"
    timeout: int = 30
    dangerous: bool = False
    enabled: bool = True


@dataclass
class ToolCall:
    """A single tool invocation within a plan step."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    status: ToolStatus = ToolStatus.IDLE
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    retry_count: int = 0


@dataclass
class Step:
    """A single step within a plan."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""
    step_type: StepType = StepType.THINK
    tool_calls: List[ToolCall] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    reasoning: Optional[str] = None
    tokens_used: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Plan:
    """A directed plan composed of multiple steps."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    goal: str = ""
    steps: List[Step] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    mode: ExecutionMode = ExecutionMode.STANDARD
    context_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    total_tokens: int = 0
    total_cost: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextFrame:
    """Working memory for a single conversation or task."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    conversation_id: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    compressed: bool = False
    summary: Optional[str] = None


@dataclass
class MemoryEntry:
    """A stored memory entry with metadata."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    key: str = ""
    value: Any = None
    memory_type: MemoryType = MemoryType.FACT
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    ttl: Optional[int] = None  # seconds, None = permanent


@dataclass
class ValidationResult:
    """Result of a self-check validation."""
    passed: bool = True
    score: float = 1.0
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    details: Optional[str] = None


@dataclass
class ResearchFinding:
    """A single finding from research mode."""
    source: str = ""
    title: str = ""
    content: str = ""
    url: Optional[str] = None
    relevance: float = 0.5
    extracted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Observation:
    """A single observability event/metric."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    event: str = ""
    level: Severity = Severity.INFO
    component: str = ""
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    tokens: Optional[int] = None
    cost: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: Optional[str] = None


@dataclass
class HarnessResult:
    """Top-level result returned by the harness."""
    success: bool = True
    response: str = ""
    plan: Optional[Plan] = None
    steps_completed: int = 0
    steps_total: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    duration_ms: float = 0.0
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None
    mode: ExecutionMode = ExecutionMode.STANDARD
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Plugin System ─────────────────────────────────────────────────────────────

class PluginPriority(enum.IntEnum):
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100


@dataclass
class PluginHook:
    """Registration of a hook point."""
    name: str
    description: str
    handlers: List[str] = field(default_factory=list)


# ── Utility ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
