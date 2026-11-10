# Small Shop Inventory Tracker

A simple web application for a small shop to track products and stock levels.
Built in Python 3 with Flask and SQLite for the *Programming with Python (BTCS2101)* mini project.

## Features

1. **Dashboard**: total products, units in stock, stock value, low-stock and out-of-stock counts, stock by category, recent activity.
2. **Product management**: add, edit, delete products; search by name and filter by category.
3. **Stock in / stock out**: record deliveries and sales; selling more than the available stock is blocked; every movement is saved in a history table.
4. **Low-stock alerts**: products at or below their reorder level are highlighted and listed in a separate report.
5. **CSV import / export**: back up the product list or load many products at once (`sample_products.csv` is included).
6. **Analytics & Financial Reports**: track weekly, monthly, and all-time total stocks in (at buying rate) and stocks out (at selling rate), monitor net profit, total inventory investment, and visualize day-wise sales graphs.
7. **Multi-Item Billing & Printable Invoices (Mini POS)**: fast point-of-sale checkout where multiple products are added to a cart, discounts & GST/taxes calculated, and printable invoices/receipts generated (`window.print()`).
8. **Expiry Date & Batch Tracking**: track expiration dates of perishable goods with automated "Expired" and "Expiring Soon" countdown alerts to prevent losses from dead stock.

## Python concepts used

| Concept | Where |
|---|---|
| Functions | `clean_product_data()`, `now_text()` in `inventory.py`; route functions in `app.py` |
| Classes and objects | `InventoryManager` and the custom exception classes in `inventory.py` |
| Data structures | lists of dictionaries (products), dictionary for category totals, set for category count, tuples |
| File handling | CSV export and import (`csv`, `io` modules) |
| Exception handling | `ValidationError`, `InsufficientStockError`, `NotFoundError` with `try/except/finally` |
| Modules | `sqlite3`, `csv`, `io`, `os`, `datetime`, `flask` |

## Project structure

```
inventory_app/
├── app.py               # Flask routes (web layer)
├── inventory.py         # InventoryManager class, validation, database code
├── requirements.txt
├── sample_products.csv  # sample data to import
├── static/style.css
└── templates/           # HTML pages (Jinja2)
```

## How to install and run

1. Install Python 3.9 or newer from https://www.python.org/downloads/
2. Open a terminal in the project folder and (optional but recommended) create a virtual environment:

   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # macOS / Linux
   ```

3. Install the requirement:

   ```
   pip install -r requirements.txt
   ```

4. Start the app:

   ```
   python app.py
   ```

5. Open <http://127.0.0.1:5000> in your browser.

The database file `inventory.db` is created automatically on the first run.
To start with sample data, go to **Products → Import CSV** and choose `sample_products.csv`.
To reset everything, stop the app and delete `inventory.db`.

## Dataset

No external dataset is needed. `sample_products.csv` is sample data written for this project.

## Declaration

AI tools (Claude by Anthropic) were used for help while developing this project. See the report for the full declaration.
