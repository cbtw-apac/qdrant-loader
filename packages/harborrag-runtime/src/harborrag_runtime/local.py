from collections.abc import Callable


def run_sync[T](fn: Callable[[], T]) -> T:
    return fn()
