"""Bounded, one-use browser entry renewal for the same local filesystem owner."""

import hmac
import secrets
import time
from typing import Callable


def entry_proof(key: bytes) -> str:
    return hmac.digest(key, b"local-entry-renewal", "sha256").hex()


class EntryTickets:
    def __init__(self, initial: str, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.pending = {initial: clock() + 300}

    def issue(self) -> str:
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v > now}
        while len(self.pending) >= 8:
            self.pending.pop(next(iter(self.pending)))
        ticket = secrets.token_urlsafe(32)
        self.pending[ticket] = now + 300
        return ticket

    def consume(self, ticket: str) -> bool:
        expires = self.pending.pop(ticket, 0)
        return expires > self.clock()
