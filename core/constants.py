"""Domain vocabularies shared by services, imports and the UI."""

from core.config import CURRENCY_CODE, CURRENCY_SYMBOL


class StockStatus:
    IN_STOCK = "In Stock"
    LOW_STOCK = "Low Stock"
    OUT_OF_STOCK = "Out of Stock"

    ALL = (IN_STOCK, LOW_STOCK, OUT_OF_STOCK)


class MovementType:
    STOCK_IN = "Stock In"
    STOCK_OUT = "Stock Out"
    ADJUSTMENT = "Adjustment"

    ALL = (STOCK_IN, STOCK_OUT, ADJUSTMENT)


class Direction:
    IN = "in"
    OUT = "out"

    ALL = (IN, OUT)


class Reason:
    RESTOCK = "Restock"
    INITIAL_STOCK = "Initial Stock"
    CUSTOMER_RETURN = "Customer Return"
    SALE = "Sale"
    DAMAGED = "Damaged"
    EXPIRED = "Expired"
    LOST = "Lost"
    DISPOSAL = "Disposal"
    INTERNAL_USE = "Internal Use"
    CORRECTION = "Correction"
    OTHER = "Other"

    ALL = (
        RESTOCK,
        INITIAL_STOCK,
        CUSTOMER_RETURN,
        SALE,
        DAMAGED,
        EXPIRED,
        LOST,
        DISPOSAL,
        INTERNAL_USE,
        CORRECTION,
        OTHER,
    )


#: Reason -> the movement type it normally belongs to. Used to keep the
#: Stock Movement dialog's reason dropdown honest about direction.
REASONS_BY_TYPE = {
    MovementType.STOCK_IN: (
        Reason.RESTOCK,
        Reason.INITIAL_STOCK,
        Reason.CUSTOMER_RETURN,
        Reason.OTHER,
    ),
    MovementType.STOCK_OUT: (
        Reason.SALE,
        Reason.DAMAGED,
        Reason.EXPIRED,
        Reason.LOST,
        Reason.DISPOSAL,
        Reason.INTERNAL_USE,
        Reason.CORRECTION,
        Reason.OTHER,
    ),
    MovementType.ADJUSTMENT: (Reason.CORRECTION, Reason.OTHER),
}

#: Movement types whose ledger direction is fixed. Adjustments carry an
#: explicit direction chosen by the user.
DIRECTION_BY_TYPE = {
    MovementType.STOCK_IN: Direction.IN,
    MovementType.STOCK_OUT: Direction.OUT,
}

UNITS = ("Piece", "Pack", "Box", "Kg", "Litre", "Dozen", "Carton", "Bottle", "Bag")

#: Reasons that must always carry an explanatory note.
NOTES_REQUIRED_REASONS = (Reason.CORRECTION,)

#: Report period keys offered by every date filter in the application.
class Period:
    TODAY = "Today"
    YESTERDAY = "Yesterday"
    THIS_WEEK = "This Week"
    THIS_MONTH = "This Month"
    LAST_7_DAYS = "Last 7 Days"
    LAST_30_DAYS = "Last 30 Days"
    CUSTOM = "Custom Range"

    ALL = (TODAY, YESTERDAY, THIS_WEEK, THIS_MONTH, LAST_7_DAYS, LAST_30_DAYS, CUSTOM)


SORT_OPTIONS = (
    "Name (A-Z)",
    "Name (Z-A)",
    "Stock (Low-High)",
    "Stock (High-Low)",
    "Code (A-Z)",
    "Newest first",
)


def money(amount) -> str:
    """Format a number as KSh with thousands separators and 2 decimals."""
    from decimal import Decimal, ROUND_HALF_UP

    value = Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{CURRENCY_SYMBOL} {value:,.2f}"


def money_short(amount) -> str:
    return money(amount).replace(".00", "")


__all__ = [
    "CURRENCY_CODE",
    "CURRENCY_SYMBOL",
    "StockStatus",
    "MovementType",
    "Direction",
    "Reason",
    "REASONS_BY_TYPE",
    "DIRECTION_BY_TYPE",
    "NOTES_REQUIRED_REASONS",
    "UNITS",
    "Period",
    "SORT_OPTIONS",
    "money",
    "money_short",
]
