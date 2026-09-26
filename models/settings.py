"""Single-row shop configuration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.config import (
    DEFAULT_BUSINESS_NAME,
    DEFAULT_FONT_SIZE,
    DEFAULT_THEME,
    DEFAULT_VAT_RATE,
)
from db.base import Base
from db.types import Rate


class Settings(Base):
    """One configuration row (always id == 1)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    business_name: Mapped[str] = mapped_column(
        String(150), nullable=False, default=DEFAULT_BUSINESS_NAME
    )
    owner_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    vat_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vat_rate: Mapped[object] = mapped_column(Rate, nullable=False, default=DEFAULT_VAT_RATE)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default=DEFAULT_THEME)
    font_size: Mapped[str] = mapped_column(
        String(10), nullable=False, default=DEFAULT_FONT_SIZE
    )
    logo_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    setup_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def effective_vat_rate(self):
        """The rate applied to new sales; zero when VAT is disabled."""
        from core.money import to_money

        return to_money(self.vat_rate) if self.vat_enabled else to_money(0)

    def __repr__(self) -> str:
        return f"<Settings {self.business_name!r} vat={self.vat_rate}>"
