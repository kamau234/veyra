"""SQLAlchemy models.

Importing this package registers every table on the shared declarative Base
so ``create_all`` sees the complete schema.
"""

from models.category import Category
from models.product import Product
from models.sale import Sale
from models.sale_item import SaleItem
from models.settings import Settings
from models.stock_movement import StockMovement

__all__ = [
    "Category",
    "Product",
    "Sale",
    "SaleItem",
    "Settings",
    "StockMovement",
]
