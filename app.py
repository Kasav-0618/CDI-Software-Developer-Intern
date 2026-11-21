import http.server
import socketserver
import json
import urllib.parse
import sys
import os
import io
import csv

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from database import DB_PATH, get_connection, to_paise, to_rupees, init_db
from seed import seed_database
from services import (
    InventoryService, PurchaseService, ProductionService, 
    SalesService
)

PORT = 8000

class ERPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/state":
            conn = get_connection()
            cur = conn.cursor()

            # Items & Live Stock
            stock_summary = InventoryService.get_all_stock_summary()

            # Customers
            cur.execute("SELECT * FROM customers")
            customers = [dict(r) for r in cur.fetchall()]
            for c in customers:
                c["outstanding_rs"] = SalesService.get_customer_outstanding(c["id"])

            # Orders
            cur.execute("""
                SELECT so.*, c.name as customer_name, c.state as customer_state,
                       (SELECT SUM(quantity * unit_price_paise) FROM sales_order_items WHERE order_id = so.id) as total_paise
                FROM sales_orders so
                JOIN customers c ON so.customer_id = c.id
                ORDER BY so.id DESC
            """)
            orders = []
            for r in cur.fetchall():
                od = dict(r)
                od["total_rs"] = to_rupees(od["total_paise"] or 0)
                cur.execute("""
                    SELECT soi.*, i.name as product_name, i.uom 
                    FROM sales_order_items soi 
                    JOIN items i ON soi.product_id = i.id 
                    WHERE soi.order_id = ?
                """, (od["id"],))
                od["items"] = [dict(it) for it in cur.fetchall()]
                orders.append(od)

            # Invoices
            cur.execute("""
                SELECT inv.*, c.name as customer_name, c.gstin as customer_gstin 
                FROM invoices inv 
                JOIN customers c ON inv.customer_id = c.id 
                ORDER BY inv.id DESC
            """)
            invoices = []
            for r in cur.fetchall():
                inv = dict(r)
                inv["taxable_rs"] = to_rupees(inv["taxable_amount_paise"])
                inv["cgst_rs"] = to_rupees(inv["cgst_paise"])
                inv["sgst_rs"] = to_rupees(inv["sgst_paise"])
                inv["igst_rs"] = to_rupees(inv["igst_paise"])
                inv["total_rs"] = to_rupees(inv["total_amount_paise"])
                invoices.append(inv)

            # Production Runs
            cur.execute("""
                SELECT pr.*, i.name as product_name 
                FROM production_runs pr 
                JOIN items i ON pr.product_id = i.id 
                ORDER BY pr.id DESC
            """)
            runs = []
            for r in cur.fetchall():
                run = dict(r)
                run["material_cost_rs"] = to_rupees(run["direct_material_cost_paise"])
                run["labour_cost_rs"] = to_rupees(run["labour_cost_paise"])
                run["power_gas_cost_rs"] = to_rupees(run["power_gas_cost_paise"])
                run["total_batch_cost_rs"] = to_rupees(run["total_batch_cost_paise"])
                run["cost_per_packet_rs"] = to_rupees(run["cost_per_packet_paise"])
                cur.execute("""
                    SELECT pri.*, i.name as item_name 
                    FROM production_run_items pri 
                    JOIN items i ON pri.item_id = i.id 
                    WHERE pri.run_id = ?
                """, (run["id"],))
                run["items"] = [dict(pri) for pri in cur.fetchall()]
                runs.append(run)

            # Payments
            cur.execute("""
                SELECT p.*, c.name as customer_name 
                FROM payments p 
                JOIN customers c ON p.customer_id = c.id 
                ORDER BY p.id DESC
            """)
            payments = [dict(r) for r in cur.fetchall()]
            for p in payments:
                p["amount_rs"] = to_rupees(p["amount_paise"])

            # Stock Ledger (Recent 50)
            cur.execute("""
                SELECT sl.*, i.name as item_name, i.code as item_code 
                FROM stock_ledger sl 
                JOIN items i ON sl.item_id = i.id 
                ORDER BY sl.id DESC LIMIT 50
            """)
            ledger = [dict(r) for r in cur.fetchall()]

            # Purchases
            cur.execute("""
                SELECT p.*, i.name as item_name 
                FROM purchases p 
                JOIN items i ON p.item_id = i.id 
                ORDER BY p.id DESC
            """)
            purchases = [dict(r) for r in cur.fetchall()]
            for p in purchases:
                p["rate_rs"] = to_rupees(p["rate_paise"])
                p["total_rs"] = to_rupees(p["total_amount_paise"])

            # Audit Logs
            cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 30")
            audit_logs = [dict(r) for r in cur.fetchall()]

            conn.close()

            self.send_json({
                "stock_summary": stock_summary,
                "customers": customers,
                "orders": orders,
                "invoices": invoices,
                "production_runs": runs,
                "payments": payments,
                "stock_ledger": ledger,
                "purchases": purchases,
                "audit_logs": audit_logs
            })
            return

        elif path == "/api/export/csv":
            report_type = query.get("type", ["sales"])[0]
            output = io.StringIO()
            writer = csv.writer(output)
            conn = get_connection()
            cur = conn.cursor()

            if report_type == "sales":
                writer.writerow(["Invoice No", "Date", "Customer", "State", "Taxable (Rs)", "CGST (Rs)", "SGST (Rs)", "IGST (Rs)", "Total (Rs)"])
                cur.execute("""
                    SELECT inv.invoice_no, inv.invoice_date, c.name, inv.place_of_supply,
                           inv.taxable_amount_paise, inv.cgst_paise, inv.sgst_paise, inv.igst_paise, inv.total_amount_paise
                    FROM invoices inv JOIN customers c ON inv.customer_id = c.id
                """)
                for r in cur.fetchall():
                    writer.writerow([
                        r[0], r[1], r[2], r[3],
                        to_rupees(r[4]), to_rupees(r[5]), to_rupees(r[6]), to_rupees(r[7]), to_rupees(r[8])
                    ])
            elif report_type == "stock":
                writer.writerow(["Item Code", "Name", "Category", "UOM", "Opening", "Inward", "Outward", "Closing Balance"])
                summary = InventoryService.get_all_stock_summary()
                for s in summary:
                    writer.writerow([s["code"], s["name"], s["category"], s["uom"], s["opening"], s["inward"], s["outward"], s["closing"]])
            elif report_type == "variance":
                writer.writerow(["Run No", "Product", "Planned Output", "Actual Output", "Yield Var %", "Material Cost (Rs)", "Cost / Packet (Rs)"])
                cur.execute("""
                    SELECT pr.run_no, i.name, pr.planned_batch_size, pr.actual_output_packets, 
                           pr.yield_variance_pct, pr.direct_material_cost_paise, pr.cost_per_packet_paise
                    FROM production_runs pr JOIN items i ON pr.product_id = i.id
                """)
                for r in cur.fetchall():
                    writer.writerow([r[0], r[1], r[2], r[3], r[4], to_rupees(r[5]), to_rupees(r[6])])
            conn.close()

            csv_data = output.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.send_header('Content-Disposition', f'attachment; filename="{report_type}_report.csv"')
            self.end_headers()
            self.wfile.write(csv_data.encode('utf-8'))
            return

        elif path in ["/", "/index.html"]:
            html_file = os.path.join(os.path.dirname(__file__), "index.html")
            if os.path.exists(html_file):
                with open(html_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('content-length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length > 0 else {}

        try:
            if path == "/api/seed/reset":
                seed_database()
                self.send_json({"success": True, "message": "Database reset to Section 5 opening state."})
                return

            elif path == "/api/benchmark/run":
                from benchmark import run_benchmark
                run_benchmark()
                self.send_json({"success": True, "message": "Benchmark scenario executed successfully."})
                return

            elif path == "/api/orders/create":
                salesman = body.get("salesman_name", "Salesman A")
                cust_id = int(body["customer_id"])
                items = body["items"] # [{product_id, quantity, unit_price_paise}]
                order_no, order_id = SalesService.create_order(salesman, cust_id, items, body.get("notes", ""))
                self.send_json({"success": True, "order_no": order_no, "order_id": order_id})
                return

            elif path == "/api/orders/check_stock":
                order_id = int(body["order_id"])
                is_ok, details = SalesService.check_stock_for_order(order_id)
                self.send_json({"is_sufficient": is_ok, "details": details})
                return

            elif path == "/api/orders/approve":
                order_id = int(body["order_id"])
                SalesService.approve_order(order_id)
                self.send_json({"success": True})
                return

            elif path == "/api/orders/invoice":
                order_id = int(body["order_id"])
                inv_no, inv_id = SalesService.raise_tax_invoice(order_id)
                self.send_json({"success": True, "invoice_no": inv_no, "invoice_id": inv_id})
                return

            elif path == "/api/orders/dispatch":
                order_id = int(body["order_id"])
                SalesService.dispatch_order(order_id)
                self.send_json({"success": True})
                return

            elif path == "/api/production/run":
                run_no = ProductionService.record_run(
                    bom_name_or_product_code="FG-MURUKKU-200G",
                    actual_issued_items=body.get("actual_issued", {
                        "RM-FLOUR": 40.0,
                        "RM-OIL": 10.5,
                        "RM-SPICE": 1.2
                    }),
                    actual_output_packets=int(body.get("actual_output_packets", 188)),
                    damaged_pouches=int(body.get("damaged_pouches", 6)),
                    cartons_used=int(body.get("cartons_used", 9)),
                    labour_rupees=float(body.get("labour_rupees", 1200.0)),
                    power_gas_rupees=float(body.get("power_gas_rupees", 600.0)),
                    notes=body.get("notes", "")
                )
                self.send_json({"success": True, "run_no": run_no})
                return

            elif path == "/api/purchases/create":
                po_no = PurchaseService.record_purchase(
                    body["item_code"], body["supplier_name"], float(body["quantity"]), float(body["rate_rupees"])
                )
                self.send_json({"success": True, "purchase_no": po_no})
                return

            elif path == "/api/payments/create":
                pay_no = SalesService.record_payment(
                    int(body["customer_id"]), float(body["amount_rupees"]),
                    int(body.get("invoice_id")) if body.get("invoice_id") else None,
                    body.get("mode", "BANK_TRANSFER"), body.get("reference", "")
                )
                self.send_json({"success": True, "payment_no": pay_no})
                return

            self.send_json({"error": "Endpoint not found"}, status=404)

        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

def run_server():
    if not os.path.exists(DB_PATH):
        seed_database()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), ERPRequestHandler) as httpd:
        print("=" * 60)
        print(f"🚀 Order-to-Audit ERP Server running at http://localhost:{PORT}")
        print(f"👉 Open http://localhost:{PORT} in your web browser.")
        print(f"👉 Press Ctrl+C in this terminal to stop.")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    run_server()
