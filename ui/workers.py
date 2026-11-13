"""Execução de tarefas em segundo plano sem travar a interface.

Os callbacks sempre rodam na thread da interface: os sinais são ligados a slots de um QObject
criado na thread principal, então o Qt entrega as chamadas via fila (queued connection).
"""
from __future__ import annotations

import logging
import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)

_pool = QThreadPool()
_pool.setMaxThreadCount(32)
_alive: set = set()


class _Relay(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)

    def __init__(self, on_done, on_error, on_progress):
        super().__init__()
        self._on_done, self._on_error, self._on_progress = on_done, on_error, on_progress
        self.done.connect(self._done)
        self.failed.connect(self._failed)
        self.progress.connect(self._prog)

    @Slot(object)
    def _done(self, result):
        try:
            if self._on_done:
                self._on_done(result)
        finally:
            _alive.discard(getattr(self, "task", None))

    @Slot(object)
    def _failed(self, exc):
        try:
            if self._on_error:
                self._on_error(exc)
            else:
                log.error("Tarefa falhou: %s", exc)
        finally:
            _alive.discard(getattr(self, "task", None))

    @Slot(object)
    def _prog(self, value):
        if self._on_progress:
            self._on_progress(value)


class Task(QRunnable):
    def __init__(self, fn, args, kwargs, relay: _Relay, with_progress: bool, with_cancel: bool):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args, self.kwargs, self.relay = fn, args, kwargs, relay
        self.cancel_event = threading.Event()
        if with_progress:
            self.kwargs["progress"] = lambda *a: relay.progress.emit(a if len(a) != 1 else a[0])
        if with_cancel:
            self.kwargs["cancel"] = self.cancel_event

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:  # noqa: BLE001
            log.debug("Erro na tarefa %s:\n%s", getattr(self.fn, "__name__", self.fn), traceback.format_exc())
            self.relay.failed.emit(exc)
        else:
            self.relay.done.emit(result)


def run_task(fn, *args, on_done=None, on_error=None, on_progress=None,
             with_progress=False, with_cancel=False, **kwargs) -> Task:
    relay = _Relay(on_done, on_error, on_progress)
    task = Task(fn, args, kwargs, relay, with_progress, with_cancel)
    relay.task = task
    _alive.add(task)
    _pool.start(task)
    return task
