"""Reference mask policy for the Skip19 T10 experiments."""

from __future__ import annotations


def decide_mask(
    profile: int,
    mh: int,
    gain1: float,
    gain2: float,
    nz0: float,
    nz1: float,
    nz2: float,
    *,
    single_margin: float = 0.0,
    zero_margin: float = 0.0,
) -> int:
    if mh < 2:
        return 0x1
    if profile <= 0:
        return 0x7

    if profile >= 3:
        both_rate_weak = gain1 <= -zero_margin and gain2 <= -zero_margin
        both_nz_weak = nz1 >= nz0 and nz2 >= nz0
        if both_rate_weak and both_nz_weak:
            return 0x1

    margin = max(0.0, single_margin)
    if gain1 - gain2 >= margin and nz1 <= nz2:
        return 0x3
    if gain2 - gain1 >= margin and nz2 <= nz1:
        return 0x5
    return 0x7


def table_stage_enabled(actual_cu_qp: int, max_cu_qp: int) -> bool:
    return actual_cu_qp <= max_cu_qp


def apply_single_candidate_to_full_mask(
    base_mask: int,
    mh: int,
    gain1: float,
    gain2: float,
    nz0: float,
    nz1: float,
    nz2: float,
    *,
    single_margin: float,
) -> int:
    if base_mask != 0x7:
        return base_mask
    return decide_mask(
        2,
        mh,
        gain1,
        gain2,
        nz0,
        nz1,
        nz2,
        single_margin=single_margin,
    )
