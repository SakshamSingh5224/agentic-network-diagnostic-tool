"""Agent call tracing (FR5).

Every tool call and reasoning note is recorded in memory and appended as one JSON
object per line to a log file, so the AI's diagnostic path can be audited later.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from netdiag.models import to_jsonable


@dataclass
class TraceEntry:
    session_id: str
    step: int
    kind: str  # "tool_call" | "reasoning"
    tool: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    status: str = "ok"  # "ok" | "error"
    result_summary: str = ""
    error: Optional[str] = None
    started_at: str = ""
    duration_ms: float = 0.0


class CallTracer:
    def __init__(self, log_path: Optional[str] = None, session_id: Optional[str] = None):
        self.log_path = Path(log_path) if log_path else None
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.entries: List[TraceEntry] = []
        self._lock = threading.Lock()

    # -- recording ---------------------------------------------------------
    def _append(self, entry: TraceEntry) -> None:
        with self._lock:
            entry.step = len(self.entries) + 1
            self.entries.append(entry)
            if self.log_path:
                try:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(to_jsonable(asdict(entry))) + "\n")
                except OSError:
                    pass  # logging must never break a diagnostic run

    def note(self, text: str) -> None:
        self._append(
            TraceEntry(
                self.session_id, 0, "reasoning", reasoning=text,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    @contextmanager
    def span(self, tool: str, arguments: Optional[Dict[str, Any]] = None, reasoning: str = "") -> Iterator[TraceEntry]:
        """Time a tool call. Set `entry.result_summary` inside the block."""
        entry = TraceEntry(
            self.session_id, 0, "tool_call", tool=tool, arguments=arguments or {},
            reasoning=reasoning, started_at=datetime.now(timezone.utc).isoformat(),
        )
        t0 = time.perf_counter()
        try:
            yield entry
        except Exception as exc:  # noqa: BLE001
            entry.status, entry.error = "error", str(exc)
            raise
        finally:
            entry.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._append(entry)

    # -- presentation ------------------------------------------------------
    def format(self) -> str:
        lines = [f"Agent trace (session {self.session_id})"]
        for e in self.entries:
            if e.kind == "reasoning":
                lines.append(f"  {e.step}. [thought] {e.reasoning}")
                continue
            args = ", ".join(f"{k}={v}" for k, v in e.arguments.items()) or "-"
            flag = "" if e.status == "ok" else f"  !! {e.error}"
            lines.append(f"  {e.step}. [tool] {e.tool}({args})  {e.duration_ms:.0f} ms{flag}")
            if e.reasoning:
                lines.append(f"       why: {e.reasoning}")
            if e.result_summary:
                lines.append(f"       -> {e.result_summary}")
        return "\n".join(lines)

    def to_list(self) -> List[Dict[str, Any]]:
        return [to_jsonable(asdict(e)) for e in self.entries]


_default: Optional[CallTracer] = None


def get_default_tracer() -> CallTracer:
    """Process-wide tracer (used by Langflow components so all calls share one log)."""
    global _default
    if _default is None:
        _default = CallTracer(os.environ.get("NETDIAG_TRACE_LOG", "logs/agent_trace.jsonl"))
    return _default
