# Architecture & Design Note: Order-to-Audit System
**Target Business:** Packaged Food Manufacturer (Murukku, Sweets, Snacks)  
**Evaluation:** NIT Tiruchirappalli Centre for Digital Infrastructure

---

## 1. Entity-Relationship Data Model

The data model enforces relational referential integrity (`PRAGMA foreign_keys = ON`), audit trails, and double-entry stock accounting:

```
[items]
 ├── id, code, name, category ('RAW_MATERIAL' | 'PACKAGING' | 'FINISHED_GOODS')
 └── uom, standard_rate_paise, hsn_code, gst_rate_pct, reorder_level

[bom] 1 ──── * [bom_items] * ──── 1 [items]
 ├── id, finished_good_id, batch_size_packets

[customers]
 ├── id, code, name, type ('RETAILER' | 'DISTRIBUTOR'), state, gstin, phone

[sales_orders] 1 ──── * [sales_order_items] * ──── 1 [items]
 ├── id, order_no, salesman_name, customer_id, status

[invoices] 1 ──── * [invoice_items]
 ├── id, invoice_no, order_id, customer_id, place_of_supply, is_interstate
 └── taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_amount_paise, status

[production_runs] 1 ──── * [production_run_items]
 ├── id, run_no, bom_id, product_id, planned_batch_size, actual_output_packets
 └── yield_variance_pct, labour_cost_paise, power_gas_cost_paise, total_batch_cost_paise

[stock_ledger]  <--- IMMUTABLE LEDGER
 ├── id, item_id, movement_type, source_doc_type, source_doc_id
 └── qty_change (+/-), balance_after, uom, unit_rate_paise, created_at

[payments]
 ├── id, payment_no, customer_id, invoice_id, amount_paise, mode, reference
```

---

## 2. Stock Ledger & Inventory Accounting Invariant

Stock balances are never overwritten directly. For any item $i$:
$$\text{Current Balance}(i) = \sum \text{qty\_change for item } i \quad \text{across all historical ledger entries}$$

The invariant strictly enforced and tested is:
$$\text{Closing Balance} = \text{Opening Balance} + \text{Inward Receipts} - \text{Outward Issues/Sales} \pm \text{Adjustments}$$

### Source Document Traceability:
* **Purchases:** Inward `PURCHASE_RECEIPT` linked to `PO-xxxx`.
* **Production Run Issues:** Outward `PRODUCTION_ISSUE` for raw materials and `PACKAGING_CONSUMPTION` / `PACKAGING_SCRAP` linked to `RUN-xxxx`.
* **Production Receipts:** Inward `PRODUCTION_RECEIPT` for Finished Goods linked to `RUN-xxxx`.
* **Sales Invoicing & Dispatch:** Outward `DISPATCH` linked to `INV-xxxx`.

---

## 3. Bill of Materials (BOM) & Variance Computation

For a production run of expected yield $Y_{\text{std}}$ and actual output $Y_{\text{act}}$:
$$\text{Yield Variance (\%)} = \frac{Y_{\text{act}} - Y_{\text{std}}}{Y_{\text{std}}} \times 100 = \frac{188 - 200}{200} \times 100 = \mathbf{-6.0\%}$$

For each ingredient $m$ with standard planned quantity $Q_{\text{std}}$ and actual issue $Q_{\text{act}}$:
$$\text{Material Consumption Variance (\%)} = \frac{Q_{\text{act}} - Q_{\text{std}}}{Q_{\text{std}}} \times 100$$
*For Cooking Oil:* Standard $= 10.0\text{ L}$, Actual $= 10.5\text{ L} \implies \frac{10.5 - 10.0}{10.0} \times 100 = \mathbf{+5.0\%}$ (Flagged).

---

## 4. Costing & Valuation Methodology

### Material Valuation Method: FIFO (First-In, First-Out)
* **Flour:** $40\text{ kg}$ issued from opening stock ($100\text{ kg}$ @ ₹42/kg) $= ₹1,680.00$.
* **Cooking Oil:** $10.5\text{ L}$ @ ₹140/L $= ₹1,470.00$.
* **Spice Mix:** $1.2\text{ kg}$ @ ₹200/kg $= ₹240.00$.
* **Pouches:** $194\text{ pouches}$ ($188\text{ good} + 6\text{ scrap}$) @ ₹2.50 $= ₹485.00$.
* **Cartons:** $9\text{ cartons}$ @ ₹15.00 $= ₹135.00$.
* **Total Direct Material Cost:** $1680 + 1470 + 240 + 485 + 135 = \mathbf{₹4,010.00}$.

### Overhead Allocation Method: Direct Batch Assignment
* **Direct Labour:** $₹1,200.00$
* **Direct Power & Gas Utilities:** $₹600.00$
* **Total Direct Overheads:** $\mathbf{₹1,800.00}$

### Total Batch Cost & Unit Packet Cost
$$\text{Total Batch Cost} = ₹4,010.00 + ₹1,800.00 = \mathbf{₹5,810.00}$$
$$\text{Cost per Packet} = \frac{\text{Total Batch Cost}}{\text{Actual Output Packets}} = \frac{₹5,810.00}{188} = \mathbf{₹30.90\text{ / packet}}$$
$$\text{Gross Margin} = \frac{₹50.00 - ₹30.90}{₹50.00} \times 100 = \mathbf{38.2\%}$$

---

## 5. Tax & Currency Precision
* All monetary values are maintained internally in **Integer Paise** (e.g. ₹187.50 is stored as `18750` paise).
* Intra-state supplies within Tamil Nadu calculate **CGST @ 2.5%** and **SGST @ 2.5%**.
* Inter-state supplies (Karnataka) calculate **IGST @ 5.0%**.
* Floating-point drift is mathematically prevented throughout all calculations.
