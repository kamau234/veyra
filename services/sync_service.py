"""Optional cloud sync: mirror the shop into a Supabase table and restore it.

VEYRA stays offline-first - the local SQLite database remains the source of
truth and every feature works with no network at all. This module adds a
durability layer: a single JSON snapshot (catalogue, stock ledger, sales
ledger, business profile and its images) is upserted into one row of
``public.veyra_sync`` keyed by an unguessable shop id, so a reinstall or a new
computer starts with yesterday's data instead of an empty shop.

Failures never masquerade as success (blueprint 16): a failed push leaves the
previous state untouched and reports exactly what happened.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, func, select

from core.cloud_config import SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL
from core.exceptions import ValidationError, VeyraError
from core.logger import get_logger
from core.money import to_money
from core.paths import (
    DATA_HOME,
    LOGO_IMAGE_DIR,
    MEDIA_DIR,
    PRODUCT_IMAGE_DIR,
    PROFILE_IMAGE_DIR,
    resolve_image_path,
)
from db.session import register_commit_hook, session_scope
from models import Category, Product, Sale, SaleItem, Settings, StockMovement

logger = get_logger("services.sync")

SCHEMA_VERSION = 1
TABLE = "veyra_sync"
TIMEOUT_SECONDS = 25

#: Images larger than this are listed in the snapshot but not embedded.
IMAGE_BYTE_LIMIT = 350 * 1024
IMAGE_DIRS = {"products": PRODUCT_IMAGE_DIR, "profile": PROFILE_IMAGE_DIR, "logos": LOGO_IMAGE_DIR}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

SYNC_ID_FILE = DATA_HOME / "sync_id.txt"
STATE_FILE = DATA_HOME / "sync_state.json"

SCHEMA_HINT = (
    "The cloud table does not exist yet. Open the Supabase SQL editor once and "
    "run the script at cloud/schema.sql, then sync again."
)

_lock = threading.Lock()
_dirty = False


class SyncError(VeyraError):
    """A cloud sync attempt failed; the local database is untouched."""

    default_message = "Cloud sync did not complete."


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    message: str
    mode: str = "push"
    products: int = 0
    sales: int = 0
    movements: int = 0
    skipped_images: tuple[str, ...] = field(default_factory=tuple)
    at: str = ""


@dataclass(frozen=True)
class SyncState:
    last_at: str | None = None
    ok: bool = False
    message: str = "Never synced."
    mode: str = ""
    auto_sync: bool = True


# --------------------------------------------------------------------- config


def configured() -> bool:
    return bool(SUPABASE_URL.strip()) and bool(SUPABASE_PUBLISHABLE_KEY.strip())


def shop_id() -> str:
    """Stable, unguessable id for this installation (also the RLS scope)."""
    try:
        existing = SYNC_ID_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = uuid.uuid4().hex
    _write_shop_id(fresh)
    return fresh


def set_shop_id(value: str) -> str:
    """Point this installation at an existing cloud copy (new computer)."""
    clean = (value or "").strip()
    if not clean or len(clean) < 8 or len(clean) > 64 or not clean.isalnum():
        raise ValidationError(
            "A Sync ID is 8-64 letters or digits. Copy it from Settings on the "
            "computer that holds your data.",
            field="sync_id",
        )
    _write_shop_id(clean)
    return clean


def _write_shop_id(value: str) -> None:
    try:
        DATA_HOME.mkdir(parents=True, exist_ok=True)
        SYNC_ID_FILE.write_text(value, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist the sync id: %s", exc)


def mark_dirty() -> None:
    global _dirty
    with _lock:
        _dirty = True


def consume_dirty() -> bool:
    global _dirty
    with _lock:
        was, _dirty = _dirty, False
    return was


# Any committed change anywhere in the app makes the cloud copy stale.
register_commit_hook(mark_dirty)


def load_state() -> SyncState:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SyncState()
    return SyncState(
        last_at=raw.get("last_at"),
        ok=bool(raw.get("ok")),
        message=raw.get("message") or "Never synced.",
        mode=raw.get("mode") or "",
        auto_sync=bool(raw.get("auto_sync", True)),
    )


def auto_sync_enabled() -> bool:
    return load_state().auto_sync


def set_auto_sync(enabled: bool) -> None:
    state = load_state()
    _save_state(
        SyncState(
            last_at=state.last_at,
            ok=state.ok,
            message=state.message,
            mode=state.mode,
            auto_sync=bool(enabled),
        )
    )


def _save_state(state: SyncState) -> None:
    try:
        STATE_FILE.write_text(
            json.dumps(
                {
                    "last_at": state.last_at,
                    "ok": state.ok,
                    "message": state.message,
                    "mode": state.mode,
                    "auto_sync": state.auto_sync,
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not persist the sync state: %s", exc)


def _record(result: SyncResult) -> SyncResult:
    state = load_state()
    _save_state(
        SyncState(
            last_at=result.at,
            ok=result.ok,
            message=result.message,
            mode=result.mode,
            auto_sync=state.auto_sync,
        )
    )
    return result


def record(result: SyncResult) -> SyncResult:
    """Persist a result produced outside this module (e.g. the UI worker)."""
    if not result.at:
        result = SyncResult(
            ok=result.ok,
            message=result.message,
            mode=result.mode,
            products=result.products,
            sales=result.sales,
            movements=result.movements,
            skipped_images=result.skipped_images,
            at=_stamp(datetime.now()),
        )
    return _record(result)


# ------------------------------------------------------------------ transport


def _request(method: str, path: str, *, body: dict | None = None, params: str = "") -> object:
    if not configured():
        raise SyncError("Cloud sync is not configured on this build.")
    url = f"{SUPABASE_URL.rstrip('/')}{path}{params}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("apikey", SUPABASE_PUBLISHABLE_KEY)
    request.add_header("Authorization", f"Bearer {SUPABASE_PUBLISHABLE_KEY}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if "PGRST205" in detail:
            raise SyncError(SCHEMA_HINT) from exc
        logger.error("Cloud sync HTTP %s: %s", exc.code, detail)
        raise SyncError(
            f"The cloud service refused the request (HTTP {exc.code}). Nothing was changed."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Cloud sync unreachable: %s", exc)
        raise SyncError(
            "VEYRA could not reach the cloud service. Your local data is safe; "
            "sync again once you are online."
        ) from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


# ------------------------------------------------------------------- snapshot


def _money(value) -> str:
    return str(to_money(value))


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _image_block(stored: str | None) -> dict | None:
    path = resolve_image_path(stored)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > IMAGE_BYTE_LIMIT:
        return {"stored": stored, "too_large": True}
    return {
        "stored": stored,
        "b64": base64.b64encode(data).decode("ascii"),
    }


def build_payload() -> dict:
    """Serialize the whole shop into a JSON-safe dictionary."""
    with session_scope() as session:
        settings = session.get(Settings, 1)
        categories = list(session.scalars(select(Category).order_by(Category.id)))
        products = list(session.scalars(select(Product).order_by(Product.id)))
        movements = list(session.scalars(select(StockMovement).order_by(StockMovement.id)))
        sales = list(session.scalars(select(Sale).order_by(Sale.id)))
        codes = {product.id: product.code for product in products}
        invoices = {sale.id: sale.invoice_number for sale in sales}
        skipped: list[str] = []

        product_entries = []
        for product in products:
            image = _image_block(product.image_path)
            if image and image.get("too_large"):
                skipped.append(product.code)
            product_entries.append(
                {
                    "code": product.code,
                    "name": product.name,
                    "category": product.category.name if product.category else None,
                    "subcategory": product.subcategory,
                    "brand": product.brand,
                    "unit": product.unit,
                    "cost_price": _money(product.cost_price),
                    "selling_price": _money(product.selling_price),
                    "stock_quantity": product.stock_quantity,
                    "reorder_level": product.reorder_level,
                    "vat_applicable": bool(product.vat_applicable),
                    "is_active": bool(product.is_active),
                    "image": image,
                    "created_at": _stamp(product.created_at),
                }
            )

        movement_entries = [
            {
                "product_code": codes.get(movement.product_id),
                "sale_invoice": invoices.get(movement.sale_id),
                "movement_type": movement.movement_type,
                "direction": movement.direction,
                "quantity": movement.quantity,
                "reason": movement.reason,
                "reference": movement.reference,
                "notes": movement.notes,
                "balance_after": movement.balance_after,
                "created_at": _stamp(movement.created_at),
            }
            for movement in movements
        ]

        sale_entries = []
        for sale in sales:
            sale_entries.append(
                {
                    "invoice_number": sale.invoice_number,
                    "sale_date": _stamp(sale.sale_date),
                    "subtotal": _money(sale.subtotal),
                    "vat_amount": _money(sale.vat_amount),
                    "discount": _money(sale.discount),
                    "total": _money(sale.total),
                    "vat_rate_snapshot": _money(sale.vat_rate_snapshot),
                    "item_count": sale.item_count,
                    "note": sale.note,
                    "items": [
                        {
                            "product_code": item.product_code_snapshot,
                            "product_id_code": codes.get(item.product_id),
                            "name": item.product_name_snapshot,
                            "unit": item.unit_snapshot,
                            "quantity": item.quantity,
                            "unit_price": _money(item.unit_price),
                            "cost_price": _money(item.cost_price_snapshot),
                            "vat_applicable": bool(item.vat_applicable),
                            "vat_amount": _money(item.vat_amount),
                            "discount_allocated": _money(item.discount_allocated),
                            "line_total": _money(item.line_total),
                        }
                        for item in sale.items
                    ],
                }
            )

        settings_entry = None
        if settings is not None:
            logo_block = _image_block(settings.logo_image)
            profile_block = _image_block(settings.profile_image)
            for block in (logo_block, profile_block):
                if block and block.get("too_large"):
                    skipped.append("business image")
            settings_entry = {
                "business_name": settings.business_name,
                "owner_name": settings.owner_name,
                "phone": settings.phone,
                "email": settings.email,
                "address": settings.address,
                "vat_enabled": bool(settings.vat_enabled),
                "vat_rate": _money(settings.vat_rate),
                "theme": settings.theme,
                "font_size": settings.font_size,
                "logo_image": logo_block,
                "profile_image": profile_block,
                "setup_complete": bool(settings.setup_complete),
            }

    return {
        "app": "VEYRA",
        "schema": SCHEMA_VERSION,
        "generated_at": _stamp(datetime.now()),
        "shop_id": shop_id(),
        "settings": settings_entry,
        "categories": [category.name for category in categories],
        "products": product_entries,
        "movements": movement_entries,
        "sales": sale_entries,
        "skipped_images": skipped,
    }


# ---------------------------------------------------------------------- push


def push() -> SyncResult:
    """Upload the current snapshot; never touches local data."""
    payload = build_payload()
    row = {
        "shop_id": shop_id(),
        "schema_version": SCHEMA_VERSION,
        "payload": payload,
        "updated_by": socket.gethostname(),
        "updated_at": datetime.now().isoformat(),
    }
    _request("POST", f"/rest/v1/{TABLE}", body=row)
    result = SyncResult(
        ok=True,
        mode="push",
        message=(
            f"Cloud copy updated: {len(payload['products'])} products, "
            f"{len(payload['sales'])} sales."
        ),
        products=len(payload["products"]),
        sales=len(payload["sales"]),
        movements=len(payload["movements"]),
        skipped_images=tuple(payload["skipped_images"]),
        at=_stamp(datetime.now()),
    )
    logger.info("Cloud push succeeded (%s products, %s sales)", result.products, result.sales)
    return _record(result)


def fetch_payload() -> dict | None:
    """Download the stored snapshot, or None when the cloud has nothing yet."""
    raw = _request(
        "GET",
        f"/rest/v1/{TABLE}",
        params=f"?shop_id=eq.{shop_id()}&select=payload,schema_version",
    )
    rows = raw or []
    if not rows:
        return None
    payload = rows[0].get("payload")
    if not isinstance(payload, dict):
        raise SyncError("The cloud copy could not be read. Sync again or contact support.")
    return payload


def probe() -> SyncResult:
    """Cheap connectivity + schema check used by the Settings card."""
    try:
        payload = fetch_payload()
    except SyncError as error:
        return _record(
            SyncResult(ok=False, mode="probe", message=error.message, at=_stamp(datetime.now()))
        )
    if payload is None:
        message = "Connected. No cloud copy yet - use Sync Now to create one."
    else:
        when = payload.get("generated_at") or "unknown time"
        message = f"Connected. Cloud copy from {when}."
    return _record(
        SyncResult(
            ok=True,
            mode="probe",
            message=message,
            products=len(payload.get("products", [])) if payload else 0,
            sales=len(payload.get("sales", [])) if payload else 0,
            at=_stamp(datetime.now()),
        )
    )


# -------------------------------------------------------------------- restore


def _write_image(image: dict | None) -> str | None:
    if not image or not image.get("b64"):
        return None
    stored = str(image.get("stored") or "")
    parts = PurePosixPath(stored.replace("\\", "/"))
    kind = parts.parts[0] if len(parts.parts) > 1 else "products"
    directory = IMAGE_DIRS.get(kind)
    suffix = parts.suffix.lower()
    if directory is None or suffix not in IMAGE_SUFFIXES:
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"restored-{uuid.uuid4().hex[:12]}{suffix}"
        target.write_bytes(base64.b64decode(image["b64"]))
    except (OSError, ValueError) as exc:
        logger.warning("Could not restore image %s: %s", stored, exc)
        return None
    return str(target.relative_to(MEDIA_DIR)).replace("\\", "/")


def restore_payload(payload: dict, *, allow_overwrite: bool = False) -> SyncResult:
    """Replace local data with a cloud snapshot, atomically."""
    if not isinstance(payload, dict) or payload.get("app") != "VEYRA":
        raise SyncError("That cloud copy was not produced by VEYRA.")
    if int(payload.get("schema", 0)) > SCHEMA_VERSION:
        raise SyncError(
            "The cloud copy was written by a newer VEYRA. Update the application first."
        )

    with session_scope() as session:
        products_now = session.scalar(select(func.count()).select_from(Product)) or 0
        sales_now = session.scalar(select(func.count()).select_from(Sale)) or 0
        if (products_now or sales_now) and not allow_overwrite:
            raise ValidationError(
                "This computer already holds products or sales. Tick 'Replace the data "
                "on this computer' to restore over them; a safety backup is taken first."
            )
        if allow_overwrite:
            session.execute(delete(SaleItem))
            session.execute(delete(StockMovement))
            session.execute(delete(Sale))
            session.execute(delete(Product))
            session.execute(delete(Category))
            session.flush()

        category_ids: dict[str, int] = {}
        for name in payload.get("categories", []):
            category = Category(name=name)
            session.add(category)
            session.flush()
            category_ids[name] = category.id

        product_ids: dict[str, int] = {}
        for entry in payload.get("products", []):
            category_name = entry.get("category")
            product = Product(
                code=entry["code"],
                name=entry["name"],
                category_id=category_ids.get(category_name)
                if category_name in category_ids
                else None,
                subcategory=entry.get("subcategory"),
                brand=entry.get("brand"),
                unit=entry.get("unit") or "Piece",
                cost_price=to_money(entry.get("cost_price", 0)),
                selling_price=to_money(entry.get("selling_price", 0)),
                stock_quantity=int(entry.get("stock_quantity", 0)),
                reorder_level=int(entry.get("reorder_level", 0)),
                vat_applicable=bool(entry.get("vat_applicable", True)),
                is_active=bool(entry.get("is_active", True)),
                image_path=_write_image(entry.get("image")),
            )
            session.add(product)
            session.flush()
            product_ids[product.code] = product.id

        sale_ids: dict[str, int] = {}
        for entry in payload.get("sales", []):
            sale = Sale(
                invoice_number=entry["invoice_number"],
                sale_date=_parse_stamp(entry.get("sale_date")) or datetime.now(),
                subtotal=to_money(entry.get("subtotal", 0)),
                vat_amount=to_money(entry.get("vat_amount", 0)),
                discount=to_money(entry.get("discount", 0)),
                total=to_money(entry.get("total", 0)),
                vat_rate_snapshot=to_money(entry.get("vat_rate_snapshot", 0)),
                item_count=int(entry.get("item_count", 0)),
                note=entry.get("note"),
            )
            session.add(sale)
            session.flush()
            sale_ids[sale.invoice_number] = sale.id
            for item in entry.get("items", []):
                product_id = product_ids.get(item.get("product_id_code") or item.get("product_code"))
                if product_id is None:
                    raise SyncError(
                        f"The cloud copy references product {item.get('product_code')} "
                        "which is missing from its own catalogue."
                    )
                session.add(
                    SaleItem(
                        sale_id=sale.id,
                        product_id=product_id,
                        product_code_snapshot=item.get("product_code") or "",
                        product_name_snapshot=item.get("name") or "",
                        unit_snapshot=item.get("unit") or "Piece",
                        quantity=int(item.get("quantity", 0)),
                        unit_price=to_money(item.get("unit_price", 0)),
                        cost_price_snapshot=to_money(item.get("cost_price", 0)),
                        vat_applicable=bool(item.get("vat_applicable", True)),
                        vat_amount=to_money(item.get("vat_amount", 0)),
                        discount_allocated=to_money(item.get("discount_allocated", 0)),
                        line_total=to_money(item.get("line_total", 0)),
                    )
                )

        for entry in payload.get("movements", []):
            product_id = product_ids.get(entry.get("product_code") or "")
            if product_id is None:
                continue
            session.add(
                StockMovement(
                    product_id=product_id,
                    sale_id=sale_ids.get(entry.get("sale_invoice") or "", None),
                    movement_type=entry.get("movement_type") or "Adjustment",
                    direction=entry.get("direction") or "in",
                    quantity=int(entry.get("quantity", 0)),
                    reason=entry.get("reason") or "Restored",
                    reference=entry.get("reference"),
                    notes=entry.get("notes"),
                    balance_after=int(entry.get("balance_after", 0)),
                    created_at=_parse_stamp(entry.get("created_at")) or datetime.now(),
                )
            )

        settings_entry = payload.get("settings")
        if settings_entry:
            settings = session.get(Settings, 1)
            if settings is None:
                settings = Settings(id=1)
                session.add(settings)
            settings.business_name = settings_entry.get("business_name") or settings.business_name
            settings.owner_name = settings_entry.get("owner_name")
            settings.phone = settings_entry.get("phone")
            settings.email = settings_entry.get("email")
            settings.address = settings_entry.get("address")
            if "vat_enabled" in settings_entry:
                settings.vat_enabled = bool(settings_entry["vat_enabled"])
            if settings_entry.get("vat_rate") is not None:
                settings.vat_rate = to_money(settings_entry["vat_rate"])
            settings.theme = settings_entry.get("theme") or settings.theme
            settings.font_size = settings_entry.get("font_size") or settings.font_size
            settings.logo_image = _write_image(settings_entry.get("logo_image"))
            settings.profile_image = _write_image(settings_entry.get("profile_image"))
            settings.setup_complete = True
            session.flush()

        counts = (
            len(payload.get("products", [])),
            len(payload.get("sales", [])),
            len(payload.get("movements", [])),
        )

    result = SyncResult(
        ok=True,
        mode="pull",
        message=f"Restored {counts[0]} products and {counts[1]} sales from the cloud.",
        products=counts[0],
        sales=counts[1],
        movements=counts[2],
        at=_stamp(datetime.now()),
    )
    logger.info("Cloud restore succeeded (%s products, %s sales)", counts[0], counts[1])
    return _record(result)


def pull_and_restore(*, allow_overwrite: bool = False) -> SyncResult:
    payload = fetch_payload()
    if payload is None:
        return _record(
            SyncResult(
                ok=False,
                mode="pull",
                message="The cloud has no copy for this shop yet. Use Sync Now first.",
                at=_stamp(datetime.now()),
            )
        )
    return restore_payload(payload, allow_overwrite=allow_overwrite)
