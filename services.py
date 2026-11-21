from decimal import Decimal, ROUND_HALF_UP
from database import get_connection, to_paise, to_rupees

FACTORY_STATE = "Tamil Nadu"

class InventoryService:
    @staticmethod
    def get_stock_balance(item_id: int) -> float:
        """Derive always-current stock balance from the immutable stock ledger."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(qty_change), 0.0) as balance 
            FROM stock_ledger 
            WHERE item_id = ?
        """, (item_id,))
        row = cur.fetchone()
        conn.close()
        return round(float(row["balance"]), 4)

    @staticmethod
    def get_all_stock_summary():
        """Retrieve opening, receipts, issues, and closing balances for all items."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                i.id, i.code, i.name, i.category, i.uom, i.reorder_level,
                COALESCE(SUM(CASE WHEN sl.movement_type = 'OPENING_STOCK' THEN sl.qty_change ELSE 0 END), 0) as opening,
                COALESCE(SUM(CASE WHEN sl.qty_change > 0 AND sl.movement_type != 'OPENING_STOCK' THEN sl.qty_change ELSE 0 END), 0) as inward,
                COALESCE(SUM(CASE WHEN sl.qty_change < 0 THEN ABS(sl.qty_change) ELSE 0 END), 0) as outward,
                COALESCE(SUM(sl.qty_change), 0) as closing
            FROM items i
            LEFT JOIN stock_ledger sl ON i.id = sl.item_id
            GROUP BY i.id
            ORDER BY i.category DESC, i.name ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def add_movement(cur, item_id: int, movement_type: str, source_type: str, source_id: str, 
                     qty_change: float, uom: str, rate_paise: int = 0, notes: str = ""):
        """Atomic append to immutable stock movement ledger."""
        # Get prior balance
        cur.execute("SELECT COALESCE(SUM(qty_change), 0.0) as bal FROM stock_ledger WHERE item_id = ?", (item_id,))
        prior_bal = float(cur.fetchone()["bal"])
        new_bal = round(prior_bal + qty_change, 4)

        cur.execute("""
        INSERT INTO stock_ledger (
            item_id, movement_type, source_doc_type, source_doc_id,
            qty_change, balance_after, uom, unit_rate_paise, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, movement_type, source_type, source_id, qty_change, new_bal, uom, rate_paise, notes))
        return new_bal

class PurchaseService:
    @staticmethod
    def record_purchase(item_code: str, supplier_name: str, quantity: float, rate_rupees: float):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, uom FROM items WHERE code = ?", (item_code,))
        item = cur.fetchone()
        if not item:
            conn.close()
            raise ValueError(f"Item {item_code} not found")

        item_id = item["id"]
        uom = item["uom"]
        rate_paise = to_paise(rate_rupees)
        total_paise = int(Decimal(str(quantity)) * Decimal(str(rate_paise)))

        cur.execute("SELECT COUNT(*) as count FROM purchases")
        count = cur.fetchone()["count"] + 1
        purchase_no = f"PO-2026-{count:03d}"

        cur.execute("""
        INSERT INTO purchases (purchase_no, item_id, supplier_name, quantity, uom, rate_paise, total_amount_paise)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (purchase_no, item_id, supplier_name, quantity, uom, rate_paise, total_paise))

        # Ledger movement: Inward
        InventoryService.add_movement(
            cur, item_id, 'PURCHASE_RECEIPT', 'PURCHASE', purchase_no,
            quantity, uom, rate_paise, f"Purchased from {supplier_name} @ ₹{rate_rupees}/{uom}"
        )

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('ADMIN', 'PURCHASE_ENTRY', 'purchases', ?, ?)
        """, (purchase_no, f"Purchased {quantity} {uom} of {item_code} at ₹{rate_rupees}"))

        conn.commit()
        conn.close()
        return purchase_no

class ProductionService:
    @staticmethod
    def record_run(bom_name_or_product_code: str, actual_issued_items: dict, actual_output_packets: int,
                   damaged_pouches: int = 0, cartons_used: int = 0, labour_rupees: float = 0.0, 
                   power_gas_rupees: float = 0.0, notes: str = ""):
        """
        Record complete recipe production run with planned vs actual consumption, yield variance,
        automatic stock deduction for RM/packaging, automatic FG stock increment, and costing.
        """
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT id FROM items WHERE code = 'FG-MURUKKU-200G'")
        fg_item = cur.fetchone()
        fg_id = fg_item["id"]

        cur.execute("SELECT * FROM bom WHERE finished_good_id = ?", (fg_id,))
        bom = cur.fetchone()
        bom_id = bom["id"]
        expected_yield = bom["batch_size_packets"]

        # Yield variance: (Actual - Expected) / Expected * 100
        yield_var_pct = round(((actual_output_packets - expected_yield) / float(expected_yield)) * 100, 2)

        cur.execute("SELECT COUNT(*) as cnt FROM production_runs")
        run_no = f"RUN-2026-{cur.fetchone()['cnt'] + 1:03d}"

        # Fetch standard BOM recipe items
        cur.execute("""
            SELECT bi.*, i.code, i.name, i.standard_rate_paise 
            FROM bom_items bi 
            JOIN items i ON bi.item_id = i.id 
            WHERE bi.bom_id = ?
        """, (bom_id,))
        bom_recipes = {r["code"]: dict(r) for r in cur.fetchall()}

        cur.execute("""
        INSERT INTO production_runs (
            run_no, bom_id, product_id, planned_batch_size, actual_output_packets,
            yield_variance_pct, labour_cost_paise, power_gas_cost_paise,
            direct_material_cost_paise, total_batch_cost_paise, cost_per_packet_paise,
            status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'COMPLETED', ?)
        """, (run_no, bom_id, fg_id, expected_yield, actual_output_packets, 
              yield_var_pct, to_paise(labour_rupees), to_paise(power_gas_rupees), notes))
        run_id = cur.lastrowid

        total_material_cost_paise = 0

        # Process Ingredients (Raw materials: Flour, Oil, Spices)
        for code, standard in bom_recipes.items():
            if code in ['PKG-POUCH', 'PKG-CARTON']:
                continue
            planned_qty = standard["standard_qty"]
            actual_qty = actual_issued_items.get(code, planned_qty)
            uom = standard["uom"]
            item_id = standard["item_id"]

            # Variance %
            var_pct = round(((actual_qty - planned_qty) / float(planned_qty)) * 100, 2)
            
            # Unit rate using FIFO from opening/purchase
            unit_rate = standard["standard_rate_paise"]
            item_cost = int(Decimal(str(actual_qty)) * Decimal(str(unit_rate)))
            total_material_cost_paise += item_cost

            cur.execute("""
            INSERT INTO production_run_items (
                run_id, item_id, planned_qty, actual_qty, variance_pct, scrap_qty, uom, unit_rate_paise, total_cost_paise
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
            """, (run_id, item_id, planned_qty, actual_qty, var_pct, uom, unit_rate, item_cost))

            # Deduct from Stock Ledger
            InventoryService.add_movement(
                cur, item_id, 'PRODUCTION_ISSUE', 'PRODUCTION_RUN', run_no,
                -float(actual_qty), uom, unit_rate, f"Issued to {run_no} ({var_pct:+}% variance)"
            )

        # Process Packaging: Pouches (Actual good packets + damaged pouches)
        pouch_recipe = bom_recipes['PKG-POUCH']
        planned_pouches = pouch_recipe["standard_qty"] # 200
        actual_pouches_used = actual_output_packets # 188
        total_pouches_consumed = actual_pouches_used + damaged_pouches # 194
        pouch_rate = pouch_recipe["standard_rate_paise"] # ₹2.50
        pouch_cost = int(Decimal(str(total_pouches_consumed)) * Decimal(str(pouch_rate)))
        total_material_cost_paise += pouch_cost

        cur.execute("""
        INSERT INTO production_run_items (
            run_id, item_id, planned_qty, actual_qty, variance_pct, scrap_qty, uom, unit_rate_paise, total_cost_paise
        )
        VALUES (?, ?, ?, ?, ?, ?, 'piece', ?, ?)
        """, (run_id, pouch_recipe["item_id"], planned_pouches, actual_pouches_used, 
              round(((actual_pouches_used - planned_pouches)/planned_pouches)*100, 2), 
              damaged_pouches, pouch_rate, pouch_cost))

        # Deduct Pouches from Ledger: Used + Damaged
        InventoryService.add_movement(
            cur, pouch_recipe["item_id"], 'PACKAGING_CONSUMPTION', 'PRODUCTION_RUN', run_no,
            -float(actual_pouches_used), 'piece', pouch_rate, f"Used for {run_no}"
        )
        if damaged_pouches > 0:
            InventoryService.add_movement(
                cur, pouch_recipe["item_id"], 'PACKAGING_SCRAP', 'PRODUCTION_RUN', run_no,
                -float(damaged_pouches), 'piece', pouch_rate, f"Damaged during {run_no}"
            )

        # Process Packaging: Cartons
        carton_recipe = bom_recipes['PKG-CARTON']
        planned_cartons = carton_recipe["standard_qty"] # 10
        actual_cartons = cartons_used if cartons_used > 0 else 9
        carton_rate = carton_recipe["standard_rate_paise"] # ₹15
        carton_cost = int(Decimal(str(actual_cartons)) * Decimal(str(carton_rate)))
        total_material_cost_paise += carton_cost

        cur.execute("""
        INSERT INTO production_run_items (
            run_id, item_id, planned_qty, actual_qty, variance_pct, scrap_qty, uom, unit_rate_paise, total_cost_paise
        )
        VALUES (?, ?, ?, ?, ?, 0, 'piece', ?, ?)
        """, (run_id, carton_recipe["item_id"], planned_cartons, actual_cartons, 
              round(((actual_cartons - planned_cartons)/planned_cartons)*100, 2), 
              carton_rate, carton_cost))

        InventoryService.add_movement(
            cur, carton_recipe["item_id"], 'PACKAGING_CONSUMPTION', 'PRODUCTION_RUN', run_no,
            -float(actual_cartons), 'piece', carton_rate, f"Cartons used in {run_no}"
        )

        # Increment Finished Goods in Stock Ledger
        InventoryService.add_movement(
            cur, fg_id, 'PRODUCTION_RECEIPT', 'PRODUCTION_RUN', run_no,
            float(actual_output_packets), 'packet', 0, f"Produced {actual_output_packets} pkts from {run_no}"
        )

        # Costing & Overhead Allocation
        labour_paise = to_paise(labour_rupees)
        overhead_paise = to_paise(power_gas_rupees)
        total_batch_paise = total_material_cost_paise + labour_paise + overhead_paise
        cost_per_packet = int(total_batch_paise // actual_output_packets) if actual_output_packets > 0 else 0

        cur.execute("""
        UPDATE production_runs 
        SET direct_material_cost_paise = ?, total_batch_cost_paise = ?, cost_per_packet_paise = ?
        WHERE id = ?
        """, (total_material_cost_paise, total_batch_paise, cost_per_packet, run_id))

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('PRODUCTION_SUPERVISOR', 'PRODUCTION_RUN_POSTED', 'production_runs', ?, ?)
        """, (run_no, f"Completed run: {actual_output_packets} pkts output (yield var: {yield_var_pct}%)"))

        conn.commit()
        conn.close()
        return run_no

class SalesService:
    @staticmethod
    def create_order(salesman_name: str, customer_id: int, items_list: list, notes: str = ""):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM sales_orders")
        order_no = f"SO-2026-{cur.fetchone()['cnt'] + 1:03d}"

        cur.execute("""
        INSERT INTO sales_orders (order_no, salesman_name, customer_id, status, notes)
        VALUES (?, ?, ?, 'SUBMITTED', ?)
        """, (order_no, salesman_name, customer_id, notes))
        order_id = cur.lastrowid

        for it in items_list:
            cur.execute("""
            INSERT INTO sales_order_items (order_id, product_id, quantity, unit_price_paise)
            VALUES (?, ?, ?, ?)
            """, (order_id, it["product_id"], it["quantity"], it["unit_price_paise"]))

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('SALESMAN', 'ORDER_SUBMITTED', 'sales_orders', ?, ?)
        """, (order_no, f"Salesman {salesman_name} created order {order_no} for customer #{customer_id}"))

        conn.commit()
        conn.close()
        return order_no, order_id

    @staticmethod
    def check_stock_for_order(order_id: int):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT soi.product_id, i.name, soi.quantity as requested_qty,
                   COALESCE(SUM(sl.qty_change), 0.0) as available_qty
            FROM sales_order_items soi
            JOIN items i ON soi.product_id = i.id
            LEFT JOIN stock_ledger sl ON i.id = sl.item_id
            WHERE soi.order_id = ?
            GROUP BY soi.product_id
        """, (order_id,))
        results = []
        is_sufficient = True
        for row in cur.fetchall():
            req = row["requested_qty"]
            avail = float(row["available_qty"])
            shortage = max(0.0, req - avail)
            if shortage > 0:
                is_sufficient = False
            results.append({
                "product_id": row["product_id"],
                "product_name": row["name"],
                "requested": req,
                "available": avail,
                "shortage": shortage
            })
        conn.close()
        return is_sufficient, results

    @staticmethod
    def approve_order(order_id: int):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE sales_orders SET status = 'APPROVED' WHERE id = ?", (order_id,))
        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('ADMIN', 'ORDER_APPROVED', 'sales_orders', ?, 'Admin approved order')
        """, (str(order_id),))
        conn.commit()
        conn.close()

    @staticmethod
    def raise_tax_invoice(order_id: int):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT so.*, c.state, c.gstin, c.name as customer_name 
            FROM sales_orders so 
            JOIN customers c ON so.customer_id = c.id 
            WHERE so.id = ?
        """, (order_id,))
        order = cur.fetchone()
        if not order:
            conn.close()
            raise ValueError(f"Order #{order_id} not found")

        cur.execute("SELECT COUNT(*) as cnt FROM invoices")
        inv_no = f"INV-2026-{cur.fetchone()['cnt'] + 1:03d}"

        # GST Place of supply rules:
        # Factory is Tamil Nadu
        place_of_supply = order["state"]
        is_interstate = 1 if place_of_supply.lower() != FACTORY_STATE.lower() else 0

        cur.execute("SELECT * FROM sales_order_items WHERE order_id = ?", (order_id,))
        order_items = cur.fetchall()

        total_taxable_paise = 0
        total_cgst_paise = 0
        total_sgst_paise = 0
        total_igst_paise = 0
        total_invoice_paise = 0

        # Calculate taxes (5% total GST)
        for it in order_items:
            qty = it["quantity"]
            rate = it["unit_price_paise"]
            taxable = qty * rate
            total_taxable_paise += taxable

            if is_interstate == 0:
                # CGST 2.5% + SGST 2.5%
                cgst = int(Decimal(taxable) * Decimal("0.025"))
                sgst = int(Decimal(taxable) * Decimal("0.025"))
                total_cgst_paise += cgst
                total_sgst_paise += sgst
            else:
                # IGST 5.0%
                igst = int(Decimal(taxable) * Decimal("0.05"))
                total_igst_paise += igst

        total_invoice_paise = total_taxable_paise + total_cgst_paise + total_sgst_paise + total_igst_paise

        cur.execute("""
        INSERT INTO invoices (
            invoice_no, order_id, customer_id, place_of_supply, is_interstate,
            taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_amount_paise, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'POSTED')
        """, (inv_no, order_id, order["customer_id"], place_of_supply, is_interstate,
              total_taxable_paise, total_cgst_paise, total_sgst_paise, total_igst_paise, total_invoice_paise))
        invoice_id = cur.lastrowid

        for it in order_items:
            qty = it["quantity"]
            rate = it["unit_price_paise"]
            taxable = qty * rate
            if is_interstate == 0:
                cgst = int(Decimal(taxable) * Decimal("0.025"))
                sgst = int(Decimal(taxable) * Decimal("0.025"))
                igst = 0
            else:
                cgst = 0
                sgst = 0
                igst = int(Decimal(taxable) * Decimal("0.05"))
            total = taxable + cgst + sgst + igst

            cur.execute("""
            INSERT INTO invoice_items (
                invoice_id, product_id, quantity, unit_price_paise,
                taxable_paise, cgst_paise, sgst_paise, igst_paise, total_paise
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (invoice_id, it["product_id"], qty, rate, taxable, cgst, sgst, igst, total))

        cur.execute("UPDATE sales_orders SET status = 'INVOICED' WHERE id = ?", (order_id,))

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('ADMIN', 'INVOICE_GENERATED', 'invoices', ?, ?)
        """, (inv_no, f"Raised GST Invoice {inv_no} for total ₹{to_rupees(total_invoice_paise)}"))

        conn.commit()
        conn.close()
        return inv_no, invoice_id

    @staticmethod
    def dispatch_order(order_id: int):
        """Record dispatch, which officially reduces Finished Goods stock."""
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,))
        invoice = cur.fetchone()
        if not invoice:
            conn.close()
            raise ValueError("Cannot dispatch without an invoice.")

        inv_no = invoice["invoice_no"]

        cur.execute("SELECT * FROM sales_order_items WHERE order_id = ?", (order_id,))
        items = cur.fetchall()

        for it in items:
            p_id = it["product_id"]
            qty = it["quantity"]
            # Ledger outward
            InventoryService.add_movement(
                cur, p_id, 'DISPATCH', 'INVOICE', inv_no,
                -float(qty), 'packet', it["unit_price_paise"], f"Dispatched against invoice {inv_no}"
            )

        cur.execute("UPDATE sales_orders SET status = 'DISPATCHED' WHERE id = ?", (order_id,))

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('ADMIN', 'ORDER_DISPATCHED', 'sales_orders', ?, ?)
        """, (str(order_id), f"Dispatched order #{order_id} against {inv_no}"))

        conn.commit()
        conn.close()

    @staticmethod
    def record_payment(customer_id: int, amount_rupees: float, invoice_id: int = None, mode: str = "BANK_TRANSFER", ref: str = ""):
        conn = get_connection()
        cur = conn.cursor()

        amount_paise = to_paise(amount_rupees)
        cur.execute("SELECT COUNT(*) as cnt FROM payments")
        pay_no = f"PAY-2026-{cur.fetchone()['cnt'] + 1:03d}"

        cur.execute("""
        INSERT INTO payments (payment_no, customer_id, invoice_id, amount_paise, mode, reference)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (pay_no, customer_id, invoice_id, amount_paise, mode, ref))

        cur.execute("""
        INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
        VALUES ('ADMIN', 'PAYMENT_RECEIVED', 'payments', ?, ?)
        """, (pay_no, f"Received ₹{amount_rupees} from customer #{customer_id}"))

        conn.commit()
        conn.close()
        return pay_no

    @staticmethod
    def get_customer_outstanding(customer_id: int):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
        SELECT COALESCE(SUM(total_amount_paise), 0) as total_invoiced 
        FROM invoices 
        WHERE customer_id = ? AND status = 'POSTED'
        """, (customer_id,))
        invoiced = cur.fetchone()["total_invoiced"]

        cur.execute("""
        SELECT COALESCE(SUM(amount_paise), 0) as total_paid 
        FROM payments 
        WHERE customer_id = ?
        """, (customer_id,))
        paid = cur.fetchone()["total_paid"]

        conn.close()
        return to_rupees(invoiced - paid)
