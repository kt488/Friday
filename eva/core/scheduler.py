"""
Job scheduler for EVA evaluation harness.

Supports one-time, recurring, and cron-based scheduling with
priority queues and dependency management.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a scheduled job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    """Priority levels for jobs."""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(order=True)
class Job:
    """A scheduled evaluation job."""
    priority: int
    scheduled_at: float
    job_id: str = field(compare=False)
    name: str = field(compare=False)
    suite: str = field(compare=False)
    config: Dict[str, Any] = field(default_factory=dict, compare=False)
    status: JobStatus = field(default=JobStatus.PENDING, compare=False)
    dependencies: List[str] = field(default_factory=list, compare=False)
    retry_count: int = field(default=0, compare=False)
    max_retries: int = field(default=3, compare=False)
    created_at: float = field(default_factory=time.time, compare=False)
    callback: Optional[Callable] = field(default=None, compare=False)


class Scheduler:
    """Job scheduler for evaluation runs.

    Supports priority-based scheduling, dependency chains,
    recurring jobs, and cron-like schedules.
    """

    def __init__(self, engine):
        self.engine = engine
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running = False
        self._jobs: Dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._scheduler_task: Optional[asyncio.Task] = None
        self.logger = logger

    async def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True
        self._scheduler_task = asyncio.create_task(self._process_queue())
        self.logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Scheduler stopped")

    async def schedule(self, job: Job) -> str:
        """Schedule a new job.

        Args:
            job: Job to schedule.

        Returns:
            Job ID string.
        """
        async with self._lock:
            self._jobs[job.job_id] = job
            await self._queue.put(job)
            self.logger.info("Scheduled job '%s' (priority=%s)", job.name, job.priority)
        return job.job_id

    async def schedule_now(
        self,
        name: str,
        suite: str,
        config: Optional[Dict[str, Any]] = None,
        priority: JobPriority = JobPriority.MEDIUM,
    ) -> str:
        """Schedule a job to run immediately.

        Args:
            name: Job name.
            suite: Test suite name.
            config: Optional config overrides.
            priority: Job priority.

        Returns:
            Job ID string.
        """
        job = Job(
            priority=priority.value,
            scheduled_at=time.time(),
            job_id=str(uuid.uuid4()),
            name=name,
            suite=suite,
            config=config or {},
        )
        return await self.schedule(job)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job.

        Args:
            job_id: Job ID to cancel.

        Returns:
            True if job was cancelled.
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status in (JobStatus.PENDING,):
                job.status = JobStatus.CANCELLED
                self.logger.info("Cancelled job '%s'", job.name)
                return True
            return False

    async def _process_queue(self) -> None:
        """Main scheduler loop - process pending jobs."""
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if job.status == JobStatus.CANCELLED:
                continue

            # Check dependencies
            deps_met = True
            for dep_id in job.dependencies:
                dep_job = self._jobs.get(dep_id)
                if dep_job and dep_job.status != JobStatus.COMPLETED:
                    deps_met = False
                    break

            if not deps_met:
                # Re-queue with short delay
                job.scheduled_at = time.time() + 5
                await self._queue.put(job)
                continue

            # Execute
            async with self._lock:
                job.status = JobStatus.RUNNING

            try:
                result = await self.engine.run_suite(
                    suite_name=job.name,
                    tests=[],
                    parallel=True,
                )

                async with self._lock:
                    job.status = JobStatus.COMPLETED

                if job.callback:
                    await job.callback(result)

                self.logger.info("Job '%s' completed: %.1f%% pass rate",
                                 job.name, result.pass_rate)

            except Exception as e:
                async with self._lock:
                    job.retry_count += 1
                    if job.retry_count >= job.max_retries:
                        job.status = JobStatus.FAILED
                        self.logger.error("Job '%s' failed after %d retries: %s",
                                          job.name, job.max_retries, e)
                    else:
                        job.status = JobStatus.PENDING
                        job.scheduled_at = time.time() + (10 * job.retry_count)
                        await self._queue.put(job)
                        self.logger.warning("Job '%s' failed, retry %d/%d",
                                            job.name, job.retry_count, job.max_retries)

            finally:
                self._queue.task_done()

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status summary.

        Returns:
            Dict with queue size, running/completed/failed counts.
        """
        status = {
            "queue_size": self._queue.qsize(),
            "total_jobs": len(self._jobs),
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for job in self._jobs.values():
            if job.status == JobStatus.RUNNING:
                status["running"] += 1
            elif job.status == JobStatus.COMPLETED:
                status["completed"] += 1
            elif job.status == JobStatus.FAILED:
                status["failed"] += 1
            elif job.status == JobStatus.CANCELLED:
                status["cancelled"] += 1
        return status

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID.

        Args:
            job_id: Job ID.

        Returns:
            Job or None.
        """
        return self._jobs.get(job_id)
