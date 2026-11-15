"""ECONOMICS §4 settlement arithmetic: exact, conserving, deterministic, fee-free."""

from __future__ import annotations

import random

import pytest

from fazetime_api.settlement import SettlementInvariantError, StakeLine, compute_payouts, estimate_gross_return


def test_worked_example_167_333_500():
    stakes = [
        StakeLine("wgr_a", "YES", 100),
        StakeLine("wgr_b", "YES", 200),
        StakeLine("wgr_c", "YES", 300),
        StakeLine("wgr_l", "NO", 400),
    ]
    payouts = compute_payouts(stakes, "YES")
    assert payouts == {"wgr_a": 167, "wgr_b": 333, "wgr_c": 500}
    assert sum(payouts.values()) == 1000  # whole escrow, zero fee
    assert {k: v - s.amount_minor for s in stakes for k, v in payouts.items() if k == s.wager_id} == {
        "wgr_a": 67, "wgr_b": 133, "wgr_c": 200}
    assert "wgr_l" not in payouts


def test_property_conservation_random_pools():
    rng = random.Random(20261114)
    for _ in range(3000):
        n = rng.randint(2, 25)
        stakes = [StakeLine(f"wgr_{i:032x}", rng.choice(["YES", "NO"]), rng.randint(1, 500) * 100) for i in range(n)]
        sides = {s.side for s in stakes}
        if sides != {"YES", "NO"}:
            stakes.append(StakeLine("wgr_" + "f" * 32, ({"YES", "NO"} - sides).pop(), 100))
        winner = rng.choice(["YES", "NO"])
        total = sum(s.amount_minor for s in stakes)
        payouts = compute_payouts(stakes, winner)
        assert sum(payouts.values()) == total
        for s in stakes:
            if s.side == winner:
                assert payouts[s.wager_id] >= s.amount_minor
            else:
                assert s.wager_id not in payouts
        # determinism: order of input does not matter
        shuffled = stakes[:]
        rng.shuffle(shuffled)
        assert compute_payouts(shuffled, winner) == payouts


def test_tie_break_by_wager_id_ascii():
    # T=1000 W=300 with three equal stakes: base 333 each (999), remainders equal -> lowest id gets the cent
    stakes = [StakeLine("wgr_c", "YES", 100), StakeLine("wgr_a", "YES", 100), StakeLine("wgr_b", "YES", 100),
              StakeLine("wgr_z", "NO", 700)]
    payouts = compute_payouts(stakes, "YES")
    assert payouts == {"wgr_a": 334, "wgr_b": 333, "wgr_c": 333}


@pytest.mark.parametrize("winning_side", ["YES", "NO"])
def test_zero_winning_stake_is_impossible(winning_side):
    one_sided = [StakeLine("wgr_a", "NO" if winning_side == "YES" else "YES", 500)]
    with pytest.raises(SettlementInvariantError):
        compute_payouts(one_sided, winning_side)  # W = 0
    all_winners = [StakeLine("wgr_a", winning_side, 500)]
    with pytest.raises(SettlementInvariantError):
        compute_payouts(all_winners, winning_side)  # W = T
    with pytest.raises(SettlementInvariantError):
        compute_payouts([], winning_side)


def test_rejects_non_integer_amounts():
    with pytest.raises(SettlementInvariantError):
        compute_payouts([StakeLine("wgr_a", "YES", 1.5), StakeLine("wgr_b", "NO", 100)], "YES")
    with pytest.raises(SettlementInvariantError):
        compute_payouts([StakeLine("wgr_a", "YES", True), StakeLine("wgr_b", "NO", 100)], "YES")


def test_estimate_formula():
    # floor(s*(T+s)/(W_side+s)); empty pool returns the stake
    assert estimate_gross_return(500, 0, 0) == 500
    assert estimate_gross_return(500, 1000, 600) == (500 * 1500) // 1100
