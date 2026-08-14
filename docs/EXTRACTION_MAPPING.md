# SellerPilot extraction mapping

The prototype is based on a real Meesho label sample supplied for the project.

## Label → internal fields

- Customer Address → customer_name, address, city/state/pincode
- Shipment code (e.g. VL...) → tracking_id
- Product Details → size, quantity, color
- Purchase Order No. → order_id
- Invoice No. → invoice_no
- Order Date / Invoice Date → date fields
- Sold by / GSTIN → seller_name, gstin
- HSN → hsn
- Invoice total → payment_status (label-only estimate)
- Invoice total → selling_price for the demo workbook
- Seller-entered cost price → purchase_cost
- Net Profit → payment_status - purchase_cost - any extra direct costs entered in Review

## Important limitation

A customer label does not contain the seller's purchase cost or necessarily the marketplace settlement statement. SellerPilot therefore asks the seller to review/enter cost data and treats the label's invoice total as an estimated settlement in this demo. Production marketplace connectors can replace that estimate with actual settlement data.
