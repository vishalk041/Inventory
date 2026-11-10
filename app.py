"""
app.py
Flask web application for the Small Shop Inventory Tracker.

Run with:   python app.py
Then open:  http://127.0.0.1:5001
"""

import json
from flask import (
    Flask, Response, flash, redirect, render_template, request, url_for, jsonify,
)

from inventory import InventoryError, InventoryManager

app = Flask(__name__)
app.secret_key = "change-this-secret-key-for-college-demo"

manager = InventoryManager()


def matches_status(product, status):
    """True if a product fits the chosen status filter (in / low / out)."""
    if status == "out":
        return product["quantity"] == 0
    if status == "low":
        return 0 < product["quantity"] <= product["reorder_level"]
    if status == "in":
        return product["quantity"] > product["reorder_level"]
    return True   # no filter chosen


# ---------------------------------------------------------------------------
# Feature 1: Dashboard (summary numbers, financial highlights, expiry alerts)
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        summary=manager.summary(),
        analytics=manager.get_analytics_summary(period="weekly"),
        expiry=manager.get_expiry_report(),
        low_stock=manager.low_stock_products(),
        recent=manager.list_transactions(limit=8),
        by_category=manager.stock_by_category(),
    )


# ---------------------------------------------------------------------------
# Feature 2: Product management with search, category and status filters
# ---------------------------------------------------------------------------
@app.route("/products")
def products():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()

    items = [
        p for p in manager.list_products(search, category)
        if matches_status(p, status)
    ]
    return render_template(
        "products.html",
        products=items,
        categories=manager.list_categories(),
        search=search,
        selected_category=category,
        selected_status=status,
    )


@app.route("/products/add", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        try:
            manager.add_product(
                request.form.get("name"),
                request.form.get("category"),
                request.form.get("price"),
                request.form.get("quantity"),
                request.form.get("reorder_level"),
                cost_price=request.form.get("cost_price"),
                expiry_date=request.form.get("expiry_date"),
            )
            flash("Product added successfully.", "success")
            return redirect(url_for("products"))
        except InventoryError as err:
            flash(str(err), "error")
    return render_template(
        "product_form.html", product=request.form, editing=False
    )


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    try:
        product = manager.get_product(product_id)
    except InventoryError as err:
        flash(str(err), "error")
        return redirect(url_for("products"))

    if request.method == "POST":
        try:
            manager.update_product(
                product_id,
                request.form.get("name"),
                request.form.get("category"),
                request.form.get("price"),
                request.form.get("reorder_level"),
                cost_price=request.form.get("cost_price"),
                expiry_date=request.form.get("expiry_date"),
            )
            flash("Product updated.", "success")
            return redirect(url_for("products"))
        except InventoryError as err:
            flash(str(err), "error")
            product = {**product, **request.form.to_dict()}
    return render_template("product_form.html", product=product, editing=True)


@app.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    try:
        manager.delete_product(product_id)
        flash("Product deleted.", "success")
    except InventoryError as err:
        flash(str(err), "error")
    return redirect(url_for("products"))


# ---------------------------------------------------------------------------
# Feature 3: Stock in / stock out (sales) with history
# ---------------------------------------------------------------------------
@app.route("/stock", methods=["GET", "POST"])
def stock():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", 0))
            manager.record_transaction(
                product_id,
                request.form.get("kind"),
                request.form.get("quantity"),
                request.form.get("note", ""),
                unit_price=request.form.get("unit_price"),
            )
            flash("Stock updated.", "success")
            return redirect(url_for("stock"))
        except ValueError:
            flash("Please choose a product.", "error")
        except InventoryError as err:
            flash(str(err), "error")
    return render_template(
        "stock.html",
        products=manager.list_products(),
        preselected=request.args.get("product_id", type=int),
        history=manager.list_transactions(limit=15),
    )


@app.route("/history")
def history():
    product_id = request.args.get("product_id", type=int)
    return render_template(
        "history.html",
        transactions=manager.list_transactions(product_id=product_id),
        products=manager.list_products(),
        selected=product_id,
    )


# ---------------------------------------------------------------------------
# Feature 4: Low-stock report & Expiry tracking
# ---------------------------------------------------------------------------
@app.route("/low-stock")
def low_stock():
    return render_template("low_stock.html", items=manager.low_stock_products())


@app.route("/expiry")
def expiry():
    report = manager.get_expiry_report()
    return render_template("expiry.html", report=report)


@app.route("/products/<int:product_id>/discard", methods=["POST"])
def discard_product(product_id):
    try:
        quantity = request.form.get("quantity")
        reason = request.form.get("reason", "EXPIRED").strip() or "EXPIRED"
        note = request.form.get("note", "").strip()
        prod = manager.get_product(product_id)
        loss = manager.discard_product(product_id, quantity, reason=reason, note=note)
        flash(f"Discarded {quantity} unit(s) of '{prod['name']}'. Recorded ₹{loss:,.2f} as loss from expired products.", "success")
    except InventoryError as err:
        flash(str(err), "error")
    return redirect(url_for("expiry"))


# ---------------------------------------------------------------------------
# Feature 5: CSV export / import
# ---------------------------------------------------------------------------
@app.route("/export")
def export_csv():
    return Response(
        manager.export_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


@app.route("/import", methods=["GET", "POST"])
def import_csv():
    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or uploaded.filename == "":
            flash("Please choose a CSV file.", "error")
        else:
            try:
                text = uploaded.read().decode("utf-8-sig")
                added, errors = manager.import_csv(text)
                flash(f"Imported {added} product(s).", "success")
                for message in errors[:5]:
                    flash(message, "error")
                return redirect(url_for("products"))
            except UnicodeDecodeError:
                flash("The file is not a valid UTF-8 CSV.", "error")
            except InventoryError as err:
                flash(str(err), "error")
    return render_template("import.html")


# ---------------------------------------------------------------------------
# Feature 6: Analytics & Financial Reports
# ---------------------------------------------------------------------------
@app.route("/analytics")
def analytics():
    period = request.args.get("period", "weekly").strip()
    if period not in ("weekly", "monthly", "all"):
        period = "weekly"
    days = request.args.get("days", 14, type=int)
    if days not in (7, 14, 30):
        days = 14

    summary = manager.get_analytics_summary(period=period)
    daily_sales = manager.get_day_wise_sales(days=days)
    top_products = manager.get_top_products_performance(period=period, limit=6)

    return render_template(
        "analytics.html",
        summary=summary,
        daily_sales=daily_sales,
        top_products=top_products,
        period=period,
        days=days,
    )


# ---------------------------------------------------------------------------
# Feature 7: Multi-Item Billing & Printable Invoices (Mini POS)
# ---------------------------------------------------------------------------
@app.route("/billing", methods=["GET", "POST"])
def billing():
    if request.method == "POST":
        try:
            # Items JSON list passed from the billing screen cart
            raw_items = request.form.get("items_json")
            if not raw_items:
                flash("No items in the bill.", "error")
                return redirect(url_for("billing"))

            items = json.loads(raw_items)
            customer_name = request.form.get("customer_name")
            customer_phone = request.form.get("customer_phone")
            discount = request.form.get("discount", 0)
            tax_percent = request.form.get("tax_percent", 0)
            payment_method = request.form.get("payment_method", "Cash")
            note = request.form.get("note", "")

            invoice_id = manager.create_invoice(
                customer_name=customer_name,
                customer_phone=customer_phone,
                items=items,
                discount=discount,
                tax_percent=tax_percent,
                payment_method=payment_method,
                note=note,
            )
            flash("Invoice generated successfully!", "success")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))
        except InventoryError as err:
            flash(str(err), "error")
        except Exception as err:
            flash(f"Unexpected error: {err}", "error")

    # In-stock products available for billing
    products = [p for p in manager.list_products() if p["quantity"] > 0]
    return render_template("billing.html", products=products)


@app.route("/invoices")
def invoices():
    search = request.args.get("search", "").strip()
    invoice_list = manager.list_invoices(search=search)
    return render_template("invoices.html", invoices=invoice_list, search=search)


@app.route("/invoice/<int:invoice_id>")
def view_invoice(invoice_id):
    try:
        invoice = manager.get_invoice(invoice_id)
        return render_template("invoice.html", invoice=invoice)
    except InventoryError as err:
        flash(str(err), "error")
        return redirect(url_for("invoices"))


if __name__ == "__main__":
    # port 5001 because macOS uses port 5000 for AirPlay
    app.run(debug=True, port=5001)
