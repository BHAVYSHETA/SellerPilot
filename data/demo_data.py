"""Deterministic demo dataset for SellerPilot's presentation mode."""
from datetime import date, timedelta
from services.calculations import enrich_order

PRODUCT_SEEDS = [
    ("Wireless Mouse","Electronics",180,499,120,"TechSource","SP-MOU-001"),
    ("4-in-1 Car Charger","Automotive",210,599,85,"AutoGear","SP-CAR-002"),
    ("Body Shaper","Fashion",260,699,60,"FitWear","SP-BOD-003"),
    ("Hair Dryer 1800W","Beauty",520,999,45,"NovaSupply","SP-HDR-004"),
    ("Yoga Resistance Bands","Fitness",140,399,150,"FlexMart","SP-YOG-005"),
    ("Shoe Repair Glue","Home & Utility",65,199,200,"FixPro","SP-GLU-006"),
    ("LED Desk Lamp","Home & Utility",310,749,70,"BrightHub","SP-LMP-007"),
    ("Phone Stand","Electronics",90,249,180,"MobileMart","SP-STD-008"),
    ("USB-C Cable","Electronics",75,199,240,"CableWorks","SP-CBL-009"),
    ("Mini Tripod","Electronics",220,499,95,"PhotoPoint","SP-TRI-010"),
    ("Hair Color Stick","Beauty",95,299,130,"GlowCare","SP-HCS-011"),
    ("Kitchen Organizer","Home & Utility",170,449,90,"HomeNest","SP-KIT-012"),
    ("Travel Bottle Set","Travel",110,299,160,"PackEasy","SP-BOT-013"),
    ("Neck Pillow","Travel",230,549,80,"ComfortCo","SP-NCK-014"),
    ("Car Cleaning Kit","Automotive",190,449,75,"AutoGear","SP-CLK-015"),
    ("Resistance Tube Set","Fitness",160,449,100,"FlexMart","SP-RES-016"),
    ("Makeup Organizer","Beauty",280,699,55,"GlowCare","SP-MAK-017"),
    ("Laptop Sleeve","Fashion",240,649,65,"UrbanCarry","SP-SLV-018"),
    ("Reusable Water Bottle","Fitness",150,399,140,"EcoGoods","SP-WAT-019"),
    ("Bluetooth Speaker","Electronics",650,1199,35,"SoundHub","SP-SPK-020"),
]

CUSTOMER_SEEDS = [
    ("Aarav Shah","Ahmedabad","Gujarat"),("Diya Patel","Surat","Gujarat"),
    ("Vivaan Mehta","Vadodara","Gujarat"),("Anaya Desai","Rajkot","Gujarat"),
    ("Rohan Verma","Mumbai","Maharashtra"),("Ishita Joshi","Pune","Maharashtra"),
    ("Arjun Gupta","Delhi","Delhi"),("Myra Singh","Jaipur","Rajasthan"),
    ("Kabir Jain","Indore","Madhya Pradesh"),("Sara Khan","Lucknow","Uttar Pradesh"),
    ("Reyansh Shah","Ahmedabad","Gujarat"),("Kiara Patel","Surat","Gujarat"),
    ("Aditya Mehta","Vadodara","Gujarat"),("Avni Desai","Rajkot","Gujarat"),
    ("Dhruv Shah","Mumbai","Maharashtra"),("Meera Joshi","Pune","Maharashtra"),
    ("Atharv Gupta","Delhi","Delhi"),("Aadhya Singh","Jaipur","Rajasthan"),
    ("Yash Jain","Indore","Madhya Pradesh"),("Zoya Khan","Lucknow","Uttar Pradesh"),
    ("Manav Shah","Ahmedabad","Gujarat"),("Navya Patel","Surat","Gujarat"),
    ("Krish Mehta","Vadodara","Gujarat"),("Ira Desai","Rajkot","Gujarat"),
    ("Rudra Verma","Mumbai","Maharashtra"),("Tara Joshi","Pune","Maharashtra"),
    ("Dev Gupta","Delhi","Delhi"),("Siya Singh","Jaipur","Rajasthan"),
    ("Ayan Jain","Indore","Madhya Pradesh"),("Alina Khan","Lucknow","Uttar Pradesh"),
]

def build_demo_dataset():
    products=[]
    for i,(name,cat,pp,sp,stock,supplier,sku) in enumerate(PRODUCT_SEEDS, start=1):
        products.append({
            "id": f"P{i:04d}", "name": name, "category": cat, "sku": sku,
            "purchase_price": pp, "selling_price": sp, "stock": stock, "supplier": supplier,
            "profit_per_unit": round(sp-pp,2),
            "margin": round((sp-pp)/sp*100,2),
        })

    customers=[]
    for i,(name,city,state) in enumerate(CUSTOMER_SEEDS, start=1):
        customers.append({
            "id": f"C{i:04d}", "name": name, "city": city, "state": state,
            "order_count": 0, "total_revenue": 0.0, "total_profit": 0.0,
            "last_order_date": None,
        })

    orders=[]
    base=date.today()-timedelta(days=29)
    for i in range(50):
        p=products[i % len(products)]
        c=customers[(i*7) % len(customers)]
        qty=1 if i%4 else 2
        # Make a few orders deliberately loss-making by increasing fees/shipping.
        shipping=55 + (i%5)*8
        packaging=15 + (i%3)*3
        platform_fee=round(p["selling_price"]*qty*(0.03 + (i%4)*0.005),2)
        tax=round(p["selling_price"]*qty*0.05,2)
        if i in (11, 27, 42):
            shipping += 180
            platform_fee += 50
        order={
            "id": f"ORD{5000+i}",
            "sub_order_id": f"ORD{5000+i}-1",
            "date": (base+timedelta(days=i%30)).isoformat(),
            "product_id": p["id"], "product_name": p["name"], "sku": p["sku"],
            "customer_id": c["id"], "customer_name": c["name"], "city": c["city"], "state": c["state"],
            "pincode": str(380000 + ((i*137)%60000)),
            "quantity": qty, "selling_price": p["selling_price"],
            "purchase_cost": round(p["purchase_price"]*qty,2),
            "shipping": shipping, "packaging": packaging,
            "platform_fee": platform_fee, "tax": tax, "other_cost": 0,
            "advertising": 0, "return_cost": 0,
            "status": ["Delivered","Delivered","Shipped","Processing","Returned"][i%5],
        }
        enrich_order(order)
        orders.append(order)
    recompute_customers(orders, customers)
    return products, customers, orders

def recompute_customers(orders, customers):
    for c in customers:
        c.update(order_count=0,total_revenue=0.0,total_profit=0.0,last_order_date=None)
    by_id={c["id"]:c for c in customers}
    for o in orders:
        c=by_id.get(o.get("customer_id"))
        if not c: continue
        c["order_count"] += 1
        c["total_revenue"] = round(c["total_revenue"]+o.get("revenue",0),2)
        c["total_profit"] = round(c["total_profit"]+o.get("profit",0),2)
        if not c["last_order_date"] or o["date"] > c["last_order_date"]:
            c["last_order_date"]=o["date"]
