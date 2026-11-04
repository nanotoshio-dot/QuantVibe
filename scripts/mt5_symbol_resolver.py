"""Safe MetaTrader 5 symbol and tick-time helpers shared by web and bridge."""

from __future__ import annotations

import math
from typing import Any, Iterable


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def symbol_candidates(
    base_symbol: str,
    *,
    prefix: str = "",
    suffix: str = "",
    cent_account: bool = False,
) -> list[str]:
    """Return broker candidates in safe preference order.

    A Vantage USC/cent account commonly exposes FX and metals under ``.sc``.
    For that account type we try it before an unsuffixed alias, while retaining
    the exact alias as a fallback for instruments such as share CFDs.
    """
    base = str(base_symbol or "").strip()
    if not base:
        return []

    custom = f"{prefix}{base}{suffix}"
    candidates: list[str] = []
    if suffix or prefix:
        candidates.append(custom)
    if cent_account:
        candidates.append(f"{base}.sc")
    candidates.extend(
        [
            base,
            f"{base}.US",
            f"{base}.us",
            f"#{base}",
            f"{base}_CFD",
            f"{base}.cfd",
            f"{base}.pro",
            f"{base}_m",
            f"{base}.m",
            f"{base}.cash",
        ]
    )
    return _unique(candidates)


def resolve_mt5_symbol(
    mt5: Any,
    base_symbol: str,
    *,
    prefix: str = "",
    suffix: str = "",
    cent_account: bool = False,
) -> str | None:
    """Select and return the first symbol proven to exist in this terminal."""
    for candidate in symbol_candidates(
        base_symbol,
        prefix=prefix,
        suffix=suffix,
        cent_account=cent_account,
    ):
        if mt5.symbol_info(candidate) is not None:
            mt5.symbol_select(candidate, True)
            return candidate
    return None


def normalized_tick_age(
    tick_epoch: float,
    receipt_epoch: float,
    *,
    max_age: float,
    max_timezone_offset_hours: int = 14,
) -> tuple[float | None, int]:
    """Return validated tick age and a detected whole-hour broker offset.

    MT5 brokers may expose a server-clock timestamp rather than UTC. We only
    compensate a future skew that is within a plausible whole-hour timezone and
    leaves a fresh residual age. This does not turn an actually old tick into a
    fresh one: after the fixed offset is removed, it must still be within TTL.
    """
    if not all(math.isfinite(value) for value in (tick_epoch, receipt_epoch, max_age)):
        return None, 0
    if max_age <= 0:
        return None, 0

    raw_age = receipt_epoch - tick_epoch
    if 0 <= raw_age <= max_age:
        return raw_age, 0

    if raw_age >= 0:
        return None, 0

    offset_seconds = int(round((-raw_age) / 3600.0)) * 3600
    if offset_seconds <= 0 or offset_seconds > max_timezone_offset_hours * 3600:
        return None, 0

    adjusted_age = raw_age + offset_seconds
    if 0 <= adjusted_age <= max_age:
        return adjusted_age, offset_seconds
    return None, 0
