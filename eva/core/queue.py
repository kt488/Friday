"""Task queue for distributed evaluation with in-memory and Redis backends."""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class QueueBackend(Enum):
    """Supported queue backends."""
    MEMORY = "memory"
    REDIS = "redis"


class TaskStatus(Enum):
    """Status of a queued task."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A single task in the evaluation queue."""
    id: str
    name: str
    payload: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    priority: int = 0

    @property
    def duration(self) -> Optional[float]:
        """Get task processing duration."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "duration": self.duration,
            "error": self.error,
        }


class QueueBackendBase:
    """Abstract base for queue backends."""

    async def enqueue(self, task: Task) -> None: ...
    async def dequeue(self) -> Optional[Task]: ...
    async def ack(self, task_id: str) -> None: ...
    async def nack(self, task_id: str) -> None: ...
    async def size(self) -> int: ...
    async def clear(self) -> None: ...


class MemoryQueueBackend(QueueBackendBase):
    """In-memory queue backend using asyncio.PriorityQueue."""

    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._pending: Dict[str, Task] = {}
        self._processing: Dict[str, Task] = {}
        self._completed: Dict[str, Task] = {}

    async def enqueue(self, task: Task) -> None:
        priority_tuple = (-task.priority, task.created_at, task.id)
        await self._queue.put(priority_tuple)
        self._pending[task.id] = task

    async def dequeue(self) -> Optional[Task]:
        try:
            _, _, task_id = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            task = self._pending.pop(task_id, None)
            if task:
                task.status = TaskStatus.PROCESSING
                task.started_at = time.time()
                self._processing[task_id] = task
                return task
        except (asyncio.TimeoutError, ValueError):
            pass
        return None

    async def ack(self, task_id: str) -> None:
        task = self._processing.pop(task_id, None)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            self._completed[task_id] = task

    async def nack(self, task_id: str) -> None:
        task = self._processing.pop(task_id, None)
        if task:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            self._completed[task_id] = task

    async def size(self) -> int:
        return self._queue.qsize()

    async def clear(self) -> None:
        self._pending.clear()
        self._processing.clear()
        self._completed.clear()


class TaskQueue:
    """Task queue for distributing evaluation work.

    Supports multiple backends (memory, Redis) and producer/consumer
    patterns with batch processing.

    Args:
        backend: Queue backend type.
        redis_url: Redis URL (required for redis backend).
        num_workers: Number of consumer workers.
    """

    def __init__(
        self,
        backend: Union[str, QueueBackend] = QueueBackend.MEMORY,
        redis_url: Optional[str] = None,
        num_workers: int = 4,
    ):
        if isinstance(backend, str):
            backend = QueueBackend(backend)

        if backend == QueueBackend.REDIS:
            if not redis_url:
                raise ValueError("Redis URL required for redis backend")
            self._backend = self._create_redis_backend(redis_url)
        else:
            self._backend = MemoryQueueBackend()

        self.num_workers = num_workers
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._handler: Optional[Callable] = None
        self._results: Dict[str, Any] = {}
        self.logger = logger

    def _create_redis_backend(self, redis_url: str) -> QueueBackendBase:
        """Create Redis queue backend (placeholder)."""
        self.logger.warning("Redis backend not fully implemented, falling back to memory")
        return MemoryQueueBackend()

    async def enqueue(self, name: str, payload: Dict[str, Any],
                      priority: int = 0) -> str:
        """Enqueue a new task.

        Args:
            name: Task name.
            payload: Task data payload.
            priority: Priority (higher = more urgent).

        Returns:
            Task ID.
        """
        task = Task(
            id=str(uuid.uuid4()),
            name=name,
            payload=payload,
            priority=priority,
        )
        await self._backend.enqueue(task)
        self.logger.debug("Enqueued task '%s' (%s)", name, task.id)
        return task.id

    async def enqueue_batch(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Enqueue multiple tasks.

        Args:
            tasks: List of dicts with 'name', 'payload', optional 'priority'.

        Returns:
            List of task IDs.
        """
        ids = []
        for t in tasks:
            task_id = await self.enqueue(
                t.get("name", "unnamed"),
                t.get("payload", {}),
                t.get("priority", 0),
            )
            ids.append(task_id)
        return ids

    def register_handler(self, handler: Callable) -> None:
        """Register a task processing handler.

        Args:
            handler: Async callable that accepts a Task and returns a result.
        """
        self._handler = handler

    async def start(self) -> None:
        """Start worker pool."""
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self.num_workers)
        ]
        self.logger.info("Started %d workers", self.num_workers)

    async def stop(self) -> None:
        """Stop all workers."""
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self.logger.info("Workers stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop - process tasks from queue.

        Args:
            worker_id: Worker identifier.
        """
        while self._running:
            try:
                task = await self._backend.dequeue()
                if task is None:
                    await asyncio.sleep(0.1)
                    continue

                self.logger.debug("Worker %d processing task '%s'", worker_id, task.name)

                try:
                    if self._handler:
                        result = await self._handler(task)
                        task.result = result
                    await self._backend.ack(task.id)
                    self._results[task.id] = task
                except Exception as e:
                    self.logger.error("Worker %d failed task '%s': %s",
                                      worker_id, task.name, e)
                    task.error = str(e)
                    await self._backend.nack(task.id)
                    self._results[task.id] = task

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Worker %d error: %s", worker_id, e)

    async def queue_size(self) -> int:
        """Get current queue size."""
        return await self._backend.size()

    def get_results(self, task_id: Optional[str] = None) -> Any:
        """Get task results.

        Args:
            task_id: Specific task ID or None for all.

        Returns:
            Task or dict of tasks.
        """
        if task_id:
            return self._results.get(task_id)
        return self._results

    async def clear(self) -> None:
        """Clear all pending tasks."""
        await self._backend.clear()
        self._results.clear()
