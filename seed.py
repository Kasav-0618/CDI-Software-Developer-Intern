import os
import sqlite3
from database import DB_PATH, get_connection, init_db, to_paise

def seed_database():
    # Fresh initialization
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass
    init_db()

    conn = get_connection()
    cur = conn.cursor()

    # 1. Master Items
    items = [
        # code, name, category, uom, standard_rate_paise, hsn_code, gst_rate_pct, reorder_level
        ("RM-FLOUR", "Flour", "RAW_MATERIAL", "kg", to_paise(42.0), "1101", 5.0, 50.0),
        ("RM-OIL", "Cooking oil", "RAW_MATERIAL", "litre", to_paise(140.0), "1507", 5.0, 15.0),
        ("RM-SPICE", "Salt and spice mix", "RAW_MATERIAL", "kg", to_paise(200.0), "0910", 5.0, 3.0),
        ("PKG-POUCH", "200 g pouch", "PACKAGING", "piece", to_paise(2.50), "3923", 18.0, 200.0),
        ("PKG-CARTON", "Carton (holds 20 packets)", "PACKAGING", "piece", to_paise(15.0), "4819", 12.0, 15.0),
        ("FG-MURUKKU-200G", "Murukku 200 g", "FINISHED_GOODS", "packet", to_paise(50.0), "1905", 5.0, 50.0),
    ]

    cur.executemany("""
    INSERT INTO items (code, name, category, uom, standard_rate_paise, hsn_code, gst_rate_pct, reorder_level)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, items)

    # Fetch inserted item IDs
    cur.execute("SELECT id, code FROM items")
    item_map = {row["code"]: row["id"] for row in cur.fetchall()}

    # 2. Bill of Materials Master (Murukku 200 g: 1 batch = 200 packets)
    cur.execute("""
    INSERT INTO bom (finished_good_id, name, batch_size_packets)
    VALUES (?, 'Standard Murukku 200g Recipe (1 Batch)', 200)
    """, (item_map["FG-MURUKKU-200G"],))
    bom_id = cur.lastrowid

    bom_items = [
        (bom_id, item_map["RM-FLOUR"], 40.0, "kg"),
        (bom_id, item_map["RM-OIL"], 10.0, "litre"),
        (bom_id, item_map["RM-SPICE"], 1.2, "kg"),
        (bom_id, item_map["PKG-POUCH"], 200.0, "piece"),
        (bom_id, item_map["PKG-CARTON"], 10.0, "piece"),
    ]
    cur.executemany("""
    INSERT INTO bom_items (bom_id, item_id, standard_qty, uom)
    VALUES (?, ?, ?, ?)
    """, bom_items)

    # 3. Opening Stock & Immutable Stock Ledger
    opening_stocks = [
        (item_map["RM-FLOUR"], 100.0, "kg", to_paise(42.0), "Flour Opening Stock"),
        (item_map["RM-OIL"], 30.0, "litre", to_paise(140.0), "Cooking Oil Opening Stock"),
        (item_map["RM-SPICE"], 5.0, "kg", to_paise(200.0), "Spice Mix Opening Stock"),
        (item_map["PKG-POUCH"], 500.0, "piece", to_paise(2.50), "Pouch Opening Stock"),
        (item_map["PKG-CARTON"], 30.0, "piece", to_paise(15.0), "Carton Opening Stock"),
        (item_map["FG-MURUKKU-200G"], 50.0, "packet", to_paise(50.0), "Finished Murukku 200g Opening Stock"),
    ]

    for item_id, qty, uom, rate_paise, note in opening_stocks:
        cur.execute("""
        INSERT INTO stock_ledger (
            item_id, movement_type, source_doc_type, source_doc_id, 
            qty_change, balance_after, uom, unit_rate_paise, notes
        )
        VALUES (?, 'OPENING_STOCK', 'SYSTEM', 'OPENING-2026', ?, ?, ?, ?, ?)
        """, (item_id, qty, qty, uom, rate_paise, note))

    # 4. Customers
    customers = [
        ("CUST-RETAILER-A", "Retailer A (Tamil Nadu)", "RETAILER", "Tamil Nadu", "33AAAAA1111A1Z5", "+91 98401 12345", "12 Cross Cut Rd, Coimbatore, Tamil Nadu"),
        ("CUST-DIST-B", "Distributor B (Karnataka)", "DISTRIBUTOR", "Karnataka", "29BBBBB2222B1Z6", "+91 94481 67890", "45 BVK Iyengar Rd, Bengaluru, Karnataka"),
    ]
    cur.executemany("""
    INSERT INTO customers (code, name, type, state, gstin, phone, address)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, customers)

    # 5. Audit Log Entry
    cur.execute("""
    INSERT INTO audit_logs (actor_role, action, table_name, record_id, details)
    VALUES ('SYSTEM', 'SEED_DATABASE', 'SYSTEM', 'INIT', 'Loaded Section 5 Master Data and Opening Stock')
    """)

    conn.commit()
    conn.close()
    print("Database seeded with Section 5 Master Data & Opening Stock.")

if __name__ == "__main__":
    seed_database()
