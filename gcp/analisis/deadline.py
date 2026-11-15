"""Bounded daemon workers enforce a response deadline even on a stalled SDK/DNS call."""

import queue
import threading
import time

_slots = threading.BoundedSemaphore(8)


def run(operation, seconds):
    deadline = time.monotonic() + seconds
    if not _slots.acquire(blocking=False):
        raise TimeoutError("Dependency capacity exhausted")
    result = queue.Queue(maxsize=1)

    def work():
        try:
            result.put((True, operation(deadline)))
        except Exception as exc:
            result.put((False, exc))
        finally:
            _slots.release()

    threading.Thread(target=work, daemon=True).start()
    try:
        ok, value = result.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise TimeoutError("Dependency deadline exceeded") from None
    if not ok:
        raise value
    return value


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Dependency deadline exceeded")
    return seconds
