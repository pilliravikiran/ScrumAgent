"""Run agent work independently from Streamlit's rerun lifecycle."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable


# Bounded so a browser session cannot create an unbounded number of workers.
_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scrumagent")


@dataclass
class BackgroundRun:
    """A task plus a thread-safe record of the events it emits."""

    label: str
    future: Future | None = None
    _events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def log_event(self, event: dict[str, Any]) -> None:
        """Record progress without depending on Streamlit's script context."""
        with self._lock:
            self._events.append(dict(event))

    def events(self) -> list[dict[str, Any]]:
        """Return a stable snapshot for the foreground UI to render."""
        with self._lock:
            return list(self._events)

    @property
    def done(self) -> bool:
        return self.future is not None and self.future.done()


def start_background_run(label: str, work: Callable[..., Any], /,
                         *args: Any, **kwargs: Any) -> BackgroundRun:
    """Start work outside Streamlit's rerun lifecycle.

    ``work`` may accept ``event_log`` but must not call Streamlit APIs.
    """
    run = BackgroundRun(label=label)
    kwargs["event_log"] = run.log_event
    run.future = _WORKERS.submit(work, *args, **kwargs)
    return run
