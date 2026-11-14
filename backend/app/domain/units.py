"""Hours are the canonical unit; FTE is a derived display unit (BR-CAP-001)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

STANDARD_WEEKLY_HOURS = Decimal("40")
HOURS_QUANTUM = Decimal("0.01")
FTE_QUANTUM = Decimal("0.001")


def to_decimal(value: Decimal | int | float | str) -> Decimal:
    """Convert without binary-float artefacts (floats go through their shortest repr)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def quantize_hours(value: Decimal | int | float | str) -> Decimal:
    """Round to 2 decimals, half-up (A-32)."""
    return to_decimal(value).quantize(HOURS_QUANTUM, rounding=ROUND_HALF_UP)


def hours_to_fte(
    hours: Decimal | int | float | str,
    weeks: int = 1,
    standard_weekly_hours: Decimal = STANDARD_WEEKLY_HOURS,
) -> Decimal:
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    fte = to_decimal(hours) / (standard_weekly_hours * weeks)
    return fte.quantize(FTE_QUANTUM, rounding=ROUND_HALF_UP)


def fte_to_hours(
    fte: Decimal | int | float | str,
    weeks: int = 1,
    standard_weekly_hours: Decimal = STANDARD_WEEKLY_HOURS,
) -> Decimal:
    return quantize_hours(to_decimal(fte) * standard_weekly_hours * weeks)
