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
from datetime import datetime, timedelta, date

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


def clean_product_data(name, category, price, quantity, reorder_level, cost_price=None, expiry_date=None):
    """
    Validate raw form values and return them as proper Python types.
    Raises ValidationError with a friendly message if something is wrong.
    Supports selling rate (price), buying rate (cost_price), and optional expiry_date.
    """
    name = (name or "").strip()
    category = (category or "").strip() or "General"
    expiry_date = (expiry_date or "").strip()

    if not name:
        raise ValidationError("Product name cannot be empty.")
    if len(name) > 80:
        raise ValidationError("Product name is too long (max 80 characters).")

    try:
        price = float(price)
        quantity = int(quantity)
        reorder_level = int(reorder_level)
        if cost_price is None or str(cost_price).strip() == "":
            cost_price = round(price * 0.75, 2) if price > 0 else 0.0
        else:
            cost_price = float(cost_price)
    except (TypeError, ValueError):
        raise ValidationError("Price, buying rate, quantity and reorder level must be numbers.")

    if price < 0:
        raise ValidationError("Selling price cannot be negative.")
    if cost_price < 0:
        raise ValidationError("Buying rate (cost price) cannot be negative.")
    if quantity < 0:
        raise ValidationError("Quantity cannot be negative.")
    if reorder_level < 0:
        raise ValidationError("Reorder level cannot be negative.")

    # Validate expiry date format if provided
    if expiry_date:
        try:
            datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            raise ValidationError("Expiry date must be in YYYY-MM-DD format.")

    return name, category, round(price, 2), quantity, reorder_level, round(cost_price, 2), expiry_date


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class InventoryManager:
    """Handles every database operation for products, stock movements, invoices, and analytics."""

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
                    cost_price    REAL    NOT NULL DEFAULT 0,
                    quantity      INTEGER NOT NULL DEFAULT 0,
                    reorder_level INTEGER NOT NULL DEFAULT 5,
                    expiry_date   TEXT    DEFAULT '',
                    created_at    TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id   INTEGER NOT NULL,
                    kind         TEXT    NOT NULL CHECK (kind IN ('IN', 'OUT')),
                    quantity     INTEGER NOT NULL,
                    unit_price   REAL    NOT NULL DEFAULT 0,
                    cost_price   REAL    NOT NULL DEFAULT 0,
                    total_amount REAL    NOT NULL DEFAULT 0,
                    reason       TEXT    DEFAULT 'SALE',
                    is_loss      INTEGER DEFAULT 0,
                    note         TEXT,
                    created_at   TEXT    NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS invoices (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_no     TEXT    NOT NULL UNIQUE,
                    customer_name  TEXT    NOT NULL DEFAULT 'Walk-in Customer',
                    customer_phone TEXT    DEFAULT '',
                    subtotal       REAL    NOT NULL DEFAULT 0,
                    discount       REAL    NOT NULL DEFAULT 0,
                    tax            REAL    NOT NULL DEFAULT 0,
                    total_amount   REAL    NOT NULL DEFAULT 0,
                    payment_method TEXT    NOT NULL DEFAULT 'Cash',
                    note           TEXT    DEFAULT '',
                    created_at     TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS invoice_items (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id   INTEGER NOT NULL,
                    product_id   INTEGER NOT NULL,
                    product_name TEXT    NOT NULL,
                    quantity     INTEGER NOT NULL,
                    unit_price   REAL    NOT NULL DEFAULT 0,
                    cost_price   REAL    NOT NULL DEFAULT 0,
                    total_price  REAL    NOT NULL DEFAULT 0,
                    profit       REAL    NOT NULL DEFAULT 0,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                );
                """
            )
            conn.commit()
            self._migrate_tables(conn)
        finally:
            conn.close()

    def _migrate_tables(self, conn):
        """Ensure backward compatibility by safely adding any missing columns or tables."""
        # 1. Products table
        p_cols = [c["name"] for c in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "cost_price" not in p_cols:
            conn.execute("ALTER TABLE products ADD COLUMN cost_price REAL NOT NULL DEFAULT 0")
            conn.execute("UPDATE products SET cost_price = ROUND(price * 0.75, 2) WHERE cost_price = 0 OR cost_price IS NULL")
        if "expiry_date" not in p_cols:
            conn.execute("ALTER TABLE products ADD COLUMN expiry_date TEXT DEFAULT ''")

        # 2. Transactions table
        t_cols = [c["name"] for c in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        if "unit_price" not in t_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN unit_price REAL NOT NULL DEFAULT 0")
        if "cost_price" not in t_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN cost_price REAL NOT NULL DEFAULT 0")
        if "total_amount" not in t_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN total_amount REAL NOT NULL DEFAULT 0")
        if "reason" not in t_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN reason TEXT DEFAULT 'SALE'")
        if "is_loss" not in t_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN is_loss INTEGER DEFAULT 0")

        # Backfill existing transactions if unit_price is 0
        conn.execute("""
            UPDATE transactions
            SET unit_price = COALESCE((SELECT cost_price FROM products WHERE products.id = transactions.product_id), 0),
                cost_price = COALESCE((SELECT cost_price FROM products WHERE products.id = transactions.product_id), 0),
                total_amount = ROUND(quantity * COALESCE((SELECT cost_price FROM products WHERE products.id = transactions.product_id), 0), 2)
            WHERE (unit_price = 0 OR unit_price IS NULL) AND kind = 'IN'
        """)
        conn.execute("""
            UPDATE transactions
            SET unit_price = COALESCE((SELECT price FROM products WHERE products.id = transactions.product_id), 0),
                cost_price = COALESCE((SELECT cost_price FROM products WHERE products.id = transactions.product_id), 0),
                total_amount = ROUND(quantity * COALESCE((SELECT price FROM products WHERE products.id = transactions.product_id), 0), 2)
            WHERE (unit_price = 0 OR unit_price IS NULL) AND kind = 'OUT'
        """)

        # Add sample expiry dates if products have none (for demonstration)
        conn.execute("""
            UPDATE products SET expiry_date = '2026-11-12' 
            WHERE name LIKE '%Maggi%' AND (expiry_date = '' OR expiry_date IS NULL)
        """)
        conn.execute("""
            UPDATE products SET expiry_date = '2026-10-24' 
            WHERE name LIKE '%Parle-G%' AND (expiry_date = '' OR expiry_date IS NULL)
        """)
        conn.execute("""
            UPDATE products SET expiry_date = '2027-04-15' 
            WHERE name LIKE '%Basmati%' AND (expiry_date = '' OR expiry_date IS NULL)
        """)
        conn.execute("""
            UPDATE products SET expiry_date = '2027-09-01' 
            WHERE name LIKE '%Sugar%' AND (expiry_date = '' OR expiry_date IS NULL)
        """)

        conn.commit()

    # ----- products: create / read / update / delete ----------------------
    def add_product(self, name, category, price, quantity, reorder_level, cost_price=None, expiry_date=None):
        name, category, price, quantity, reorder_level, cost_price, expiry_date = clean_product_data(
            name, category, price, quantity, reorder_level, cost_price, expiry_date
        )
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO products (name, category, price, cost_price, quantity, "
                "reorder_level, expiry_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, category, price, cost_price, quantity, reorder_level, expiry_date, now_text()),
            )
            product_id = cur.lastrowid
            if quantity > 0:   # record the opening stock in the history at buying rate
                tot = round(quantity * cost_price, 2)
                conn.execute(
                    "INSERT INTO transactions (product_id, kind, quantity, unit_price, cost_price, "
                    "total_amount, note, created_at) VALUES (?, 'IN', ?, ?, ?, ?, 'Opening stock', ?)",
                    (product_id, quantity, cost_price, cost_price, tot, now_text()),
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

    def update_product(self, product_id, name, category, price, reorder_level, cost_price=None, expiry_date=None):
        """Edit product details. Quantity changes go through stock movements."""
        prod = self.get_product(product_id)
        if cost_price is None or str(cost_price).strip() == "":
            cost_price = prod.get("cost_price", 0)
        if expiry_date is None:
            expiry_date = prod.get("expiry_date", "")

        name, category, price, _, reorder_level, cost_price, expiry_date = clean_product_data(
            name, category, price, 0, reorder_level, cost_price, expiry_date
        )
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE products SET name=?, category=?, price=?, cost_price=?, reorder_level=?, expiry_date=? "
                "WHERE id=?",
                (name, category, price, cost_price, reorder_level, expiry_date, product_id),
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
    def record_transaction(self, product_id, kind, quantity, note="", unit_price=None):
        """
        Add stock (kind='IN') at buying rate or sell/remove stock (kind='OUT') at selling rate.
        Both the stock update and the history entry succeed together or not at all.
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

        cost_price = float(product.get("cost_price", 0) or 0)
        selling_price = float(product.get("price", 0) or 0)

        # Rate determination
        if unit_price is not None and str(unit_price).strip() != "":
            try:
                rate = float(unit_price)
                if rate < 0:
                    raise ValidationError("Rate cannot be negative.")
            except ValueError:
                raise ValidationError("Rate must be a valid number.")
        else:
            rate = cost_price if kind == "IN" else selling_price

        total_amount = round(quantity * rate, 2)
        change = quantity if kind == "IN" else -quantity

        conn = self._connect()
        try:
            conn.execute(
                "UPDATE products SET quantity = quantity + ? WHERE id = ?",
                (change, product_id),
            )
            conn.execute(
                "INSERT INTO transactions (product_id, kind, quantity, unit_price, "
                "cost_price, total_amount, reason, is_loss, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'SALE', 0, ?, ?)",
                (product_id, kind, quantity, rate, cost_price, total_amount, (note or "").strip(), now_text()),
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise InventoryError("Database error while saving the transaction.")
        finally:
            conn.close()

    def discard_product(self, product_id, quantity, reason="EXPIRED", note=""):
        """
        Discards expired or damaged products from inventory.
        The full buying worth (quantity * cost_price) is logged as an unrecovered loss
        and deducted from net profit.
        """
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValidationError("Quantity must be a whole number.")
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        product = self.get_product(product_id)
        if quantity > product["quantity"]:
            raise InsufficientStockError(
                f"Only {product['quantity']} of '{product['name']}' in stock; cannot discard {quantity}."
            )

        cost_price = float(product.get("cost_price", 0) or 0)
        loss_amount = round(quantity * cost_price, 2)
        note_text = note.strip() if note else f"Discarded expired stock (Loss of ₹{loss_amount:,.2f})"

        conn = self._connect()
        try:
            conn.execute(
                "UPDATE products SET quantity = quantity - ? WHERE id = ?",
                (quantity, product_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (
                    product_id, kind, quantity, unit_price, cost_price,
                    total_amount, reason, is_loss, note, created_at
                ) VALUES (?, 'OUT', ?, 0.0, ?, 0.0, ?, 1, ?, ?)
                """,
                (product_id, quantity, cost_price, reason, note_text, now_text()),
            )
            conn.commit()
            return loss_amount
        except sqlite3.Error as err:
            conn.rollback()
            raise InventoryError(f"Database error while recording discard: {err}")
        finally:
            conn.close()

    def list_transactions(self, limit=None, product_id=None, start_date=None, end_date=None):
        query = (
            "SELECT t.*, p.name AS product_name, p.category, p.price AS current_price, "
            "p.cost_price AS current_cost_price "
            "FROM transactions t "
            "JOIN products p ON p.id = t.product_id WHERE 1=1"
        )
        params = []
        if product_id:
            query += " AND t.product_id = ?"
            params.append(product_id)
        if start_date:
            query += " AND t.created_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND t.created_at <= ?"
            params.append(end_date)
        query += " ORDER BY t.id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("kind") == "OUT":
                d["profit"] = round(d.get("total_amount", 0) - (d.get("quantity", 0) * (d.get("cost_price", 0) or 0)), 2)
            else:
                d["profit"] = 0.0
            results.append(d)
        return results

    # ----- Multi-Item Billing & Invoicing (POS) --------------------------
    def generate_invoice_number(self):
        """Generates a sequential invoice number like INV-20261029-001."""
        date_str = datetime.now().strftime("%Y%m%d")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM invoices WHERE invoice_no LIKE ?",
                (f"INV-{date_str}-%",)
            ).fetchone()
            count = row["count"] if row else 0
        finally:
            conn.close()
        return f"INV-{date_str}-{count + 1:03d}"

    def create_invoice(self, customer_name, customer_phone, items, discount=0.0, tax_percent=0.0, payment_method="Cash", note=""):
        """
        Creates an invoice for multiple items at once.
        - Verifies stock for all items
        - Deducts quantities atomically
        - Records 'OUT' movement for each item in transactions table
        - Saves invoice and invoice items
        """
        customer_name = (customer_name or "").strip() or "Walk-in Customer"
        customer_phone = (customer_phone or "").strip()
        payment_method = (payment_method or "Cash").strip()
        note = (note or "").strip()

        if not items:
            raise ValidationError("Invoice must contain at least one item.")

        try:
            discount = float(discount or 0)
            tax_percent = float(tax_percent or 0)
        except ValueError:
            raise ValidationError("Discount and tax must be numbers.")

        if discount < 0 or tax_percent < 0:
            raise ValidationError("Discount and tax cannot be negative.")

        # 1. Validate all items and current stock first
        validated_items = []
        for item in items:
            prod_id = int(item["product_id"])
            qty = int(item["quantity"])
            if qty <= 0:
                raise ValidationError("Item quantity must be greater than zero.")

            prod = self.get_product(prod_id)
            if qty > prod["quantity"]:
                raise InsufficientStockError(
                    f"Only {prod['quantity']} of '{prod['name']}' in stock; cannot sell {qty}."
                )

            unit_price = float(item.get("unit_price") or prod["price"])
            cost_price = float(prod.get("cost_price", 0) or 0)
            line_total = round(qty * unit_price, 2)
            profit = round(line_total - (qty * cost_price), 2)

            validated_items.append({
                "product_id": prod_id,
                "product_name": prod["name"],
                "quantity": qty,
                "unit_price": unit_price,
                "cost_price": cost_price,
                "total_price": line_total,
                "profit": profit,
            })

        subtotal = round(sum(i["total_price"] for i in validated_items), 2)
        if discount > subtotal:
            raise ValidationError(f"Discount (₹{discount:.2f}) cannot exceed subtotal (₹{subtotal:.2f}).")

        taxable_amount = max(0.0, subtotal - discount)
        tax_amount = round(taxable_amount * (tax_percent / 100.0), 2)
        total_amount = round(taxable_amount + tax_amount, 2)
        invoice_no = self.generate_invoice_number()
        timestamp = now_text()

        conn = self._connect()
        try:
            # 2. Insert invoice
            cur = conn.execute(
                """
                INSERT INTO invoices (
                    invoice_no, customer_name, customer_phone, subtotal, discount,
                    tax, total_amount, payment_method, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (invoice_no, customer_name, customer_phone, subtotal, discount,
                 tax_amount, total_amount, payment_method, note, timestamp)
            )
            invoice_id = cur.lastrowid

            # 3. Insert invoice items, deduct stock, and write stock history
            for item in validated_items:
                conn.execute(
                    """
                    INSERT INTO invoice_items (
                        invoice_id, product_id, product_name, quantity,
                        unit_price, cost_price, total_price, profit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (invoice_id, item["product_id"], item["product_name"], item["quantity"],
                     item["unit_price"], item["cost_price"], item["total_price"], item["profit"])
                )

                # Deduct stock
                conn.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE id = ?",
                    (item["quantity"], item["product_id"])
                )

                # Record stock out movement
                conn.execute(
                    """
                    INSERT INTO transactions (
                        product_id, kind, quantity, unit_price, cost_price,
                        total_amount, note, created_at
                    ) VALUES (?, 'OUT', ?, ?, ?, ?, ?, ?)
                    """,
                    (item["product_id"], item["quantity"], item["unit_price"], item["cost_price"],
                     item["total_price"], f"Bill #{invoice_no} ({customer_name})", timestamp)
                )

            conn.commit()
            return invoice_id
        except sqlite3.Error as err:
            conn.rollback()
            raise InventoryError(f"Database error while generating invoice: {err}")
        finally:
            conn.close()

    def get_invoice(self, invoice_id):
        """Returns invoice details and all line items."""
        conn = self._connect()
        try:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv:
                raise NotFoundError("Invoice not found.")
            items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,)).fetchall()
        finally:
            conn.close()

        invoice_dict = dict(inv)
        invoice_dict["items"] = [dict(i) for i in items]
        invoice_dict["total_profit"] = round(sum(i["profit"] for i in invoice_dict["items"]), 2)
        invoice_dict["item_count"] = sum(i["quantity"] for i in invoice_dict["items"])
        return invoice_dict

    def list_invoices(self, search="", limit=50):
        """Returns list of invoices with item counts and search filtering."""
        query = """
            SELECT i.*, COUNT(ii.id) as distinct_items, SUM(ii.quantity) as total_units
            FROM invoices i
            LEFT JOIN invoice_items ii ON i.id = ii.invoice_id
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (i.invoice_no LIKE ? OR i.customer_name LIKE ? OR i.customer_phone LIKE ?)"
            term = f"%{search.strip()}%"
            params.extend([term, term, term])

        query += " GROUP BY i.id ORDER BY i.id DESC LIMIT ?"
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ----- Expiry Date & Batch Tracking -----------------------------------
    def get_expiry_report(self, days=30):
        """
        Analyzes perishable stock and flags expired, expiring-soon, and safe products.
        """
        today = date.today()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM products 
                WHERE expiry_date IS NOT NULL AND expiry_date != '' AND quantity > 0
                ORDER BY expiry_date ASC
                """
            ).fetchall()
        finally:
            conn.close()

        expired = []
        expiring_soon = []
        safe = []
        all_items = []

        for r in rows:
            p = dict(r)
            try:
                exp_date = datetime.strptime(p["expiry_date"], "%Y-%m-%d").date()
                delta_days = (exp_date - today).days
                p["days_left"] = delta_days

                if delta_days < 0:
                    p["status"] = "expired"
                    p["status_label"] = f"Expired {abs(delta_days)} days ago"
                    expired.append(p)
                elif delta_days <= days:
                    p["status"] = "expiring_soon"
                    if delta_days == 0:
                        p["status_label"] = "Expires Today!"
                    else:
                        p["status_label"] = f"Expires in {delta_days} days"
                    expiring_soon.append(p)
                else:
                    p["status"] = "safe"
                    p["status_label"] = f"Fresh ({delta_days} days left)"
                    safe.append(p)

                all_items.append(p)
            except ValueError:
                continue

        total_loss = 0.0
        conn = self._connect()
        try:
            loss_row = conn.execute("SELECT SUM(quantity * cost_price) as loss FROM transactions WHERE is_loss = 1 OR reason = 'EXPIRED'").fetchone()
            total_loss = round(float(loss_row["loss"] or 0), 2) if loss_row else 0.0
        finally:
            conn.close()

        return {
            "expired": expired,
            "expiring_soon": expiring_soon,
            "safe": safe,
            "expired_count": len(expired),
            "expiring_soon_count": len(expiring_soon),
            "total_expired_loss": total_loss,
            "all_items": all_items,
        }

    # ----- reports & analytics --------------------------------------------
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
        total_investment = sum((p.get("cost_price", 0) or 0) * p["quantity"] for p in products)
        out_of_stock = [p for p in products if p["quantity"] == 0]
        expiry_rep = self.get_expiry_report()

        return {
            "total_products": len(products),
            "total_units": sum(p["quantity"] for p in products),
            "total_value": round(total_value, 2),
            "total_investment": round(total_investment, 2),
            "potential_profit": round(total_value - total_investment, 2),
            "low_stock_count": len(self.low_stock_products()),
            "out_of_stock_count": len(out_of_stock),
            "categories": len({p["category"] for p in products}),
            "expired_count": expiry_rep["expired_count"],
            "expiring_soon_count": expiry_rep["expiring_soon_count"],
        }

    def stock_by_category(self):
        """Dictionary of {category: total units} used for the dashboard chart."""
        totals = {}
        for p in self.list_products():
            totals[p["category"]] = totals.get(p["category"], 0) + p["quantity"]
        return totals

    def get_analytics_summary(self, period="weekly"):
        """Calculates period financial metrics (stocks in, stocks out, profit, investment)."""
        now = datetime.now()
        start_date = None
        period_label = "All Time"

        if period == "weekly":
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
            period_label = "This Week (Last 7 Days)"
        elif period == "monthly":
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
            period_label = "This Month (Last 30 Days)"

        txs = self.list_transactions(start_date=start_date)

        # Separate regular sales from loss write-offs
        sales_txs = [t for t in txs if t["kind"] == "OUT" and not t.get("is_loss")]
        loss_txs = [t for t in txs if t["kind"] == "OUT" and (t.get("is_loss") == 1 or t.get("reason") in ("EXPIRED", "DAMAGED"))]

        stocks_in_qty = sum(t["quantity"] for t in txs if t["kind"] == "IN")
        stocks_in_amount = sum(t["total_amount"] for t in txs if t["kind"] == "IN")

        stocks_out_qty = sum(t["quantity"] for t in sales_txs)
        stocks_out_amount = sum(t["total_amount"] for t in sales_txs)
        cogs = sum(t["quantity"] * (t.get("cost_price", 0) or 0) for t in sales_txs)
        gross_profit = round(stocks_out_amount - cogs, 2)

        expired_loss_amount = round(sum(t["quantity"] * (t.get("cost_price", 0) or 0) for t in loss_txs), 2)
        expired_loss_qty = sum(t["quantity"] for t in loss_txs)

        net_profit = round(gross_profit - expired_loss_amount, 2)
        profit_margin = round((net_profit / stocks_out_amount * 100), 1) if stocks_out_amount > 0 else 0.0

        products = self.list_products()
        current_inv_investment = round(sum((p.get("cost_price", 0) or 0) * p["quantity"] for p in products), 2)
        current_inv_value = round(sum(p["price"] * p["quantity"] for p in products), 2)
        current_units = sum(p["quantity"] for p in products)

        conn = self._connect()
        try:
            all_in = conn.execute("SELECT SUM(quantity) as qty, SUM(total_amount) as amt FROM transactions WHERE kind='IN'").fetchone()
            all_out = conn.execute("SELECT SUM(quantity) as qty, SUM(total_amount) as amt, SUM(quantity * cost_price) as cogs FROM transactions WHERE kind='OUT' AND COALESCE(is_loss, 0) = 0").fetchone()
            all_loss = conn.execute("SELECT SUM(quantity) as qty, SUM(quantity * cost_price) as loss FROM transactions WHERE is_loss = 1 OR reason = 'EXPIRED'").fetchone()
        finally:
            conn.close()

        all_in_amt = float(all_in["amt"] or 0) if all_in else 0.0
        all_out_amt = float(all_out["amt"] or 0) if all_out else 0.0
        all_cogs = float(all_out["cogs"] or 0) if all_out else 0.0
        all_loss_amt = float(all_loss["loss"] or 0) if all_loss else 0.0
        all_profit = round(all_out_amt - all_cogs - all_loss_amt, 2)

        return {
            "period": period,
            "period_label": period_label,
            "stocks_in_qty": stocks_in_qty,
            "stocks_in_amount": round(stocks_in_amount, 2),
            "stocks_out_qty": stocks_out_qty,
            "stocks_out_amount": round(stocks_out_amount, 2),
            "cogs": round(cogs, 2),
            "gross_profit": gross_profit,
            "expired_loss_amount": expired_loss_amount,
            "expired_loss_qty": expired_loss_qty,
            "profit": net_profit,
            "net_profit": net_profit,
            "profit_margin": profit_margin,
            "current_inventory_investment": current_inv_investment,
            "current_inventory_value": current_inv_value,
            "current_units": current_units,
            "all_time_in_amount": round(all_in_amt, 2),
            "all_time_out_amount": round(all_out_amt, 2),
            "all_time_loss_amount": round(all_loss_amt, 2),
            "all_time_profit": all_profit,
            "tx_count": len(txs),
        }

    def get_day_wise_sales(self, days=14):
        """Returns day-by-day aggregated data for the last N days for charts and tables."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT 
                    substr(created_at, 1, 10) as day,
                    SUM(CASE WHEN kind = 'IN' THEN quantity ELSE 0 END) as in_qty,
                    SUM(CASE WHEN kind = 'IN' THEN total_amount ELSE 0 END) as in_amount,
                    SUM(CASE WHEN kind = 'OUT' AND COALESCE(is_loss, 0) = 0 THEN quantity ELSE 0 END) as out_qty,
                    SUM(CASE WHEN kind = 'OUT' AND COALESCE(is_loss, 0) = 0 THEN total_amount ELSE 0 END) as out_amount,
                    SUM(CASE WHEN kind = 'OUT' AND COALESCE(is_loss, 0) = 0 THEN (quantity * cost_price) ELSE 0 END) as cogs,
                    SUM(CASE WHEN kind = 'OUT' AND (COALESCE(is_loss, 0) = 1 OR reason = 'EXPIRED') THEN quantity ELSE 0 END) as loss_qty,
                    SUM(CASE WHEN kind = 'OUT' AND (COALESCE(is_loss, 0) = 1 OR reason = 'EXPIRED') THEN (quantity * cost_price) ELSE 0 END) as loss_amount
                FROM transactions
                GROUP BY substr(created_at, 1, 10)
                ORDER BY day ASC
                """
            ).fetchall()
        finally:
            conn.close()

        data_by_day = {r["day"]: dict(r) for r in rows}

        now = datetime.now()
        day_list = []
        for i in range(days, -1, -1):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            rec = data_by_day.get(d, {
                "day": d,
                "in_qty": 0,
                "in_amount": 0.0,
                "out_qty": 0,
                "out_amount": 0.0,
                "cogs": 0.0,
                "loss_qty": 0,
                "loss_amount": 0.0,
            })
            out_amt = round(float(rec.get("out_amount") or 0), 2)
            cogs = round(float(rec.get("cogs") or 0), 2)
            in_amt = round(float(rec.get("in_amount") or 0), 2)
            loss_amt = round(float(rec.get("loss_amount") or 0), 2)
            profit = round(out_amt - cogs - loss_amt, 2)
            margin = round((profit / out_amt * 100), 1) if out_amt > 0 else 0.0

            date_obj = datetime.strptime(d, "%Y-%m-%d")
            label_short = date_obj.strftime("%d %b")
            label_full = date_obj.strftime("%d %b (%a)")

            day_list.append({
                "date": d,
                "label_short": label_short,
                "label_full": label_full,
                "day_name": date_obj.strftime("%a"),
                "in_qty": int(rec.get("in_qty") or 0),
                "in_amount": in_amt,
                "out_qty": int(rec.get("out_qty") or 0),
                "out_amount": out_amt,
                "cogs": cogs,
                "loss_qty": int(rec.get("loss_qty") or 0),
                "loss_amount": loss_amt,
                "profit": profit,
                "profit_margin": margin,
            })

        chart_data = {
            "labels": [d["label_short"] for d in day_list],
            "sales": [d["out_amount"] for d in day_list],
            "purchases": [d["in_amount"] for d in day_list],
            "losses": [d["loss_amount"] for d in day_list],
            "profits": [d["profit"] for d in day_list],
            "sales_units": [d["out_qty"] for d in day_list],
            "purchase_units": [d["in_qty"] for d in day_list],
        }

        active_days = [d for d in day_list if d["in_qty"] > 0 or d["out_qty"] > 0 or d["loss_amount"] > 0]
        if not active_days and data_by_day:
            for d, rec in sorted(data_by_day.items(), reverse=True):
                out_amt = round(float(rec.get("out_amount") or 0), 2)
                cogs = round(float(rec.get("cogs") or 0), 2)
                in_amt = round(float(rec.get("in_amount") or 0), 2)
                loss_amt = round(float(rec.get("loss_amount") or 0), 2)
                profit = round(out_amt - cogs - loss_amt, 2)
                margin = round((profit / out_amt * 100), 1) if out_amt > 0 else 0.0
                date_obj = datetime.strptime(d, "%Y-%m-%d")
                active_days.append({
                    "date": d,
                    "label_short": date_obj.strftime("%d %b"),
                    "label_full": date_obj.strftime("%d %b (%a)"),
                    "day_name": date_obj.strftime("%a"),
                    "in_qty": int(rec.get("in_qty") or 0),
                    "in_amount": in_amt,
                    "out_qty": int(rec.get("out_qty") or 0),
                    "out_amount": out_amt,
                    "cogs": cogs,
                    "loss_qty": int(rec.get("loss_qty") or 0),
                    "loss_amount": loss_amt,
                    "profit": profit,
                    "profit_margin": margin,
                })

        return {
            "days": day_list,
            "active_days": active_days,
            "chart_data": chart_data,
            "total_chart_sales": round(sum(d["out_amount"] for d in day_list), 2),
            "total_chart_purchases": round(sum(d["in_amount"] for d in day_list), 2),
            "total_chart_losses": round(sum(d["loss_amount"] for d in day_list), 2),
            "total_chart_profit": round(sum(d["profit"] for d in day_list), 2),
        }

    def get_top_products_performance(self, period="weekly", limit=5):
        """Products with the highest sales and profit during the period."""
        now = datetime.now()
        start_date = None
        if period == "weekly":
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        elif period == "monthly":
            start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")

        query = """
            SELECT 
                p.id, p.name, p.category, p.price, p.cost_price,
                SUM(CASE WHEN t.kind = 'OUT' THEN t.quantity ELSE 0 END) as units_sold,
                SUM(CASE WHEN t.kind = 'OUT' THEN t.total_amount ELSE 0 END) as revenue,
                SUM(CASE WHEN t.kind = 'OUT' THEN (t.quantity * t.cost_price) ELSE 0 END) as cogs
            FROM products p
            JOIN transactions t ON p.id = t.product_id
            WHERE 1=1
        """
        params = []
        if start_date:
            query += " AND t.created_at >= ?"
            params.append(start_date)
        query += " GROUP BY p.id HAVING revenue > 0 ORDER BY revenue DESC LIMIT ?"
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        items = []
        for r in rows:
            rev = round(float(r["revenue"] or 0), 2)
            cogs = round(float(r["cogs"] or 0), 2)
            profit = round(rev - cogs, 2)
            margin = round((profit / rev * 100), 1) if rev > 0 else 0.0
            items.append({
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "units_sold": int(r["units_sold"] or 0),
                "revenue": rev,
                "cost": cogs,
                "profit": profit,
                "margin": margin,
            })
        return items

    # ----- CSV import / export (file handling) ----------------------------
    CSV_COLUMNS = ["name", "category", "price", "cost_price", "quantity", "reorder_level", "expiry_date"]

    def export_csv(self):
        """Return all products as CSV text."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self.CSV_COLUMNS)
        for p in self.list_products():
            writer.writerow([p.get(c, "") for c in self.CSV_COLUMNS])
        return buffer.getvalue()

    def import_csv(self, text):
        """
        Add products from CSV text. Returns (added_count, error_messages).
        Supports 5-column, 6-column, and 7-column (with expiry_date) CSV files.
        """
        reader = csv.DictReader(io.StringIO(text))
        required_cols = {"name", "category", "price", "quantity", "reorder_level"}
        if reader.fieldnames is None or not required_cols <= set(reader.fieldnames):
            raise ValidationError(
                "CSV must contain at least: " + ", ".join(required_cols)
            )
        added, errors = 0, []
        for line_no, row in enumerate(reader, start=2):
            try:
                cost_price = row.get("cost_price", None)
                expiry_date = row.get("expiry_date", None)
                self.add_product(
                    row["name"],
                    row["category"],
                    row["price"],
                    row["quantity"],
                    row["reorder_level"],
                    cost_price=cost_price,
                    expiry_date=expiry_date,
                )
                added += 1
            except InventoryError as err:
                errors.append(f"Line {line_no}: {err}")
        return added, errors
