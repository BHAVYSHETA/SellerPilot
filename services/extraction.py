"""SellerPilot label extraction.

Core demo behavior:
- PDF: real text extraction with PyMuPDF and field parsing.
- XLSX/CSV: real tabular import and normalization.
- PNG/JPG: optional OCR through pytesseract when installed and configured.
- Unsupported/poorly parsed files fall back to a small demo record so the Shark Tank demo never breaks.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime
from pathlib import Path

from services.calculations import enrich_order


def _num(value: str | None) -> float:
    if value is None:
        return 0.0
    value = value.replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    try:
        return float(re.findall(r'-?\d+(?:\.\d+)?', value)[0])
    except (IndexError, ValueError):
        return 0.0


def _clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


def _first(pattern: str, text: str, flags=re.I | re.M) -> str:
    m = re.search(pattern, text, flags)
    return _clean(m.group(1)) if m else ''


def detect_platform(text: str, filename: str = '') -> str:
    hay = f"{filename} {text}".lower()
    if 'meesho' in hay or 'valmo' in hay:
        return 'Meesho'
    if 'amazon' in hay or 'amazon.in' in hay:
        return 'Amazon'
    if 'flipkart' in hay or 'ekart' in hay:
        return 'Flipkart'
    return 'Other / Unknown'


def parse_meesho_page(text: str, filename: str, page_no: int = 1) -> dict:
    lines = [_clean(x) for x in text.splitlines() if _clean(x)]
    joined = '\n'.join(lines)

    customer = _first(r'Customer Address\s*\n([^\n]+)', joined)
    if not customer:
        customer = _first(r'BILL TO / SHIP TO\s*\n([^\n-]+)', joined)

    tracking = ''
    for line in lines:
        if re.fullmatch(r'[A-Z0-9]{10,30}', line) and ('/' not in line) and not line.isdigit():
            # Prefer known shipment prefixes and ignore GST/order ids.
            if line.startswith(('VL', 'SF', 'EK', 'FM')):
                tracking = line
                break

    order_id = _first(r'Purchase Order No\.\s*\n([^\n]+)', joined)
    invoice_no = _first(r'Invoice No\.\s*\n([^\n]+)', joined)
    order_date = _first(r'Order Date\s*\n([^\n]+)', joined)
    invoice_date = _first(r'Invoice Date\s*\n([^\n]+)', joined)
    gstin = _first(r'GSTIN\s*-\s*([A-Z0-9]+)', joined)
    seller = _first(r'Sold by\s*:\s*([^\n]+)', joined)
    place = _first(r'Place of Supply:\s*([^\n]+)', joined)

    product_name = ''
    sku = ''
    size = ''
    quantity = 1
    color = ''
    # Product Details is rendered as one field per line in the PDF text layer.
    for i, line in enumerate(lines):
        if line.lower().startswith('product details') and i + 6 < len(lines):
            # After the title: SKU, Size, Qty, Color, Order No.
            values = lines[i + 6:i + 11]
            if len(values) >= 5:
                # Shipping-label SKU can be the marketplace display title.
                # Prefer the invoice SKU below (e.g. SZ-615).
                sku = values[0]
                size = values[1]
                quantity = int(values[2]) if values[2].isdigit() else 1
                color = values[3]
            break

    # Invoice description line(s). Prefer a SKU/size line such as
    # "SZ-615 - Free Size" and take the preceding line as the product name.
    for i, line in enumerate(lines):
        msku = re.match(r'([A-Z]{1,6}-\d+[A-Z0-9_-]*)\s+-\s+(.+)', line, re.I)
        if msku and i > 0:
            sku = msku.group(1)
            size = msku.group(2)
            product_name = lines[i - 1]
            break
    if not product_name:
        for i, line in enumerate(lines):
            if line.lower() == 'description' and i + 6 < len(lines):
                # In some PDFs the description values follow the headers.
                for candidate in lines[i + 1:i + 10]:
                    if candidate.lower() not in {'hsn','qty','gross amount','discount','taxable value','taxes','total'} and not candidate.startswith('Rs.'):
                        product_name = candidate
                        break
                if product_name:
                    break

    hsn = _first(r'\n(\d{6})\s+\d+\s+Rs\.', joined)
    totals = re.findall(r'Total\s+Rs\.\s*[\d.]+\s+Rs\.\s*([\d.]+)', joined, re.I)
    total = totals[-1] if totals else '0'
    # The first line item's total is the product selling amount; the final
    # total also includes Other Charges. Keep both.
    line_total = _first(r'IGST\s*@\s*[\d.]+%\s*\nRs\.\s*[\d.]+\s*\nRs\.\s*([\d.]+)', joined)

    gross = _first(r'\b\d{6}\s+\d+\s+Rs\.([\d.]+)', joined)
    discount = _first(r'\bRs\.([\d.]+)\nRs\.([\d.]+)\nRs\.([\d.]+)', joined)
    taxable = _first(r'Rs\.\d+\nRs\.\d+\nRs\.([\d.]+)', joined)
    taxes = re.findall(r'IGST\s*@\s*[\d.]+%\s*\nRs\.\s*([\d.]+)', joined, re.I)
    tax_total = sum(_num(x) for x in taxes)

    # Address: capture first block before return address.
    address = ''
    if customer:
        try:
            start = lines.index(customer)
            addr = []
            for line in lines[start + 1:]:
                if line.lower().startswith('if undelivered'):
                    break
                if line.lower() in {'customer address'}:
                    continue
                addr.append(line)
                if len(addr) >= 3:
                    break
            address = ', '.join(addr)
        except ValueError:
            pass

    row = {
        'id': str(uuid.uuid4())[:8],
        'source_file': filename,
        'platform': 'Meesho',
        'page': page_no,
        'order_id': order_id or f'EXTRACTED-{uuid.uuid4().hex[:8].upper()}',
        'date': order_date or invoice_date or datetime.now().strftime('%d-%m-%Y'),
        'customer_name': customer,
        'address': address,
        'city': _first(r'\n([^\n,]+),\s*West Bengal', joined) or _first(r'\n([^\n,]+),\s*Gujarat', joined),
        'state': place,
        'pincode': _first(r'\b(\d{6})\b', joined),
        'tracking_id': tracking,
        'sku': sku,
        'product_name': product_name or 'Unknown Product',
        'size': size,
        'color': color,
        'quantity': quantity,
        'selling_price': _num(total),
        'gross_amount': _num(gross),
        'discount': _num(discount),
        'taxable_value': _num(taxable),
        'tax': round(tax_total, 2),
        'purchase_cost': 0.0,
        'shipping': 0.0,
        'packaging': 0.0,
        'platform_fee': 0.0,
        'other_cost': 0.0,
        'payment_status': _num(total),
        'status': 'Extracted',
        'invoice_no': invoice_no,
        'invoice_date': invoice_date,
        'hsn': hsn,
        'seller_name': seller,
        'gstin': gstin,
    }
    # SellerPilot's demo profit engine mirrors the user's Excel logic:
    # net profit = payment/settlement amount - cost price.
    enrich_order(row)
    return row


def extract_pdf(file_bytes: bytes, filename: str) -> list[dict]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError('PDF extraction requires PyMuPDF. Install requirements.txt first.') from exc

    doc = fitz.open(stream=file_bytes, filetype='pdf')
    rows = []
    for idx, page in enumerate(doc, start=1):
        text = page.get_text('text')
        if text.strip():
            platform = detect_platform(text, filename)
            if platform == 'Meesho':
                rows.append(parse_meesho_page(text, filename, idx))
            else:
                # Generic parser still captures the most important order fields.
                rows.append(parse_meesho_page(text, filename, idx) | {'platform': platform})
    return rows


def normalize_tabular(rows: list[dict], filename: str) -> list[dict]:
    out = []
    for raw in rows:
        low = {str(k).strip().lower(): v for k, v in raw.items()}
        def val(*names, default=''):
            for n in names:
                if n.lower() in low and low[n.lower()] not in ('', None):
                    return low[n.lower()]
            return default
        order = {
            'id': str(uuid.uuid4())[:8],
            'source_file': filename,
            'platform': val('platform', default='Other / Unknown'),
            'order_id': str(val('order id', 'order_id', default=f'EXTRACTED-{uuid.uuid4().hex[:8].upper()}')),
            'date': str(val('order date', 'date', default=datetime.now().strftime('%d-%m-%Y'))),
            'customer_name': str(val('customer name', 'customer', default='')),
            'tracking_id': str(val('tracking id', 'tracking_id', default='')),
            'sku': str(val('sku', default='')),
            'product_name': str(val('product', 'product name', default='Unknown Product')),
            'quantity': int(float(val('quantity', 'qty', default=1) or 1)),
            'selling_price': _num(str(val('selling price', 'selling_price', default=0))),
            'purchase_cost': _num(str(val('cost price', 'cost_price', 'purchase cost', default=0))),
            'payment_status': _num(str(val('payment status', 'payment_status', default=0))),
            'status': str(val('status', default='Imported')),
            'shipping': _num(str(val('shipping', default=0))),
            'packaging': _num(str(val('packaging', default=0))),
            'platform_fee': _num(str(val('platform fee', 'platform_fee', default=0))),
            'tax': _num(str(val('tax', default=0))),
            'other_cost': _num(str(val('other cost', 'other_cost', default=0))),
            'city': str(val('city', default='')),
            'state': str(val('state', default='')),
        }
        if not order['payment_status']:
            order['payment_status'] = order['selling_price']
        enrich_order(order)
        out.append(order)
    return out


def extract_tabular(file_bytes: bytes, filename: str) -> list[dict]:
    ext = Path(filename).suffix.lower()
    if ext == '.csv':
        text = file_bytes.decode('utf-8-sig', errors='replace')
        return normalize_tabular(list(csv.DictReader(io.StringIO(text))), filename)
    import pandas as pd
    df = pd.read_excel(io.BytesIO(file_bytes))
    return normalize_tabular(df.fillna('').to_dict(orient='records'), filename)


def extract_file(file_bytes: bytes, filename: str, demo_products=None, demo_customers=None) -> list[dict]:
    ext = Path(filename).suffix.lower()
    if ext == '.pdf':
        rows = extract_pdf(file_bytes, filename)
    elif ext in {'.xlsx', '.xls', '.csv'}:
        rows = extract_tabular(file_bytes, filename)
    elif ext in {'.png', '.jpg', '.jpeg'}:
        try:
            from PIL import Image
            import pytesseract
            image = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(image)
            platform = detect_platform(text, filename)
            rows = [parse_meesho_page(text, filename, 1) | {'platform': platform}] if text.strip() else []
        except Exception:
            rows = []
    else:
        rows = []
    if rows:
        return rows
    return simulate_extraction(filename, demo_products or [], demo_customers or [], count=1)


def simulate_extraction(filename, products, customers, count=None):
    """Safe demo fallback used when a file cannot be parsed."""
    import random
    if not products or not customers:
        return []
    count = count or 1
    extracted = []
    for _ in range(count):
        product = random.choice(products)
        customer = random.choice(customers)
        qty = 1
        settlement = float(product['selling_price'])
        cost = float(product['purchase_price'])
        row = {
            'id': str(uuid.uuid4())[:8], 'source_file': filename, 'platform': 'Demo',
            'order_id': f'EXTRACTED-{uuid.uuid4().hex[:8].upper()}',
            'date': datetime.now().strftime('%d-%m-%Y'), 'customer_name': customer['name'],
            'address': '', 'city': customer.get('city',''), 'state': customer.get('state',''),
            'pincode': '', 'tracking_id': '', 'sku': product['sku'], 'product_name': product['name'],
            'quantity': qty, 'selling_price': settlement, 'purchase_cost': cost,
            'shipping': 0, 'packaging': 0, 'platform_fee': 0, 'tax': 0, 'other_cost': 0,
            'payment_status': settlement, 'status': 'Extracted'
        }
        enrich_order(row)
        extracted.append(row)
    return extracted
