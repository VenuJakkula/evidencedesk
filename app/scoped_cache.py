"""Process-local bounded retrieval cache; authorization is always re-evaluated outside it."""
import copy
import threading
import time
from collections import OrderedDict


class ScopedCache:
    def __init__(self, capacity=128, ttl=30, clock=time.monotonic):
        if not 1 <= capacity <= 1024 or not 0 < ttl <= 300: raise ValueError('Bound cache size and TTL')
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self.entries, self.lock = OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.entries.pop(key, None)
            if item is None or item[0] <= self.clock(): return None
            self.entries[key] = item
            return copy.deepcopy(item[1])

    def put(self, key, value):
        with self.lock:
            self.entries.pop(key, None)
            self.entries[key] = (self.clock()+self.ttl, copy.deepcopy(value))
            while len(self.entries) > self.capacity: self.entries.popitem(last=False)

    def __getstate__(self):
        # Spawned workers start empty; never serialize cached tenant material or locks.
        return {'capacity':self.capacity,'ttl':self.ttl}

    def __setstate__(self, state):
        self.__init__(**state)
