"""Custom column types."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import types

from core.money import CENTS, to_money


class Money(types.TypeDecorator):
    """Exact KSh amounts.

    SQLite has no decimal type and the pysqlite driver cannot return
    ``Decimal`` natively, so money is persisted as integer minor units
    (cents) and rehydrated as a 2dp ``Decimal``. This keeps every
    calculation in the application free of binary floating point error.
    """

    impl = types.BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int((to_money(value) * 100).to_integral_value())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(CENTS)


class Rate(types.TypeDecorator):
    """A percentage rate such as the VAT rate, stored as integer hundredths.

    ``16.00`` is persisted as ``1600`` so the configured rate survives a
    write/read cycle exactly.
    """

    impl = types.Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int((to_money(value) * 100).to_integral_value())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(CENTS)
