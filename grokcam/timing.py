"""Small stage timing utility."""

from contextlib import contextmanager
import time


@contextmanager
def timed(label: str, timings: dict[str, float]):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[label] += time.perf_counter() - started
