"""Centralized business calculations for SellerPilot."""

def compute_margin(profit, revenue):
    return round((profit / revenue) * 100, 2) if revenue else 0.0


def product_profit_per_unit(purchase_price, selling_price):
    return round(float(selling_price) - float(purchase_price), 2)


def product_margin(purchase_price, selling_price):
    return compute_margin(product_profit_per_unit(purchase_price, selling_price), float(selling_price))


def enrich_order(order):
    qty = max(0, int(order.get("quantity", 1)))
    selling_price = float(order.get("selling_price", 0))
    purchase_cost = float(order.get("purchase_cost", 0))
    shipping = float(order.get("shipping", 0))
    packaging = float(order.get("packaging", 0))
    platform_fee = float(order.get("platform_fee", 0))
    tax = float(order.get("tax", 0))
    other_cost = float(order.get("other_cost", 0))
    refund_amount = float(order.get("refund_amount", 0) or 0)
    return_shipping = float(order.get("return_shipping", 0) or 0)

    revenue = round(selling_price * qty, 2)
    explicit_settlement = order.get("payment_status", None)
    settlement = float(explicit_settlement) if explicit_settlement not in (None, "") else revenue

    # A returned/refunded order keeps its history but removes the refunded
    # amount from realized revenue and adds return shipping to the cost.
    is_returned = str(order.get("status", "")).strip().lower() in {"return", "returned", "refunded"}
    realized_settlement = max(0.0, settlement - refund_amount) if is_returned else settlement

    if explicit_settlement not in (None, "") or is_returned:
        profit = round(
            realized_settlement - purchase_cost - shipping - packaging - other_cost - return_shipping,
            2,
        )
        total_cost = round(revenue - profit, 2)
    else:
        total_cost = round(
            purchase_cost + shipping + packaging + platform_fee + tax + other_cost,
            2,
        )
        profit = round(revenue - total_cost, 2)

    order.update({
        "quantity": qty,
        "selling_price": round(selling_price, 2),
        "purchase_cost": round(purchase_cost, 2),
        "shipping": round(shipping, 2),
        "packaging": round(packaging, 2),
        "platform_fee": round(platform_fee, 2),
        "tax": round(tax, 2),
        "other_cost": round(other_cost, 2),
        "payment_status": round(settlement, 2),
        "refund_amount": round(refund_amount, 2),
        "return_shipping": round(return_shipping, 2),
        "net_settlement": round(realized_settlement, 2),
        "revenue": revenue,
        "total_cost": total_cost,
        "profit": profit,
        "margin": compute_margin(profit, revenue),
    })
    return order


def aggregate_orders(orders):
    revenue = round(sum(float(o.get("revenue", 0)) for o in orders), 2)
    total_cost = round(sum(float(o.get("total_cost", 0)) for o in orders), 2)
    profit = round(revenue - total_cost, 2)
    return {
        "revenue": revenue,
        "total_cost": total_cost,
        "profit": profit,
        "margin": compute_margin(profit, revenue),
        "orders": len(orders),
    }
