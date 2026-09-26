"""P03 process guard: external sockets only during the fixed Amap transport."""

from contextlib import contextmanager
from threading import local
from collections.abc import Iterator

_state = local()


@contextmanager
def amap_transport() -> Iterator[None]:
    _state.amap = True
    try:
        yield
    finally:
        _state.amap = False


def in_amap_transport() -> bool:
    return bool(getattr(_state, "amap", False))
