"""
Rule-based 'Seller Assistant'. Answers plain-English questions using the
application's current in-memory dataset. No external AI call is made -
this mirrors what a real LLM-backed assistant would return.
"""


def _product_rollup(orders):
    rollup = {}
    for o in orders:
        key = o["product_name"]
        r = rollup.setdefault(key, {"revenue": 0, "profit": 0, "quantity": 0})
        r["revenue"] += o["revenue"]
        r["profit"] += o["profit"]
        r["quantity"] += o["quantity"]
    return rollup


def answer_question(question, orders, products, customers):
    q = question.lower().strip()
    revenue = round(sum(o["revenue"] for o in orders), 2)
    total_cost = round(sum(o["total_cost"] for o in orders), 2)
    profit = round(revenue - total_cost, 2)
    margin = round((profit / revenue) * 100, 2) if revenue else 0
    rollup = _product_rollup(orders)

    if "total profit" in q or ("profit" in q and "which" not in q and "product" not in q and "causing" not in q):
        return f"Your total profit across {len(orders)} orders is ₹{profit:,.0f}, a margin of {margin:.1f}%."

    if "highest margin" in q or ("margin" in q and "product" in q):
        best = max(products, key=lambda p: p["margin"], default=None)
        if best:
            return f"'{best['name']}' has your highest margin at {best['margin']:.1f}% (₹{best['profit_per_unit']:,.0f} profit per unit)."

    if "causing loss" in q or "losses" in q or "loss-making" in q or ("loss" in q and "product" in q):
        losers = {k: v for k, v in rollup.items() if v["profit"] < 0}
        if not losers:
            return "Good news — no products are currently loss-making."
        worst = min(losers.items(), key=lambda kv: kv[1]["profit"])
        return f"'{worst[0]}' is your biggest loss-maker, at ₹{worst[1]['profit']:,.0f} total loss across {int(worst[1]['quantity'])} units sold."

    if "shipping" in q:
        shipping_total = round(sum(o["shipping"] for o in orders), 2)
        pct = round((shipping_total / total_cost) * 100, 1) if total_cost else 0
        return f"You've spent ₹{shipping_total:,.0f} on shipping, which is {pct}% of your total costs."

    if "revenue" in q and "this month" in q:
        return f"Total revenue in the current dataset is ₹{revenue:,.0f}."
    if "revenue" in q:
        return f"Your total revenue is ₹{revenue:,.0f} across {len(orders)} orders."

    if "sold the most" in q or ("top" in q and "product" not in q and "5" not in q) or "best selling" in q or "highest-selling" in q or "highest selling" in q:
        if rollup:
            top = max(rollup.items(), key=lambda kv: kv[1]["quantity"])
            return f"'{top[0]}' sold the most, with {int(top[1]['quantity'])} units and ₹{top[1]['revenue']:,.0f} in revenue."

    if "top 5" in q or ("top" in q and "products" in q):
        top5 = sorted(rollup.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:5]
        lines = [f"{i+1}. {name} — ₹{v['revenue']:,.0f} revenue, ₹{v['profit']:,.0f} profit"
                 for i, (name, v) in enumerate(top5)]
        return "Your top 5 products by revenue:\n" + "\n".join(lines)

    if "customer" in q:
        if customers:
            top_c = max(customers, key=lambda c: c["total_revenue"])
            return f"Your best customer is {top_c['name']} from {top_c['city']}, with ₹{top_c['total_revenue']:,.0f} in total revenue across {top_c['order_count']} orders."

    return (f"Here's a quick snapshot: ₹{revenue:,.0f} revenue, ₹{profit:,.0f} profit "
            f"({margin:.1f}% margin) across {len(orders)} orders. Try asking about "
            f"'top products', 'shipping costs', or 'loss-making products'.")