"""Shop configuration: business profile, VAT, appearance."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from core.config import DEFAULT_FONT_SIZE, DEFAULT_THEME, DEFAULT_VAT_RATE, FONT_SIZES, THEMES
from core.exceptions import ValidationError
from core.logger import get_logger
from core.money import format_rate, to_money
from db.session import session_scope
from models import Settings

logger = get_logger("services.settings")

MAX_EMAIL_LENGTH = 150


@dataclass(frozen=True)
class SettingsSnapshot:
    """Detached view of the configuration row, safe to hand to the UI."""

    business_name: str
    owner_name: str | None
    phone: str | None
    email: str | None
    address: str | None
    vat_enabled: bool
    vat_rate: Decimal
    theme: str
    font_size: str
    logo_image: str | None
    profile_image: str | None
    setup_complete: bool

    @property
    def effective_vat_rate(self) -> Decimal:
        return self.vat_rate if self.vat_enabled else to_money(0)

    @property
    def vat_label(self) -> str:
        return f"VAT ({format_rate(self.effective_vat_rate)}%)" if self.vat_enabled else "VAT (off)"


def _snapshot(settings: Settings) -> SettingsSnapshot:
    return SettingsSnapshot(
        business_name=settings.business_name,
        owner_name=settings.owner_name,
        phone=settings.phone,
        email=settings.email,
        address=settings.address,
        vat_enabled=bool(settings.vat_enabled),
        vat_rate=to_money(settings.vat_rate),
        theme=settings.theme or DEFAULT_THEME,
        font_size=settings.font_size or DEFAULT_FONT_SIZE,
        logo_image=settings.logo_image,
        profile_image=settings.profile_image,
        setup_complete=bool(settings.setup_complete),
    )


def _row(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def get_settings(session: Session | None = None) -> SettingsSnapshot:
    """Read configuration, using the caller's session when one is supplied."""
    if session is not None:
        return _snapshot(_row(session))
    with session_scope() as scope:
        return _snapshot(_row(scope))


def _clean_text(value, *, field: str, required: bool = False, limit: int = 300) -> str | None:
    text = " ".join(str(value or "").split())[:limit]
    if required and not text:
        raise ValidationError(f"{field} is required.", field=field.lower().replace(" ", "_"))
    return text or None


def update_business_profile(
    *,
    business_name: str,
    owner_name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    logo_image: str | None = None,
    profile_image: str | None = None,
) -> SettingsSnapshot:
    name = _clean_text(business_name, field="Business Name", required=True, limit=150)
    email_value = _clean_text(email, field="Email", limit=MAX_EMAIL_LENGTH)
    if email_value and "@" not in email_value:
        raise ValidationError("Enter a valid email address, or leave it blank.", field="email")

    with session_scope() as session:
        settings = _row(session)
        settings.business_name = name
        settings.owner_name = _clean_text(owner_name, field="Owner Name", limit=150)
        settings.phone = _clean_text(phone, field="Phone", limit=40)
        settings.email = email_value
        settings.address = _clean_text(address, field="Address")
        # ``None`` means "leave the stored image alone"; an empty string clears it.
        for field_name, value in (("logo_image", logo_image), ("profile_image", profile_image)):
            if value is not None:
                setattr(settings, field_name, str(value).strip() or None)
        settings.setup_complete = True
        session.flush()
        logger.info("Business profile updated (%s)", settings.business_name)
        return _snapshot(settings)


def update_tax_settings(*, vat_enabled: bool, vat_rate) -> SettingsSnapshot:
    """Change VAT for future sales; stored sales keep their own amounts."""
    rate = to_money(vat_rate)
    if rate < 0 or rate > 100:
        raise ValidationError("VAT rate must be between 0 and 100.", field="vat_rate")

    with session_scope() as session:
        settings = _row(session)
        settings.vat_enabled = bool(vat_enabled)
        settings.vat_rate = rate
        session.flush()
        logger.info("VAT settings updated: enabled=%s rate=%s", vat_enabled, rate)
        return _snapshot(settings)


def update_appearance(*, theme: str, font_size: str) -> SettingsSnapshot:
    theme_value = next((item for item in THEMES if item.lower() == str(theme).lower()), None)
    if theme_value is None:
        raise ValidationError("Choose Light, Dark or System.", field="theme")
    size_value = next(
        (item for item in FONT_SIZES if item.lower() == str(font_size).lower()), None
    )
    if size_value is None:
        raise ValidationError("Choose Small, Normal or Large.", field="font_size")

    with session_scope() as session:
        settings = _row(session)
        settings.theme = theme_value
        settings.font_size = size_value
        session.flush()
        logger.info("Appearance updated: theme=%s font=%s", theme_value, size_value)
        return _snapshot(settings)


def complete_setup() -> SettingsSnapshot:
    with session_scope() as session:
        settings = _row(session)
        settings.setup_complete = True
        session.flush()
        return _snapshot(settings)


def default_vat_rate() -> Decimal:
    return to_money(DEFAULT_VAT_RATE)
