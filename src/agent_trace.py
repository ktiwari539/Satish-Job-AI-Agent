import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


_ACTIVE_TRACER: ContextVar = ContextVar("job_agent_active_tracer", default=None)
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
    "otp",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_value(value: Any, *, max_length: int = 500):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        clean = " ".join(value.split())
        if len(clean) > max_length:
            return clean[:max_length] + "...<truncated>"
        return clean
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item, max_length=max_length) for item in list(value)[:50]]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = _safe_value(item, max_length=max_length)
        return result
    return _safe_value(str(value), max_length=max_length)


class RunTracer:
    """Structured local observability for one agent run.

    Events are printed to the terminal and persisted under gitignored data/.
    Sensitive credential-like keys are redacted before output.
    """

    def __init__(
        self,
        trace_dir: str = "data/agent_runs",
        *,
        heartbeat_seconds: float = 5.0,
        print_events: bool = True,
    ):
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
        self.events_path = self.trace_dir / f"{self.run_id}.jsonl"
        self.status_path = self.trace_dir.parent / "agent_status.json"
        self.latest_events_path = self.trace_dir.parent / "agent_latest.jsonl"
        self.heartbeat_seconds = max(float(heartbeat_seconds), 1.0)
        self.print_events = bool(print_events)
        self._run_started = time.monotonic()
        self._step_stack = []
        self._last_event: Dict[str, Any] = {}
        self._status = "running"
        self._finished = False
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.latest_events_path.write_text("", encoding="utf-8")
        self.emit(
            "run_start",
            pid=os.getpid(),
            events_file=str(self.events_path),
            status_file=str(self.status_path),
        )
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="job-agent-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _current_step_snapshot(self):
        with self._lock:
            stack = list(self._step_stack)
        if not stack:
            return "", "", 0.0
        current = stack[-1]
        path = " > ".join(item["name"] for item in stack)
        elapsed = max(0.0, time.monotonic() - current["started_monotonic"])
        return current["name"], path, elapsed

    def emit(self, event: str, **payload) -> Dict[str, Any]:
        current_step, step_path, step_elapsed = self._current_step_snapshot()
        record = {
            "timestamp": _utc_now(),
            "run_id": self.run_id,
            "event": event,
            "run_elapsed_seconds": round(time.monotonic() - self._run_started, 3),
            "current_step": current_step,
            "step_path": step_path,
            "step_elapsed_seconds": round(step_elapsed, 3),
        }
        record.update(_safe_value(payload))

        line = json.dumps(record, sort_keys=True, ensure_ascii=True)
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            with self.latest_events_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._last_event = record
            self._write_status_locked()

        if self.print_events:
            print(line, flush=True)
        return record

    def _write_status_locked(self) -> None:
        current_step, step_path, step_elapsed = self._current_step_snapshot()
        payload = {
            "run_id": self.run_id,
            "status": self._status,
            "pid": os.getpid(),
            "current_step": current_step,
            "step_path": step_path,
            "step_elapsed_seconds": round(step_elapsed, 3),
            "run_elapsed_seconds": round(time.monotonic() - self._run_started, 3),
            "last_event": self._last_event.get("event", ""),
            "last_event_at": self._last_event.get("timestamp", ""),
            "events_file": str(self.events_path),
            "latest_events_file": str(self.latest_events_path),
        }
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)

    @contextmanager
    def step(self, name: str, **payload):
        frame = {
            "name": str(name),
            "started_monotonic": time.monotonic(),
        }
        with self._lock:
            self._step_stack.append(frame)
        self.emit("step_start", step=name, **payload)
        started = time.monotonic()
        try:
            yield
        except BaseException as exc:
            self.emit(
                "step_error",
                step=name,
                duration_seconds=round(time.monotonic() - started, 3),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        else:
            self.emit(
                "step_end",
                step=name,
                duration_seconds=round(time.monotonic() - started, 3),
            )
        finally:
            with self._lock:
                if self._step_stack and self._step_stack[-1] is frame:
                    self._step_stack.pop()
                elif frame in self._step_stack:
                    self._step_stack.remove(frame)
                self._write_status_locked()

    def finish(self, status: str, *, exit_code: int = 0, **payload) -> None:
        if self._finished:
            return
        self._status = str(status)
        self.emit("run_finish", status=self._status, exit_code=exit_code, **payload)
        self._finished = True
        self._stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1.0)
        with self._lock:
            self._write_status_locked()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            current_step, step_path, step_elapsed = self._current_step_snapshot()
            if current_step:
                self.emit(
                    "heartbeat",
                    step=current_step,
                    step_path=step_path,
                    step_elapsed_seconds=round(step_elapsed, 3),
                )


def set_active_tracer(tracer: Optional[RunTracer]):
    return _ACTIVE_TRACER.set(tracer)


def reset_active_tracer(token) -> None:
    _ACTIVE_TRACER.reset(token)


def get_active_tracer() -> Optional[RunTracer]:
    return _ACTIVE_TRACER.get()


def trace_event(event: str, **payload) -> None:
    tracer = get_active_tracer()
    if tracer is not None:
        tracer.emit(event, **payload)


@contextmanager
def trace_step(name: str, **payload):
    tracer = get_active_tracer()
    if tracer is None:
        yield
        return
    with tracer.step(name, **payload):
        yield
