"""Structured event log.

Everything downstream reads this: the live UI renders it, the benchmark
analyses it, and the demo video is a recording of it. So it is JSONL on
disk from the start rather than print statements we regret in October.

One line per event, flushed immediately, so a reader can tail a run in
progress.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


@dataclass
class EventLog:
    path: Path | None = None
    echo: bool = True
    t0: float = field(default_factory=time.perf_counter)
    _fh: TextIO | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("w", encoding="utf-8")

    def emit(self, kind: str, **data: Any) -> None:
        rec = {"t": round(time.perf_counter() - self.t0, 3), "kind": kind, **data}
        if self._fh:
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
        if self.echo:
            print(self._render(rec), flush=True)

    @staticmethod
    def _render(rec: dict) -> str:
        t, kind = rec["t"], rec["kind"]
        head = f"[{t:>7.2f}s] {kind:<14}"
        skip = {"t", "kind"}
        body = "  ".join(f"{k}={v}" for k, v in rec.items() if k not in skip)
        return head + body

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
