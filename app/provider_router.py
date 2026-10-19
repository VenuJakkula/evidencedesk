"""Explicit two-provider experiment with policy-equivalent fallback and finite budgets."""
import time
import math
from dataclasses import dataclass
from .workbooks import Problem
from .observability import span


@dataclass(frozen=True)
class Peer:
    name: str
    provider: object
    region: str
    privacy: str
    price_cap: float


class RoutedDraft:
    """Opt-in experiment; not installed in primary workflows or their budget ledger."""
    experimental_only=True
    def __init__(self, peers, preferred, *, region, privacy, max_price, cooldown=10, clock=time.monotonic):
        if len(peers) != 2 or len({peer.name for peer in peers}) != 2:
            raise ValueError('Two distinct providers required')
        if preferred not in {peer.name for peer in peers}: raise ValueError('Unknown preferred provider')
        if not math.isfinite(max_price) or max_price<0 or not 0<cooldown<=300:
            raise ValueError('Use finite price caps and bounded cooldown')
        if any(peer.region != region or peer.privacy != privacy or not math.isfinite(peer.price_cap) or peer.price_cap > max_price or peer.price_cap < 0 for peer in peers):
            raise Problem('routing_policy', 'Fallback must preserve region, privacy and price bounds.', 503)
        self.peers = sorted(peers, key=lambda peer: peer.name != preferred)
        self.clock, self.cooldown = clock, cooldown
        self.unavailable = {}
        self.model = 'experimental-router:'+':'.join(peer.provider.model for peer in self.peers)

    def draft(self, question, chunks, timeout):
        if not 0 < timeout <= 20: raise Problem('provider_deadline', 'Use a bounded provider deadline.', 504)
        deadline = self.clock()+timeout
        for peer in self.peers:
            remaining = deadline-self.clock()
            if remaining <= 0: break
            if self.unavailable.get(peer.name, 0) > self.clock(): continue
            with span('provider') as update:
                try:
                    result = peer.provider.draft(question, chunks, remaining)
                    if self.clock() >= deadline: raise Problem('provider_deadline', 'Provider deadline exceeded.', 504)
                    update(provider_calls=1)
                    return result
                except Problem as error:
                    # Invalid claims, authorization, schema and policy errors never trigger fallback.
                    if error.code != 'provider_unavailable': raise
                    self.unavailable[peer.name] = self.clock()+self.cooldown
                    update(failure='provider', provider_calls=1)
        raise Problem('provider_unavailable', 'Equivalent providers exhausted or cooling down.', 503)
