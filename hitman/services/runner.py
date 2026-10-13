"""Send requests on background threads so the UI never blocks."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from hitman.core.http import RequestCancelled, ResolvedRequest, SendOptions, send


@dataclass
class _Job:
    id: int
    cancel: threading.Event


class RequestRunner(QObject):
    finished = Signal(str, object)    # tab_id, HttpResponse
    _done = Signal(int, str, object)  # internal: job_id, tab_id, response (emitted from worker threads)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._jobs: dict[str, _Job] = {}
        self._next_id = 0
        self._done.connect(self._on_done)

    def is_running(self, tab_id: str) -> bool:
        return tab_id in self._jobs

    def send(self, tab_id: str, request: ResolvedRequest, options: SendOptions) -> None:
        self.cancel(tab_id)
        self._next_id += 1
        job = _Job(self._next_id, threading.Event())
        self._jobs[tab_id] = job
        threading.Thread(target=self._work, args=(job, tab_id, request, options), daemon=True).start()

    def cancel(self, tab_id: str) -> None:
        job = self._jobs.pop(tab_id, None)
        if job:
            job.cancel.set()

    def _work(self, job: _Job, tab_id: str, request: ResolvedRequest, options: SendOptions) -> None:
        try:
            response = send(request, options, job.cancel)
        except RequestCancelled:
            return
        self._done.emit(job.id, tab_id, response)

    def _on_done(self, job_id: int, tab_id: str, response) -> None:
        job = self._jobs.get(tab_id)
        if job is None or job.id != job_id or job.cancel.is_set():
            return  # cancelled or superseded
        del self._jobs[tab_id]
        self.finished.emit(tab_id, response)
