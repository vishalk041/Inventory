"""
inventory.py
Backend logic for the Small Shop Inventory Tracker.

Core Python concepts used here:
  - classes and objects (InventoryManager, custom exception classes)
  - functions and modules (sqlite3, csv, io, datetime)
  - data structures (dict, list, tuple)
  - file handling (CSV import / export)
  - exception handling (custom errors, try/except/finally)
"""

import csv
import io
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "inventory.db")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class InventoryError(Exception):
    """Base class for all errors raised by this module."""


class ValidationError(InventoryError):
    """Raised when user input is missing or invalid."""


class InsufficientStockError(InventoryError):
    """Raised when we try to sell more items than are in stock."""


class NotFoundError(InventoryError):
    """Raised when a product does not exist."""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def now_text():
    """Current date and time as a readable string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_product_data(name, category, price, quantity, reorder_level):
    """
    Validate raw form values and return them as proper Python types.
    Raises ValidationError with a friendly message if something is wrong.
    """
    name = (name or "").strip()
    category = (category or "").strip() or "General"

    if not name:
        raise ValidationError("Product name cannot be empty.")
    if len(name) > 80:
        raise ValidationError("Product name is too long (max 80 characters).")

    try:
        price = float(price)
        quantity = int(quantity)
        reorder_level = int(reorder_level)
    except (TypeError, ValueError):
        raise ValidationError("Price, quantity and reorder level must be numbers.")

    if price < 0:
        raise ValidationError("Price cannot be negative.")
    if quantity < 0:
        raise ValidationError("Quantity cannot be negative.")
    if reorder_level < 0:
        raise ValidationError("Reorder level cannot be negative.")

    return name, category, round(price, 2), quantity, reorder_level


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class InventoryManager:
    """Handles every database operation for products and stock movements."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._create_tables()

    # ----- database setup -------------------------------------------------
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row          # rows behave like dictionaries
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_tables(self):
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL UNIQUE,
                    category      TEXT    NOT NULL DEFAULT 'General',
                    price         REAL    NOT NULL DEFAULT 0,
                    quantity      INTEGER NOT NULL DEFAULT 0,
                    reorder_level INTEGER NOT NULL DEFAULT 5,
                    created_at    TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    kind       TEXT    NOT NULL CHECK (kind IN ('IN', 'OUT')),
                    quantity   INTEGER NOT NULL,
                    note       TEXT,
                    created_at TEXT    NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                        ON DELETE CASCADE
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ----- products: create / read / update / delete ----------------------
    def add_product(self, name, category, price, quantity, reorder_level):
        name, category, price, quantity, reorder_level = clean_product_data(
            name, category, price, quantity, reorder_level
        )
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO products (name, category, price, quantity, "
                "reorder_level, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, category, price, quantity, reorder_level, now_text()),
            )
            product_id = cur.lastrowid
            if quantity > 0:   # record the opening stock in the history
                conn.execute(
                    "INSERT INTO transactions (product_id, kind, quantity, note, "
                    "created_at) VALUES (?, 'IN', ?, 'Opening stock', ?)",
                    (product_id, quantity, now_text()),
                )
            conn.commit()
            return product_id
        except sqlite3.IntegrityError:
            raise ValidationError(f"A product named '{name}' already exists.")
        finally:
            conn.close()

    def get_product(self, product_id):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise NotFoundError("That product does not exist.")
        return dict(row)

    def list_products(self, search="", category=""):
        """Return a list of product dicts, optionally filtered."""
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search.strip()}%")
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY name COLLATE NOCASE"

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def list_categories(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT category FROM products ORDER BY category"
            ).fetchall()
        finally:
            conn.close()
        return [r["category"] for r in rows]

    def update_product(self, product_id, name, category, price, reorder_level):
        """Edit product details. Quantity changes go through stock movements."""
        self.get_product(product_id)  # raises NotFoundError if missing
        # quantity is fixed at 0 here only to reuse the validator
        name, category, price, _, reorder_level = clean_product_data(
            name, category, price, 0, reorder_level
        )
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE products SET name=?, category=?, price=?, reorder_level=? "
                "WHERE id=?",
                (name, category, price, reorder_level, product_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValidationError(f"A product named '{name}' already exists.")
        finally:
            conn.close()

    def delete_product(self, product_id):
        self.get_product(product_id)
        conn = self._connect()
        try:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
        finally:
            conn.close()

    # ----- stock movements ------------------------------------------------
    def record_transaction(self, product_id, kind, quantity, note=""):
        """
        Add stock (kind='IN') or sell/remove stock (kind='OUT').
        Both the stock update and the history entry succeed together or
        not at all.
        """
        if kind not in ("IN", "OUT"):
            raise ValidationError("Transaction type must be IN or OUT.")
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValidationError("Quantity must be a whole number.")
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        product = self.get_product(product_id)
        if kind == "OUT" and quantity > product["quantity"]:
            raise InsufficientStockError(
                f"Only {product['quantity']} of '{product['name']}' in stock; "
                f"cannot remove {quantity}."
            )

        change = quantity if kind == "IN" else -quantity
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE products SET quantity = quantity + ? WHERE id = ?",
                (change, product_id),
            )
            conn.execute(
                "INSERT INTO transactions (product_id, kind, quantity, note, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (product_id, kind, quantity, (note or "").strip(), now_text()),
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise InventoryError("Database error while saving the transaction.")
        finally:
            conn.close()

    def list_transactions(self, limit=None, product_id=None):
        query = (
            "SELECT t.*, p.name AS product_name FROM transactions t "
            "JOIN products p ON p.id = t.product_id"
        )
        params = []
        if product_id:
            query += " WHERE t.product_id = ?"
            params.append(product_id)
        query += " ORDER BY t.id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ----- reports --------------------------------------------------------
    def low_stock_products(self):
        """Products whose quantity is at or below their reorder level."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM products WHERE quantity <= reorder_level "
                "ORDER BY quantity ASC, name"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def summary(self):
        """Numbers shown on the dashboard."""
        products = self.list_products()
        total_value = sum(p["price"] * p["quantity"] for p in products)
        out_of_stock = [p for p in products if p["quantity"] == 0]
        return {
            "total_products": len(products),
            "total_units": sum(p["quantity"] for p in products),
            "total_value": round(total_value, 2),
            "low_stock_count": len(self.low_stock_products()),
            "out_of_stock_count": len(out_of_stock),
            "categories": len({p["category"] for p in products}),   # a set
        }

    def stock_by_category(self):
        """Dictionary of {category: total units} used for the dashboard chart."""
        totals = {}
        for p in self.list_products():
            totals[p["category"]] = totals.get(p["category"], 0) + p["quantity"]
        return totals

    # ----- CSV import / export (file handling) ----------------------------
    CSV_COLUMNS = ["name", "category", "price", "quantity", "reorder_level"]

    def export_csv(self):
        """Return all products as CSV text."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self.CSV_COLUMNS)
        for p in self.list_products():
            writer.writerow([p[c] for c in self.CSV_COLUMNS])
        return buffer.getvalue()

    def import_csv(self, text):
        """
        Add products from CSV text. Returns (added_count, error_messages).
        Rows with problems are skipped and reported, not fatal.
        """
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or not set(self.CSV_COLUMNS) <= set(
            reader.fieldnames
        ):
            raise ValidationError(
                "CSV must have these columns: " + ", ".join(self.CSV_COLUMNS)
            )
        added, errors = 0, []
        for line_no, row in enumerate(reader, start=2):
            try:
                self.add_product(
                    row["name"],
                    row["category"],
                    row["price"],
                    row["quantity"],
                    row["reorder_level"],
                )
                added += 1
            except InventoryError as err:
                errors.append(f"Line {line_no}: {err}")
        return added, errors
