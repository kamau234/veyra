"""Application-wide configuration constants.

VEYRA is KES-only: there is deliberately no currency selector anywhere in
Version 1, so the currency is a constant rather than a setting.
"""

APP_NAME = "VEYRA"
APP_SUBTITLE = "Business Inventory & Sales Management System"
APP_VERSION = "1.0.0"

CURRENCY_CODE = "KES"
CURRENCY_SYMBOL = "KSh"

DATABASE_FILENAME = "veyra.db"

DEFAULT_VAT_RATE = 16.00
DEFAULT_BUSINESS_NAME = "My Shop"

INVOICE_PREFIX = "INV"

FONT_SIZES = ("Small", "Normal", "Large")
DEFAULT_FONT_SIZE = "Normal"

THEMES = ("Light", "Dark", "System")
DEFAULT_THEME = "Light"

MAX_PRODUCT_IMAGE_PX = 300
