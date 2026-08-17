import os
import uuid
from functools import wraps
from datetime import datetime

from flask import (Flask, render_template, request, jsonify, session,
                    send_file, redirect, url_for)

from data.demo_data import build_demo_dataset, recompute_customers
from services.calculations import (enrich_order, compute_margin,
                                    product_profit_per_unit, product_margin,
                                    aggregate_orders)
from services.excel_service import generate_excel_report, REPORTS_DIR
from services.extraction import extract_file, simulate_extraction
from services.assistant import answer_question
from services.persistence import (
    ensure_demo_user, authenticate_user, create_user, get_user, user_access,
    activate_plan, get_product_cost, set_product_cost
)

app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")
app.secret_key = "shark-tank-demo-secret-key"

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo123"
ensure_demo_user(DEMO_EMAIL, DEMO_PASSWORD)

PLANS = {
    "free": {"name": "Free Demo", "monthly": 0, "annual": 0, "label_limit": 3},
    "premium_monthly": {"name": "Premium Monthly", "monthly": 1000, "annual": None, "label_limit": None},
    "premium_yearly": {"name": "Premium Yearly", "monthly": 800, "annual": 9600, "label_limit": None},
}

# ---------------------------------------------------------------------------
# In-memory "database". Reset on server restart; reloaded instantly via the
# "Load Demo Data" button so the app never looks empty.
# ---------------------------------------------------------------------------
STORE = {
    "products": [],
    "customers": [],
    "orders": [],
    "uploads": [],       # uploaded file records
    "pending_review": [],  # extracted-but-not-yet-saved order rows
    "reports": [],        # generated excel report history
    "settings": {
        "business_name": "Aarohi Retail Co.",
        "gst_number": "24ABCDE1234F1Z5",
        "currency": "INR",
        "default_packaging_cost": 15,
        "default_tax_percent": 18,
        "default_shipping_cost": 55,
        "notifications": True,
    },
}


def _seed():
    products, customers, orders = build_demo_dataset()
    STORE["products"] = products
    STORE["customers"] = customers
    STORE["orders"] = orders
    STORE["uploads"] = []
    STORE["pending_review"] = []
    STORE["reports"] = []


_seed()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def current_plan():
    plan = session.get("plan", "free")
    if plan == "trial":
        access = user_access(session.get("user_email", DEMO_EMAIL))
        return "premium_monthly" if access.get("active") else "free"
    return plan


def premium_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_plan() not in ("premium_monthly", "premium_yearly"):
            return jsonify({"ok": False, "error": "Premium is required for this feature.", "upgrade_url": url_for("pricing_page")}), 402
        return f(*args, **kwargs)
    return wrapper


def label_limit_reached():
    plan = PLANS[current_plan()]
    if plan["label_limit"] is None:
        return False
    return len(STORE["uploads"]) >= plan["label_limit"]


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/login")
def login_page():
    return render_template("login.html", demo_email=DEMO_EMAIL, demo_password=DEMO_PASSWORD)


@app.route("/pricing")
def pricing_page():
    return render_template("pricing.html", plans=PLANS)


@app.route("/app/dashboard")
@login_required
def page_dashboard():
    return render_template("dashboard.html", active="dashboard")


@app.route("/app/upload")
@login_required
def page_upload():
    return render_template("upload.html", active="upload")


@app.route("/app/review")
@login_required
def page_review():
    return render_template("review.html", active="upload")


@app.route("/app/orders")
@login_required
def page_orders():
    return render_template("orders.html", active="orders")


@app.route("/app/products")
@login_required
def page_products():
    return render_template("products.html", active="products")


@app.route("/app/customers")
@login_required
def page_customers():
    return render_template("customers.html", active="customers")


@app.route("/app/financials")
@login_required
def page_financials():
    return render_template("financials.html", active="financials")


@app.route("/app/analytics")
@login_required
def page_analytics():
    return render_template("analytics.html", active="analytics")


@app.route("/app/reports")
@login_required
def page_reports():
    return render_template("reports.html", active="reports")


@app.route("/app/settings")
@login_required
def page_settings():
    return render_template("settings.html", active="settings")


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------
@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters."}), 400
    try:
        user = create_user(email, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    session["logged_in"] = True
    session["user_email"] = email
    session["plan"] = "trial"
    return jsonify({"ok": True, "redirect": url_for("page_dashboard"), "trial_days": 7})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    user = authenticate_user(email, password)
    if not user:
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401
    access = user_access(email)
    session["logged_in"] = True
    session["user_email"] = email
    session["plan"] = access["plan"]
    return jsonify({"ok": True, "redirect": url_for("page_dashboard"), "subscription": access})


@app.route("/api/demo-login", methods=["POST"])
def api_demo_login():
    ensure_demo_user(DEMO_EMAIL, DEMO_PASSWORD)
    access = user_access(DEMO_EMAIL)
    session["logged_in"] = True
    session["user_email"] = DEMO_EMAIL
    session["plan"] = access["plan"]
    return jsonify({"ok": True, "redirect": url_for("page_dashboard"), "subscription": access})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": url_for("landing")})


@app.route("/api/subscription/status")
def api_subscription_status():
    email = session.get("user_email")
    if not email:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    access = user_access(email)
    session["plan"] = access["plan"]
    return jsonify({"ok": True, "email": email, **access,
                    "monthly_price": 1000, "yearly_price": 9600,
                    "yearly_monthly_equivalent": 800, "trial_days": 7})


@app.route("/api/subscription/activate", methods=["POST"])
def api_subscription_activate():
    # Demo-only activation. Replace this endpoint with Razorpay webhook verification
    # before accepting real money.
    email = session.get("user_email")
    if not email:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.get_json(force=True, silent=True) or {}
    plan = data.get("plan")
    try:
        user = activate_plan(email, plan)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    session["plan"] = plan
    return jsonify({"ok": True, "message": "Premium activated for demo.", "plan": user["plan"]})


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------
@app.route("/api/demo/load", methods=["POST"])
def api_demo_load():
    _seed()
    return jsonify({"ok": True, "message": "Demo data loaded successfully.",
                     "counts": {"products": len(STORE["products"]),
                                "orders": len(STORE["orders"]),
                                "customers": len(STORE["customers"])}})


# ---------------------------------------------------------------------------
# Dashboard / Financials / Analytics
# ---------------------------------------------------------------------------
def _cost_breakdown(orders):
    keys = ["purchase_cost", "shipping", "tax", "platform_fee", "packaging", "other_cost"]
    labels = {"purchase_cost": "Product Cost", "shipping": "Shipping", "tax": "GST/Tax",
              "platform_fee": "Platform Fees", "packaging": "Packaging", "other_cost": "Other Costs"}
    breakdown = {labels[k]: round(sum(o.get(k, 0) for o in orders), 2) for k in keys}
    return breakdown


def _series_by_date(orders):
    by_date = {}
    for o in orders:
        d = o["date"]
        e = by_date.setdefault(d, {"revenue": 0, "cost": 0, "profit": 0})
        e["revenue"] += o["revenue"]
        e["cost"] += o["total_cost"]
        e["profit"] += o["profit"]
    dates = sorted(by_date.keys())
    return {
        "labels": dates,
        "revenue": [round(by_date[d]["revenue"], 2) for d in dates],
        "cost": [round(by_date[d]["cost"], 2) for d in dates],
        "profit": [round(by_date[d]["profit"], 2) for d in dates],
    }


def _sales_by_product(orders, top=8):
    rollup = {}
    for o in orders:
        r = rollup.setdefault(o["product_name"], {"revenue": 0, "profit": 0, "quantity": 0})
        r["revenue"] += o["revenue"]
        r["profit"] += o["profit"]
        r["quantity"] += o["quantity"]
    ranked = sorted(rollup.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:top]
    return {"labels": [k for k, _ in ranked], "revenue": [round(v["revenue"], 2) for _, v in ranked]}


@app.route("/api/dashboard/summary")
def api_dashboard_summary():
    orders = STORE["orders"]
    kpi = aggregate_orders(orders)
    return jsonify({
        "kpi": kpi,
        "trend": {"revenue_change_pct": 18.4, "cost_change_pct": 9.2,
                   "profit_change_pct": 24.7, "margin_change_pct": 3.1},
        "revenue_vs_cost": _series_by_date(orders),
        "profit_trend": _series_by_date(orders),
        "sales_by_product": _sales_by_product(orders),
        "cost_breakdown": _cost_breakdown(orders),
        "business_name": STORE["settings"]["business_name"],
    })


@app.route("/api/financials/summary")
def api_financials_summary():
    orders = STORE["orders"]
    kpi = aggregate_orders(orders)
    return jsonify({
        "kpi": kpi,
        "cost_breakdown": _cost_breakdown(orders),
        "series": _series_by_date(orders),
    })


@app.route("/api/analytics")
def api_analytics():
    orders = STORE["orders"]
    rollup = {}
    for o in orders:
        r = rollup.setdefault(o["product_name"], {"revenue": 0, "profit": 0, "quantity": 0})
        r["revenue"] += o["revenue"]
        r["profit"] += o["profit"]
        r["quantity"] += o["quantity"]

    top_by_revenue = sorted(rollup.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:6]
    top_by_profit = sorted(rollup.items(), key=lambda kv: kv[1]["profit"], reverse=True)[:6]
    top_by_qty = sorted(rollup.items(), key=lambda kv: kv[1]["quantity"], reverse=True)[:6]
    losers = sorted([(k, v) for k, v in rollup.items() if v["profit"] < 0],
                     key=lambda kv: kv[1]["profit"])[:6]

    best_customers = sorted(STORE["customers"], key=lambda c: c["total_revenue"], reverse=True)[:6]

    return jsonify({
        "series": _series_by_date(orders),
        "top_by_revenue": [{"name": k, **v} for k, v in top_by_revenue],
        "top_by_profit": [{"name": k, **v} for k, v in top_by_profit],
        "top_by_quantity": [{"name": k, **v} for k, v in top_by_qty],
        "loss_making": [{"name": k, **v} for k, v in losers],
        "best_customers": best_customers,
        "insights": _generate_insights(orders, rollup),
    })


def _generate_insights(orders, rollup):
    insights = []
    if rollup:
        top = max(rollup.items(), key=lambda kv: kv[1]["revenue"])
        top_margin = round((top[1]["profit"] / top[1]["revenue"]) * 100, 1) if top[1]["revenue"] else 0
        insights.append(f"Your highest-selling product '{top[0]}' generated ₹{top[1]['revenue']:,.0f} "
                         f"revenue but only a {top_margin}% margin.")
    total_cost = sum(o["total_cost"] for o in orders)
    shipping_total = sum(o["shipping"] for o in orders)
    if total_cost:
        pct = round((shipping_total / total_cost) * 100, 1)
        insights.append(f"Shipping costs represent {pct}% of your total expenses.")
    losers = [(k, v) for k, v in rollup.items() if v["profit"] < 0 and v["quantity"] >= 2]
    if losers:
        worst = min(losers, key=lambda kv: kv[1]["profit"])
        insights.append(f"'{worst[0]}' is selling frequently but generating negative profit "
                         f"(₹{worst[1]['profit']:,.0f} loss).")
    return insights


# ---------------------------------------------------------------------------
# Upload / Extraction / Review
# ---------------------------------------------------------------------------
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "xlsx", "xls", "csv"}


@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if label_limit_reached():
        return jsonify({"ok": False, "error": "Free Demo allows 3 uploads. Upgrade to Premium for unlimited label processing.", "upgrade_url": url_for("pricing_page")}), 402
    if not files:
        return jsonify({"ok": False, "error": "Please upload a PDF, CSV, Excel, PNG or JPG file."}), 400

    results = []
    for f in files:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXT:
            results.append({"file": f.filename, "status": "Failed",
                             "error": "Unsupported file type."})
            continue

        file_bytes = f.read()
        extracted = extract_file(file_bytes, f.filename, STORE["products"], STORE["customers"])
        upload_record = {
            "id": str(uuid.uuid4())[:8],
            "file": f.filename,
            "status": "Processed",
            "orders_found": len(extracted),
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        STORE["uploads"].insert(0, upload_record)
        STORE["pending_review"].extend(extracted)
        results.append(upload_record)

    return jsonify({"ok": True, "results": results,
                     "pending_review_count": len(STORE["pending_review"])})


@app.route("/api/uploads")
def api_uploads():
    return jsonify(STORE["uploads"])


@app.route("/api/review", methods=["GET"])
def api_review_list():
    return jsonify(STORE["pending_review"])


@app.route("/api/review/<row_id>", methods=["PUT"])
def api_review_update(row_id):
    data = request.get_json(force=True, silent=True) or {}
    for row in STORE["pending_review"]:
        if row["id"] == row_id:
            for k in ("product_name", "sku", "customer_name", "city", "quantity",
                       "selling_price", "purchase_cost", "shipping", "tax",
                       "platform_fee", "other_cost", "payment_status", "status"):
                if k in data:
                    row[k] = data[k]
            enrich_order(row)
            return jsonify({"ok": True, "row": row})
    return jsonify({"ok": False, "error": "Row not found."}), 404


@app.route("/api/review/<row_id>", methods=["DELETE"])
def api_review_delete(row_id):
    STORE["pending_review"] = [r for r in STORE["pending_review"] if r["id"] != row_id]
    return jsonify({"ok": True})


@app.route("/api/review/add", methods=["POST"])
def api_review_add():
    products = STORE["products"]
    customers = STORE["customers"]
    if not products or not customers:
        return jsonify({"ok": False, "error": "No product/customer catalog available."}), 400
    row = simulate_extraction("manual-entry", products, customers, count=1)[0]
    saved_cost = get_product_cost(session.get("user_email", DEMO_EMAIL), row.get("sku", ""))
    if saved_cost is not None:
        row["purchase_cost"] = saved_cost
        row["cost_source"] = "saved"
        enrich_order(row)
    else:
        row["cost_source"] = "manual"
    STORE["pending_review"].append(row)
    return jsonify({"ok": True, "row": row})


@app.route("/api/product-cost/<sku>")
def api_product_cost(sku):
    email = session.get("user_email")
    if not email:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    cost = get_product_cost(email, sku)
    return jsonify({"ok": True, "sku": sku, "purchase_cost": cost, "found": cost is not None})


@app.route("/api/review/save", methods=["POST"])
def api_review_save():
    """Commit all pending-review rows into the main Orders store."""
    if not STORE["pending_review"]:
        return jsonify({"ok": False, "error": "Some required fields are missing. Please review the extracted order."}), 400

    saved = 0
    for row in STORE["pending_review"]:
        order = dict(row)
        order["id"] = f"ORD{5000 + len(STORE['orders']) + saved}"
        order["sub_order_id"] = f"{order['id']}-1"
        order["status"] = "Processing"
        order.pop("source_file", None)
        enrich_order(order)
        STORE["orders"].insert(0, order)
        saved += 1

    STORE["pending_review"] = []
    recompute_customers(STORE["orders"], STORE["customers"])
    return jsonify({"ok": True, "saved": saved})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.route("/api/orders")
def api_orders():
    orders = STORE["orders"]
    q = request.args.get("q", "").lower().strip()
    city = request.args.get("city", "")
    product = request.args.get("product", "")
    status = request.args.get("status", "")
    profit_filter = request.args.get("profit", "")  # positive/negative/warning
    sort_by = request.args.get("sort_by", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    def matches(o):
        if q and q not in o["id"].lower() and q not in o["product_name"].lower() and q not in o["customer_name"].lower():
            return False
        if city and o["city"] != city:
            return False
        if product and o["product_name"] != product:
            return False
        if status and o["status"] != status:
            return False
        if profit_filter == "positive" and o["profit"] <= 0:
            return False
        if profit_filter == "negative" and o["profit"] >= 0:
            return False
        if date_from and o["date"] < date_from:
            return False
        if date_to and o["date"] > date_to:
            return False
        return True

    filtered = [o for o in orders if matches(o)]

    if sort_by == "revenue_desc":
        filtered.sort(key=lambda o: o["revenue"], reverse=True)
    elif sort_by == "revenue_asc":
        filtered.sort(key=lambda o: o["revenue"])
    elif sort_by == "profit_desc":
        filtered.sort(key=lambda o: o["profit"], reverse=True)
    elif sort_by == "profit_asc":
        filtered.sort(key=lambda o: o["profit"])
    elif sort_by == "date_desc":
        filtered.sort(key=lambda o: o["date"], reverse=True)

    return jsonify({
        "orders": filtered,
        "count": len(filtered),
        "cities": sorted({o["city"] for o in orders}),
        "products": sorted({o["product_name"] for o in orders}),
        "statuses": sorted({o["status"] for o in orders}),
    })


@app.route("/api/orders/<order_id>", methods=["PUT"])
def api_order_update(order_id):
    data = request.get_json(force=True, silent=True) or {}
    order = next((o for o in STORE["orders"] if o.get("id") == order_id), None)
    if not order:
        return jsonify({"ok": False, "error": "Order not found."}), 404

    allowed = ("status", "payment_state", "payment_status", "refund_amount",
               "return_shipping", "shipping", "other_cost", "platform_fee", "tax")
    for key in allowed:
        if key in data:
            if key in {"payment_status", "refund_amount", "return_shipping", "shipping", "other_cost", "platform_fee", "tax"}:
                try:
                    order[key] = float(data[key] or 0)
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": f"{key} must be a valid number."}), 400
            else:
                order[key] = data[key]
    enrich_order(order)
    return jsonify({"ok": True, "order": order})


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@app.route("/api/products", methods=["GET"])
def api_products_list():
    return jsonify(STORE["products"])


@app.route("/api/products", methods=["POST"])
def api_products_create():
    data = request.get_json(force=True, silent=True) or {}
    required = ["name", "category", "sku", "purchase_price", "selling_price", "stock", "supplier"]
    if not all(k in data and str(data[k]) != "" for k in required):
        return jsonify({"ok": False, "error": "Some required fields are missing."}), 400
    if float(data["selling_price"]) < float(data["purchase_price"]):
        return jsonify({"ok": False, "error": "Selling price must be greater than or equal to purchase price."}), 400
    if int(data["stock"]) < 0:
        return jsonify({"ok": False, "error": "Stock cannot be negative."}), 400

    pid = f"P{1000 + len(STORE['products'])}"
    product = {
        "id": pid,
        "name": data["name"],
        "category": data["category"],
        "sku": data["sku"],
        "purchase_price": float(data["purchase_price"]),
        "selling_price": float(data["selling_price"]),
        "stock": int(data["stock"]),
        "supplier": data["supplier"],
    }
    product["profit_per_unit"] = product_profit_per_unit(product["purchase_price"], product["selling_price"])
    product["margin"] = product_margin(product["purchase_price"], product["selling_price"])
    STORE["products"].append(product)
    set_product_cost(session.get("user_email", DEMO_EMAIL), product["sku"], product["purchase_price"])
    return jsonify({"ok": True, "product": product})


@app.route("/api/products/<pid>", methods=["PUT"])
def api_products_update(pid):
    data = request.get_json(force=True, silent=True) or {}
    for p in STORE["products"]:
        if p["id"] == pid:
            sp = float(data.get("selling_price", p["selling_price"]))
            pp = float(data.get("purchase_price", p["purchase_price"]))
            if sp < pp:
                return jsonify({"ok": False, "error": "Selling price must be greater than or equal to purchase price."}), 400
            stock = int(data.get("stock", p["stock"]))
            if stock < 0:
                return jsonify({"ok": False, "error": "Stock cannot be negative."}), 400
            for k in ("name", "category", "sku", "supplier"):
                if k in data:
                    p[k] = data[k]
            p["purchase_price"] = pp
            p["selling_price"] = sp
            p["stock"] = stock
            p["profit_per_unit"] = product_profit_per_unit(pp, sp)
            p["margin"] = product_margin(pp, sp)
            set_product_cost(session.get("user_email", DEMO_EMAIL), p["sku"], pp)
            return jsonify({"ok": True, "product": p})
    return jsonify({"ok": False, "error": "Product not found."}), 404


@app.route("/api/products/<pid>", methods=["DELETE"])
def api_products_delete(pid):
    STORE["products"] = [p for p in STORE["products"] if p["id"] != pid]
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/api/customers")
def api_customers_list():
    return jsonify(STORE["customers"])


@app.route("/api/customers/<cid>")
def api_customer_detail(cid):
    customer = next((c for c in STORE["customers"] if c["id"] == cid), None)
    if not customer:
        return jsonify({"ok": False, "error": "Customer not found."}), 404
    history = [o for o in STORE["orders"] if o["customer_id"] == cid]
    return jsonify({"customer": customer, "orders": history})


# ---------------------------------------------------------------------------
# Excel reports
# ---------------------------------------------------------------------------
@app.route("/api/excel/generate", methods=["POST"])
@login_required
@premium_required
def api_excel_generate():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name") or f"{STORE['settings']['business_name']} Sales Report"
    orders = STORE["orders"]
    if not orders:
        return jsonify({"ok": False, "error": "We couldn't generate the report. Please try again."}), 400

    filepath, filename = generate_excel_report(orders, report_name=name.replace(" ", "_"))
    record = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "created": datetime.now().strftime("%d %b %Y"),
        "orders": len(orders),
        "type": "Excel",
        "filename": filename,
    }
    STORE["reports"].insert(0, record)
    return jsonify({"ok": True, "report": record})


@app.route("/api/excel/reports")
def api_excel_reports():
    return jsonify(STORE["reports"])


@app.route("/api/excel/export/<report_id>")
@login_required
@premium_required
def api_excel_export(report_id):
    record = next((r for r in STORE["reports"] if r["id"] == report_id), None)
    if not record:
        return jsonify({"ok": False, "error": "Report not found."}), 404
    filepath = os.path.join(REPORTS_DIR, record["filename"])
    if not os.path.exists(filepath):
        return jsonify({"ok": False, "error": "We couldn't generate the report. Please try again."}), 404
    return send_file(filepath, as_attachment=True, download_name=record["filename"])


# ---------------------------------------------------------------------------
# Seller Assistant
# ---------------------------------------------------------------------------
@app.route("/api/assistant/ask", methods=["POST"])
def api_assistant_ask():
    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question", "")
    if not question.strip():
        return jsonify({"ok": False, "error": "Please type a question."}), 400
    answer = answer_question(question, STORE["orders"], STORE["products"], STORE["customers"])
    return jsonify({"ok": True, "answer": answer})


# ---------------------------------------------------------------------------
# Subscription / Pricing
# ---------------------------------------------------------------------------
@app.route("/api/subscription")
def api_subscription():
    key = current_plan()
    plan = PLANS[key]
    return jsonify({"ok": True, "plan_key": key, "plan": plan})


@app.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    data = request.get_json(force=True, silent=True) or {}
    plan = data.get("plan")
    if plan not in ("premium_monthly", "premium_yearly"):
        return jsonify({"ok": False, "error": "Choose a valid Premium plan."}), 400
    # Demo billing only: no money is charged. Real gateway can be connected later.
    session["plan"] = plan
    return jsonify({"ok": True, "message": f"{PLANS[plan]['name']} activated for this demo session.", "plan": PLANS[plan]})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(STORE["settings"])


@app.route("/api/settings", methods=["POST"])
def api_settings_update():
    data = request.get_json(force=True, silent=True) or {}
    STORE["settings"].update({k: v for k, v in data.items() if k in STORE["settings"]})
    return jsonify({"ok": True, "settings": STORE["settings"]})


# ---------------------------------------------------------------------------
# Business overview
# ---------------------------------------------------------------------------
@app.route("/api/business-overview")
def api_business_overview():
    orders = STORE["orders"]
    kpi = aggregate_orders(orders)
    repeat_customers = len([c for c in STORE["customers"] if c["order_count"] > 1])
    top_customers = sorted(STORE["customers"], key=lambda c: c["total_revenue"], reverse=True)[:5]
    return jsonify({
        "plan": PLANS[current_plan()],
        "business_numbers": kpi,
        "customer": {
            "count": len(STORE["customers"]),
            "repeat_customers": repeat_customers,
            "top_customers": top_customers,
        },
        "marketing": {
            "orders_from_marketing": round(len(orders) * 0.34),
            "marketing_cost": 18500,
            "marketing_revenue": 62300,
            "marketing_roi": round(((62300 - 18500) / 18500) * 100, 1) if 18500 else 0,
        },
        "future_goals": [
            "Increase monthly revenue by 25%",
            "Improve profit margin above 35%",
            "Reduce shipping costs by 15%",
            "Expand into 3 new product categories",
            "Automate 80% of seller operations",
        ],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)