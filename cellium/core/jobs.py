"""Background job manager for Cellium.

Qt-free by design (AGENTS.md invariant 2: `core/` is headless and must not
depend on PySide6). Ported in spirit from the archived `ManagedJob` /
`ProcessPool` pair in `Cerebellium Opus.py`, which had no counterpart in Cellium.

Long-running work (model pulls, batch inpainting, tree walks, index rebuilds)
should run through this rather than blocking the UI thread. It is thread-safe:
`ManagedJob` state transitions are guarded by a lock, and listeners are invoked
outside that lock so a listener may safely submit further work.

Usage
-----
    from cellium.core.jobs import ProcessPool
    pool = ProcessPool(max_workers=4)
    job = pool.submit("Warm model", do_thing, arg1)
    job.on_progress(lambda pct, msg: ...)
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

__all__ = ["JobState", "ManagedJob", "ProcessPool", "get_pool", "current_job"]


# The currently-executing job for this thread. Without this, a submitted
# function had no ergonomic way to reach its own ManagedJob in order to call
# checkpoint(), which made cooperative pause/cancel unusable.
_TLS = threading.local()


def current_job() -> "ManagedJob | None":
    """Return the ManagedJob running on this thread, or None outside a job."""
    return getattr(_TLS, "job", None)


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.COMPLETED, JobState.ERROR, JobState.CANCELLED)

    @property
    def is_active(self) -> bool:
        return self in (JobState.RUNNING, JobState.PAUSED)


@dataclass
class ManagedJob:
    """A single unit of background work with observable state."""

    title: str
    fn: Callable[..., Any]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    state: JobState = JobState.QUEUED
    progress: float = 0.0          # 0.0 .. 1.0
    message: str = ""
    result: Any = None
    error: str = ""
    traceback_text: str = ""

    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    paused_total: float = 0.0

    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    # Convention: _pause SET == paused. A fresh Event() is already unset.
    _pause: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    _progress_cbs: List[Callable] = field(default_factory=list, repr=False)
    _state_cbs: List[Callable] = field(default_factory=list, repr=False)

    # ── elapsed / eta ────────────────────────────────────────────────────
    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at - self.paused_total)

    @property
    def eta(self) -> Optional[float]:
        if self.state is not JobState.RUNNING or self.progress <= 0.01:
            return None
        return max(0.0, self.elapsed * (1.0 - self.progress) / self.progress)

    # ── observers ────────────────────────────────────────────────────────
    def on_progress(self, cb: Callable) -> "ManagedJob":
        self._progress_cbs.append(cb)
        return self

    def on_state(self, cb: Callable) -> "ManagedJob":
        self._state_cbs.append(cb)
        return self

    def _emit(self, cbs, *a) -> None:
        for cb in list(cbs):
            try:
                cb(*a)
            except Exception:
                pass

    def set_progress(self, value: float, message: str = "") -> None:
        with self._lock:
            self.progress = max(0.0, min(1.0, float(value)))
            if message:
                self.message = message
        self._emit(self._progress_cbs, self.progress, self.message)

    def _set_state(self, state: JobState) -> None:
        with self._lock:
            changed = self.state is not state
            self.state = state
            if state is JobState.RUNNING and self.started_at is None:
                self.started_at = time.time()
            if state.is_terminal:
                self.finished_at = time.time()
        if changed:
            self._emit(self._state_cbs, self)

    # ── cooperative control ──────────────────────────────────────────────
    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()
        # Release a paused job so it can observe the cancel flag.
        self._pause.set()
        if self.state is JobState.QUEUED:
            self._set_state(JobState.CANCELLED)

    def pause(self) -> None:
        if self.state is JobState.RUNNING:
            self._pause.set()
            self._set_state(JobState.PAUSED)

    def resume(self) -> None:
        if self.state is JobState.PAUSED:
            if self.started_at is not None and self.finished_at is None:
                pass
            self._pause.clear()
            self._set_state(JobState.RUNNING)

    def checkpoint(self) -> bool:
        """Call inside long loops. Returns False once cancelled or paused.

        Pausing blocks here until `resume()` is called, so a paused job costs
        nothing and burns no CPU.

        Inside a submitted function, reach the job via
        ``from cellium.core.jobs import current_job`` then
        ``current_job().checkpoint()``.
        """
        if self._cancel.is_set():
            return False
        while self._pause.is_set() and not self._cancel.is_set():
            time.sleep(0.05)
        return not self._cancel.is_set()

    # ── execution ────────────────────────────────────────────────────────
    def run(self) -> "ManagedJob":
        if self._cancel.is_set():
            self._set_state(JobState.CANCELLED)
            return self
        self._set_state(JobState.RUNNING)
        _TLS.job = self
        try:
            self.result = self.fn(*self.args, **self.kwargs)
            if self._cancel.is_set():
                # fn returned normally but cancel() was requested mid-flight;
                # reporting COMPLETED here would show a full progress bar for
                # work the user deliberately abandoned.
                self._set_state(JobState.CANCELLED)
            else:
                self.set_progress(1.0, "done")
                self._set_state(JobState.COMPLETED)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.traceback_text = traceback.format_exc()
            self._set_state(JobState.ERROR)
        finally:
            _TLS.job = None
        return self


class ProcessPool:
    """Thread-backed job queue. Named for parity with the archived class."""

    def __init__(self, max_workers: int = 4, name: str = "cellium-jobs"):
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)),
                                             thread_name_prefix=name)
        self._lock = threading.RLock()
        self._jobs: List[ManagedJob] = []
        self._listeners: List[Callable] = []
        self._shutdown = False

    # ── registry ─────────────────────────────────────────────────────────
    @property
    def jobs(self) -> List[ManagedJob]:
        with self._lock:
            return list(self._jobs)

    def active_count(self) -> int:
        return sum(1 for j in self.jobs if j.state.is_active)

    def pending(self) -> List[ManagedJob]:
        return [j for j in self.jobs if j.state is JobState.QUEUED]

    def add_listener(self, cb: Callable) -> Callable:
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)
        return cb

    def remove_listener(self, cb: Callable) -> None:
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    # ── submission ───────────────────────────────────────────────────────
    def submit(self, title: str, fn: Callable, *args, on_progress=None,
               on_state=None, **kwargs) -> ManagedJob:
        if self._shutdown:
            raise RuntimeError("ProcessPool has been shut down")
        job = ManagedJob(title=title, fn=fn, args=args, kwargs=kwargs)
        if on_progress:
            job.on_progress(on_progress)
        if on_state:
            job.on_state(on_state)

        # Always notify so listeners (a Qt UI, typically) can re-render.
        job.on_progress(lambda *_: self._notify())
        job.on_state(lambda *_: self._notify())

        with self._lock:
            self._jobs.insert(0, job)
        self._executor.submit(job.run)
        self._notify()
        return job

    def get(self, job_id: str) -> Optional[ManagedJob]:
        for j in self.jobs:
            if j.job_id == job_id:
                return j
        return None

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if not j.state.is_terminal]
            removed = before - len(self._jobs)
        if removed:
            self._notify()
        return removed

    # ── bulk control ─────────────────────────────────────────────────────
    def pause_all(self) -> None:
        for j in self.jobs:
            if j.state is JobState.RUNNING:
                j.pause()

    def resume_all(self) -> None:
        for j in self.jobs:
            if j.state is JobState.PAUSED:
                j.resume()

    def cancel_all(self) -> None:
        for j in self.jobs:
            if j.state.is_active or j.state is JobState.QUEUED:
                j.cancel()
        self._notify()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until nothing is active or queued. Returns True if drained."""
        deadline = None if timeout is None else time.time() + timeout
        while True:
            if self.active_count() == 0 and not self.pending():
                return True
            if deadline is not None and time.time() > deadline:
                return False
            time.sleep(0.02)

    def shutdown(self, wait: bool = True) -> None:
        self.cancel_all()
        self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


_GLOBAL_POOL: Optional[ProcessPool] = None
_GLOBAL_LOCK = threading.Lock()


def get_pool() -> ProcessPool:
    """Process-wide default pool, created on first use."""
    global _GLOBAL_POOL
    with _GLOBAL_LOCK:
        if _GLOBAL_POOL is None:
            _GLOBAL_POOL = ProcessPool(max_workers=4)
        return _GLOBAL_POOL
