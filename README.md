# VEYRA - Business Inventory & Sales Management System

VEYRA is an offline, single-user Windows desktop application for a small Kenyan
shop: catalogue, stock ledger, point of sale, invoice history, reports and
backups. Everything is stored locally in a SQLite database - there is no server,
no login and no internet access.

All monetary values are Kenyan Shillings (KSh / KES). There is deliberately no
currency selector anywhere in the application.

## Requirements

- Windows 10/11
- Python 3.11 or newer (developed on 3.14)
- The four packages in `requirements.txt`

## Install and run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The first launch creates the database and the media/log/backup folders next to
the project (`veyra.db`, `media/`, `logs/`, `backups/`). Set the `VEYRA_HOME`
environment variable to keep the data somewhere else - the test suite uses this
to stay isolated.

## What is inside

| Section | Where | Notes |
| --- | --- | --- |
| Dashboard | `ui/pages/dashboard_page.py` | KPIs, 7-day sales chart, stock donut, low stock, top sellers, activity |
| Products | `ui/pages/products_page.py` | CRUD, images, archive-never-delete-with-history, Excel import |
| Inventory | `ui/pages/inventory_page.py` | Stock summary, movement ledger, stock in/out/adjustment |
| POS | `ui/pages/pos_page.py` | Product tiles, cart rules, KSh discount, VAT, complete sale |
| Sales | `ui/pages/sales_page.py` | Invoice history, immutable detail view, PDF receipt |
| Reports | `ui/pages/reports_page.py` | Six reports with CSV / Excel / PDF export |
| Settings | `ui/pages/settings_page.py` | Business profile, logo/avatar, theme, VAT, backup & restore |

Business rules live in `services/` (pricing in `services/pricing.py`), data
access in `repositories/`, and the schema in `models/`. The UI never writes to
the database directly.

### Money and VAT

- Line total = quantity x selling price (selling prices are VAT-exclusive).
- A sale-level discount is a fixed KSh amount, shared across lines pro-rata;
  VAT is charged per line on the amount after that line's discount share.
- Total = subtotal + VAT - discount. Every amount is rounded to 2 decimals.
- The VAT rate and each line's prices are snapshotted onto the sale, so editing
  a price or the VAT rate later never rewrites history.

### Safety rules

- A sale is one transaction: invoice, sale items, stock changes and ledger
  movements commit together or not at all.
- Sales are never deleted. Products with history are archived, not deleted.
- Excel imports validate every row first, show a preview, and never overwrite
  live stock or product images silently.
- Errors are shown as plain language. Unexpected failures produce a six-digit
  reference and the traceback goes to `logs/veyra.log` only.

## Backups

Settings -> Backup and Restore writes timestamped copies of the database into
`backups/`. Restoring takes an automatic safety copy of the current database
first, replaces the live file and reopens the connection; VEYRA then suggests a
restart so no stale connection survives.

## Tests

```bash
python -m pytest
```

The suite covers the pricing engine (including the blueprint's worked example),
Excel template/import validation, all report exporters, the atomic sale
transaction, VAT history, backup/restore, and an offscreen smoke test that
builds every page and prices a cart through the POS panel.

## Project layout

```
veyra/
|-- main.py               entry point: database, theme, shell, excepthook
|-- requirements.txt
|-- README.md
|-- core/                 config, constants, money, dates, paths, logging, errors
|-- db/                   engine, session_scope, schema creation
|-- models/               SQLAlchemy models (Category, Product, Sale, SaleItem, StockMovement, Settings)
|-- repositories/         queries only - never commit
|-- services/             business rules: products, inventory, pos, pricing, reports, settings, backups, images, imports
|-- imports/              Excel template + workbook validation
|-- reports/              CSV, Excel, PDF report and receipt writers
|-- ui/                   theme, main window, shared widgets, dialogs, pages
|-- tests/                pytest suite (isolated via VEYRA_HOME)
```
