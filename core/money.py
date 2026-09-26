"""Money helpers.

All monetary values in VEYRA are ``Decimal`` quantized to 2 decimal places.
Values are stored in SQLite as integer minor units (see ``db/types.py``) so
KSh amounts never suffer binary floating point drift.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def to_money(value) -> Decimal:
    """Coerce a value to a 2dp Decimal, raising ValueError when impossible."""
    if isinstance(value, Decimal):
        amount = value
    elif value is None or value == "":
        amount = Decimal(0)
    elif isinstance(value, bool):
        raise ValueError("Expected an amount, got a boolean.")
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        amount = Decimal(repr(value))
    else:
        text = str(value).strip()
        for token in ("KSh", "KES", ",", " "):
            text = text.replace(token, "")
        if not text:
            amount = Decimal(0)
        else:
            try:
                amount = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError(f"'{text}' is not a valid amount.") from exc
    if not amount.is_finite():
        raise ValueError("Amount must be a finite number.")
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def parse_money(value) -> Decimal:
    """Parse user/sheet input to money, raising ValueError for bad input."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Amount is required.")
    return to_money(value)


def to_int(value, *, field: str = "Value") -> int:
    """Parse a whole-number quantity, rejecting negatives and fractions."""
    if value is None or value == "":
        raise ValueError(f"{field} is required.")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number.")
    if isinstance(value, float):
        if abs(value - round(value)) > 1e-9:
            raise ValueError(f"{field} must be a whole number.")
        number = int(round(value))
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError(f"{field} must be a whole number.")
        number = int(value)
    elif isinstance(value, int):
        number = value
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            raise ValueError(f"{field} is required.")
        try:
            number = int(text)
        except ValueError:
            try:
                decimal_value = Decimal(text)
            except InvalidOperation:
                raise ValueError(f"{field} must be a whole number.") from None
            if decimal_value != decimal_value.to_integral_value():
                raise ValueError(f"{field} must be a whole number.") from None
            number = int(decimal_value)
    if number < 0:
        raise ValueError(f"{field} cannot be negative.")
    return number


def round_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def format_money(value) -> str:
    """Format for display: 'KSh 2,784.00'."""
    from core.config import CURRENCY_SYMBOL

    return f"{CURRENCY_SYMBOL} {to_money(value):,.2f}"


def format_rate(value) -> str:
    """Percentage without trailing zeros: 16.00 -> '16', 16.50 -> '16.5'."""
    rate = to_money(value).normalize()
    if rate == rate.to_integral_value():
        return str(rate.quantize(Decimal(1)))
    return f"{rate:f}"


def format_number(value) -> str:
    return f"{to_int(value, field='Value'):,d}"
