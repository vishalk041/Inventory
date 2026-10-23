"""
app.py
Flask web application for the Small Shop Inventory Tracker.

Run with:   python app.py
Then open:  http://127.0.0.1:5001
"""

from flask import (
    Flask, Response, flash, redirect, render_template, request, url_for,
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
# Feature 1: Dashboard (summary numbers, low-stock alerts, recent activity)
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        summary=manager.summary(),
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
# Feature 4: Low-stock report
# ---------------------------------------------------------------------------
@app.route("/low-stock")
def low_stock():
    return render_template("low_stock.html", items=manager.low_stock_products())


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


if __name__ == "__main__":
    # port 5001 because macOS uses port 5000 for AirPlay
    app.run(debug=True, port=5001)
