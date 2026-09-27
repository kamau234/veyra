"""Offscreen UI smoke tests: the shell and every page must build and refresh.

These tests never assert pixel output; they prove the pages wire up against the
real services without raising, and that the POS panel shows the same totals the
pricing engine produces (blueprint 20.3: no tracebacks, no false success).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.money import format_money
from services import pos_service, product_service, settings_service
from services.pos_service import Cart

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import main as entry  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def window(qapp):
    window = entry.build_window()
    qapp.processEvents()
    yield window
    qapp.processEvents()


def test_every_page_builds_and_refreshes(window, qapp, sample_products):
    for key in ("dashboard", "products", "inventory", "pos", "sales", "reports", "settings"):
        window.show_page(key)
        qapp.processEvents()
        assert window.current_page() == key
        window.page(key).refresh()
        qapp.processEvents()


def test_pos_panel_prices_the_cart_like_the_engine(window, qapp, sample_products):
    window.show_page("pos")
    qapp.processEvents()
    page = window.page("pos")

    tile = page._grid_widgets[0]
    tile.clicked.emit(tile.product)
    page.cart.set_discount(Decimal("50.00"))
    page._refresh_cart()
    qapp.processEvents()

    expected = Cart()
    expected.add(tile.product, 1)
    expected.set_discount(Decimal("50.00"))
    priced = expected.price(vat_rate=Decimal("16"), vat_enabled=True)

    assert page.total_row.value_widget.text() == format_money(priced.total)
    assert page.subtotal_row.value_widget.text() == format_money(priced.subtotal)
    assert page.table.rowCount() == 1
    assert page.complete_button.isEnabled()


def test_pos_complete_sale_refreshes_stock_and_notifies(window, qapp, sample_products):
    window.show_page("pos")
    qapp.processEvents()
    page = window.page("pos")
    before = product_service.find_by_code("DET001").stock_quantity

    cart = page.cart
    cart.add(product_service.find_by_code("DET001"), 2)
    page._refresh_cart()
    result = pos_service.complete_sale(cart, note="ui smoke")
    page.refresh()
    qapp.processEvents()

    assert result.invoice_number == "INV-00001"
    assert product_service.find_by_code("DET001").stock_quantity == before - 2
    assert page.table.rowCount() == 0
    assert not page.complete_button.isEnabled()


def test_products_page_lists_and_filters(window, qapp, sample_products):
    window.show_page("products")
    qapp.processEvents()
    page = window.page("products")
    assert page.table.rowCount() == 3

    page.search.setText("hammer")
    qapp.processEvents()
    assert page.table.rowCount() == 1
    assert page.table.cell_text(0, 2) == "Hammer"

    page.focus_product(sample_products[0].id)
    qapp.processEvents()
    assert page.table.cell_text(0, 1) == "DET001"


def test_reports_page_runs_and_exports(window, qapp, sample_products, tmp_path):
    cart = Cart()
    cart.add(product_service.find_by_code("DET001"), 2)
    pos_service.complete_sale(cart)

    window.show_page("reports")
    qapp.processEvents()
    page = window.page("reports")

    names = []
    for row in range(page.report_list.count()):
        page.report_list.setCurrentRow(row)
        qapp.processEvents()
        names.append(page.result_title.text())
        assert page.table.rowCount() >= 1

    assert names == [
        "Sales Report",
        "Product Sales Report",
        "Inventory Report",
        "Stock Movement Report",
        "Low Stock Report",
        "Estimated Gross Profit Report",
    ]

    from reports.csv_exporter import export_csv

    page.report_list.setCurrentRow(0)
    qapp.processEvents()
    destination = tmp_path / "sales.csv"
    written = export_csv(
        page.report, destination, business_name=settings_service.get_settings().business_name
    )
    text = written.read_text(encoding="utf-8-sig")
    assert "Currency: KES (KSh)" in text
    assert "Sales Report" in text


def test_settings_page_saves_appearance_and_vat(window, qapp):
    window.show_page("settings")
    qapp.processEvents()
    page = window.page("settings")

    page.vat_enabled.setChecked(False)
    page.save_tax()
    qapp.processEvents()
    assert settings_service.get_settings().vat_enabled is False

    page.font_size.setCurrentText("Large")
    page.save_appearance()
    qapp.processEvents()
    assert settings_service.get_settings().font_size == "Large"
    assert window.settings.font_size == "Large"


def test_dark_theme_is_applied_and_remembered(window, qapp):
    from ui import theme as theme_module

    assert theme_module.resolve_theme("Dark") is theme_module.DARK
    assert theme_module.resolve_theme("dark") is theme_module.DARK
    assert theme_module.resolve_theme(None) is theme_module.LIGHT

    window.show_page("settings")
    qapp.processEvents()
    page = window.page("settings")
    dark_radio = next(b for b in page.theme_group.buttons() if b.text() == "Dark")
    dark_radio.click()
    page.save_appearance()
    qapp.processEvents()

    assert settings_service.get_settings().theme == "Dark"
    assert qapp.veyra_theme is theme_module.DARK

    window.show_page("dashboard")
    window.show_page("settings")
    qapp.processEvents()
    assert window.page("settings")._selected_theme() == "Dark"
    assert qapp.veyra_theme is theme_module.DARK


def test_sales_page_shows_invoices_and_opens_detail(window, qapp, sample_products):
    cart = Cart()
    cart.add(product_service.find_by_code("DET001"), 2)
    pos_service.complete_sale(cart, note="smoke note")

    window.show_page("sales")
    qapp.processEvents()
    page = window.page("sales")
    assert page.table.rowCount() == 1
    assert page.table.cell_text(0, 0) == "INV-00001"

    page.table.selectRow(0)
    sale = page.selected_sale()
    assert sale.note == "smoke note"
    assert sale.total == Decimal("812.00")
