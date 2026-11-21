import sqlite3
import os
from decimal import Decimal, ROUND_HALF_UP

DB_PATH = os.path.join(os.path.dirname(__file__), "order_to_audit.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    -- Items: Raw Materials, Packaging, Finished Goods
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN ('RAW_MATERIAL', 'PACKAGING', 'FINISHED_GOODS')),
        uom TEXT NOT NULL, -- 'kg', 'litre', 'piece', 'packet', 'carton'
        standard_rate_paise INTEGER NOT NULL DEFAULT 0,
        hsn_code TEXT NOT NULL DEFAULT '',
        gst_rate_pct REAL NOT NULL DEFAULT 5.0,
        reorder_level REAL NOT NULL DEFAULT 0.0
    );

    -- Bill of Materials Master
    CREATE TABLE IF NOT EXISTS bom (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finished_good_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        batch_size_packets INTEGER NOT NULL,
        FOREIGN KEY (finished_good_id) REFERENCES items(id)
    );

    -- BOM Recipe Items
    CREATE TABLE IF NOT EXISTS bom_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bom_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        standard_qty REAL NOT NULL,
        uom TEXT NOT NULL,
        FOREIGN KEY (bom_id) REFERENCES bom(id),
        FOREIGN KEY (item_id) REFERENCES items(id)
    );

    -- Customers (Retailers / Distributors)
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('RETAILER', 'DISTRIBUTOR')),
        state TEXT NOT NULL, -- 'Tamil Nadu', 'Karnataka', etc.
        gstin TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        address TEXT NOT NULL DEFAULT ''
    );

    -- Sales Orders (Mobile order taking)
    CREATE TABLE IF NOT EXISTS sales_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL,
        salesman_name TEXT NOT NULL,
        customer_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'INVOICED', 'DISPATCHED')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT '',
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS sales_order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price_paise INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES sales_orders(id),
        FOREIGN KEY (product_id) REFERENCES items(id)
    );

    -- Invoices (GST Tax Invoices)
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        order_id INTEGER,
        customer_id INTEGER NOT NULL,
        invoice_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        place_of_supply TEXT NOT NULL,
        is_interstate INTEGER NOT NULL DEFAULT 0, -- 0 = Intra (CGST+SGST), 1 = Inter (IGST)
        taxable_amount_paise INTEGER NOT NULL,
        cgst_paise INTEGER NOT NULL DEFAULT 0,
        sgst_paise INTEGER NOT NULL DEFAULT 0,
        igst_paise INTEGER NOT NULL DEFAULT 0,
        total_amount_paise INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('POSTED', 'CANCELLED')),
        credit_note_ref TEXT DEFAULT NULL,
        FOREIGN KEY (order_id) REFERENCES sales_orders(id),
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price_paise INTEGER NOT NULL,
        taxable_paise INTEGER NOT NULL,
        cgst_paise INTEGER NOT NULL DEFAULT 0,
        sgst_paise INTEGER NOT NULL DEFAULT 0,
        igst_paise INTEGER NOT NULL DEFAULT 0,
        total_paise INTEGER NOT NULL,
        FOREIGN KEY (invoice_id) REFERENCES invoices(id),
        FOREIGN KEY (product_id) REFERENCES items(id)
    );

    -- Payments & Customer Collections
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_no TEXT UNIQUE NOT NULL,
        customer_id INTEGER NOT NULL,
        invoice_id INTEGER,
        amount_paise INTEGER NOT NULL,
        payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        mode TEXT NOT NULL DEFAULT 'BANK_TRANSFER',
        reference TEXT DEFAULT '',
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (invoice_id) REFERENCES invoices(id)
    );

    -- Production Runs (Recipe based execution)
    CREATE TABLE IF NOT EXISTS production_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_no TEXT UNIQUE NOT NULL,
        bom_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        planned_batch_size INTEGER NOT NULL,
        actual_output_packets INTEGER NOT NULL,
        yield_variance_pct REAL NOT NULL,
        labour_cost_paise INTEGER NOT NULL DEFAULT 0,
        power_gas_cost_paise INTEGER NOT NULL DEFAULT 0,
        direct_material_cost_paise INTEGER NOT NULL DEFAULT 0,
        total_batch_cost_paise INTEGER NOT NULL DEFAULT 0,
        cost_per_packet_paise INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK(status IN ('COMPLETED', 'IN_PROGRESS', 'CANCELLED')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT '',
        FOREIGN KEY (bom_id) REFERENCES bom(id),
        FOREIGN KEY (product_id) REFERENCES items(id)
    );

    CREATE TABLE IF NOT EXISTS production_run_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        planned_qty REAL NOT NULL,
        actual_qty REAL NOT NULL,
        variance_pct REAL NOT NULL,
        scrap_qty REAL NOT NULL DEFAULT 0.0,
        uom TEXT NOT NULL,
        unit_rate_paise INTEGER NOT NULL DEFAULT 0,
        total_cost_paise INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (run_id) REFERENCES production_runs(id),
        FOREIGN KEY (item_id) REFERENCES items(id)
    );

    -- Immutable Double-Entry Stock Movement Ledger
    CREATE TABLE IF NOT EXISTS stock_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        movement_type TEXT NOT NULL CHECK(movement_type IN (
            'OPENING_STOCK', 'PURCHASE_RECEIPT', 'PRODUCTION_ISSUE', 
            'PACKAGING_CONSUMPTION', 'PACKAGING_SCRAP', 'PRODUCTION_RECEIPT', 
            'DISPATCH', 'STOCK_ADJUSTMENT'
        )),
        source_doc_type TEXT NOT NULL, -- 'SYSTEM', 'PURCHASE', 'PRODUCTION_RUN', 'INVOICE', 'MANUAL'
        source_doc_id TEXT NOT NULL,
        qty_change REAL NOT NULL, -- Positive for inward, negative for outward
        balance_after REAL NOT NULL,
        uom TEXT NOT NULL,
        unit_rate_paise INTEGER NOT NULL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items(id)
    );

    -- Purchases
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_no TEXT UNIQUE NOT NULL,
        item_id INTEGER NOT NULL,
        supplier_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        uom TEXT NOT NULL,
        rate_paise INTEGER NOT NULL,
        total_amount_paise INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items(id)
    );

    -- Audit Logs
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_role TEXT NOT NULL,
        action TEXT NOT NULL,
        table_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        details TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

def to_paise(rupees: float) -> int:
    """Safely convert rupees to integer paise without floating point issues."""
    d = Decimal(str(rupees))
    return int((d * Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def to_rupees(paise: int) -> float:
    """Format paise as float rupees for display."""
    return float(Decimal(paise) / Decimal(100))

if __name__ == "__main__":
    init_db()
    print("Database schema successfully initialized.")
