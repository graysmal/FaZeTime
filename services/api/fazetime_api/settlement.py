"""Pari-mutuel settlement, ECONOMICS §4 (PARIMUTUEL_FLOOR_REMAINDER_V1). Pure Python ints; no fee.

For each winning wager with stake s: base = floor(s*T/W), remainder numerator = (s*T) mod W.
The T - sum(base) leftover cents go one each to winners in descending remainder order, ties broken
by wager_id ascending (ASCII). The payout includes the returned stake. sum(payouts) == T exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

ALGORITHM = "PARIMUTUEL_FLOOR_REMAINDER_V1"


class SettlementInvariantError(AssertionError):
    """Raised when a pool cannot be settled (0 < W < T is violated). Never settle in that case."""


@dataclass(frozen=True)
class StakeLine:
    wager_id: str
    side: str
    amount_minor: int


def _check_int(value: object, name: str) -> int:
    if type(value) is not int:  # bool is rejected too
        raise SettlementInvariantError(f"{name} must be an int, got {type(value).__name__}")
    return value


def compute_payouts(stakes: list[StakeLine], winning_side: str) -> dict[str, int]:
    """Return {wager_id: gross payout} for winning wagers only. Losing wagers receive 0."""
    if winning_side not in ("YES", "NO"):
        raise SettlementInvariantError("winning_side must be YES or NO")
    ids = [s.wager_id for s in stakes]
    if len(set(ids)) != len(ids):
        raise SettlementInvariantError("duplicate wager_id in stake set")
    for s in stakes:
        if _check_int(s.amount_minor, "amount_minor") <= 0:
            raise SettlementInvariantError("stakes must be positive")
        if s.side not in ("YES", "NO"):
            raise SettlementInvariantError("side must be YES or NO")
    total = sum(s.amount_minor for s in stakes)
    winners = [s for s in stakes if s.side == winning_side]
    winning_total = sum(s.amount_minor for s in winners)
    if not (0 < winning_total < total):
        raise SettlementInvariantError(f"cannot settle: requires 0 < W < T (W={winning_total}, T={total})")
    payouts: dict[str, int] = {}
    remainders: dict[str, int] = {}
    for s in winners:
        numerator = s.amount_minor * total
        payouts[s.wager_id] = numerator // winning_total
        remainders[s.wager_id] = numerator % winning_total
    leftover = total - sum(payouts.values())
    if not (0 <= leftover < len(winners)):
        raise SettlementInvariantError("remainder allocation out of range")
    order = sorted(winners, key=lambda s: (-remainders[s.wager_id], s.wager_id))
    for s in order[:leftover]:
        payouts[s.wager_id] += 1
    if sum(payouts.values()) != total:
        raise SettlementInvariantError("payouts do not conserve the pool")
    for s in winners:
        if payouts[s.wager_id] < s.amount_minor:
            raise SettlementInvariantError("a winner cannot receive less than its stake")
    return payouts


def estimate_gross_return(stake_minor: int, total_minor: int, side_total_minor: int) -> int:
    """§9.6 pre-lock estimate: floor(s*(T+s)/(W_side+s)). Labelled as an estimate."""
    s, t, w = (_check_int(v, "amount") for v in (stake_minor, total_minor, side_total_minor))
    if s <= 0 or t < 0 or w < 0 or w > t:
        raise ValueError("invalid estimate inputs")
    return (s * (t + s)) // (w + s)
