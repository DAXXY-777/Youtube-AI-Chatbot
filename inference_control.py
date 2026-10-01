"""Bounded single-worker execution for local GGUF inference."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore, RLock
from typing import TypeVar


LOCAL_QUEUE_CAPACITY = 4
LOCAL_INFERENCE_DEADLINE_SECONDS = 15.0
T = TypeVar("T")


class InferenceBusyError(RuntimeError):
    pass


class InferenceTimeoutError(RuntimeError):
    pass


class SingleWorkerInferenceQueue:
    """Run one local generation at a time and reject excess pending work quickly."""

    def __init__(
        self,
        capacity: int = LOCAL_QUEUE_CAPACITY,
        deadline_seconds: float = LOCAL_INFERENCE_DEADLINE_SECONDS,
    ) -> None:
        self.capacity = capacity
        self.deadline_seconds = deadline_seconds
        self._state_lock = RLock()
        self._slots = BoundedSemaphore(capacity)
        self._executor: ThreadPoolExecutor | None = self._new_executor()

    def run(self, action: Callable[[], T]) -> T:
        with self._state_lock:
            if self._executor is None:
                self._slots = BoundedSemaphore(self.capacity)
                self._executor = self._new_executor()
            slots = self._slots
            executor = self._executor
            if not slots.acquire(blocking=False):
                raise InferenceBusyError("Local inference queue is full.")

        try:
            future = executor.submit(action)
        except Exception:
            slots.release()
            raise
        try:
            result = future.result(timeout=self.deadline_seconds)
        except TimeoutError as error:
            if future.cancel():
                slots.release()
                raise InferenceBusyError("Local inference queue wait expired.") from error

            # A running llama.cpp call cannot be safely interrupted in-process.
            # Keep its slot reserved until completion so another generation never
            # races it against the same loaded model.
            future.add_done_callback(lambda _future: slots.release())
            raise InferenceTimeoutError("Local inference exceeded its deadline.") from error
        except Exception:
            slots.release()
            raise
        else:
            slots.release()
            return result

    def shutdown(self) -> None:
        with self._state_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _new_executor() -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-llm")


local_inference_queue = SingleWorkerInferenceQueue()
