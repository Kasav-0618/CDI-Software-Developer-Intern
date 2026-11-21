# Order-to-Audit ERP for Small Food Manufacturer
### Centre for Digital Infrastructure, NIT Tiruchirappalli — Internship Prototype

A complete, production-ready Order-to-Audit system modeling a South Indian snack manufacturer (Murukku, mixture, chips, sweets). It bridges the **Sales Loop** and the **Production Loop** at the **Finished Goods Stock** ledger, enforcing mathematical precision, immutable double-entry inventory tracking, and complete GST compliance.

---

## 1. Quick Start Guide (Run in VS Code)

### Prerequisites
* Python 3.10+ (Zero external dependencies needed! Uses standard library `http.server`, `sqlite3`, `decimal`, and `unittest`).

### Commands to Run
Open your terminal in VS Code inside the project directory:

```bash
cd "C:\Users\lsk22\.gemini\antigravity\scratch\order-to-audit"
```

#### Step 1: Run Unit Tests (Math, GST, and Ledger Invariants)
```bash
python test_math.py
```

#### Step 2: Run the Mandatory Section 5 Benchmark Verification Script
```bash
python benchmark.py
```
*Outputs a 100% verified PASS/FAIL scorecard against all Section 5 check metrics.*

#### Step 3: Launch the Full Interactive Web Application
```bash
python app.py
```
Open your browser and navigate to:
👉 http://localhost:8000

Demo Video
https://youtu.be/bUIuqYtMKnU

---

## 2. Tech Stack & Justification

* **Backend & Storage:** Python standard library (`http.server`, `sqlite3`, `decimal`) providing zero-dependency reliability, immediate portability across any machine, relational schema foreign key integrity, and zero floating-point drift.
* **Frontend:** Responsive HTML5 + Tailwind CSS + Lucide Icons serving dedicated views for all 5 roles:
  1. 📱 **Salesman (Mobile View):** Rapid customer order entry in < 1 minute with simulated phone frame.
  2. 🖥️ **Factory Admin:** Incoming order review, real-time stock shortage checks, GST Tax Invoice generation (CGST/SGST vs IGST), dispatch, and collection logging.
  3. 🏭 **Production Floor:** Recipe-based BOM runs, planned vs. actual consumption, yield variance flags (> 3%), and packaging scrap deductions.
  4. 📊 **Auditor & Accounts:** GSTR-1/3B summaries, immutable double-entry stock movement ledger, sales register, and CSV exports.
  5. 👑 **Owner Dashboard:** Live stock levels, sales KPIs, gross margin per packet, and outstanding dues.

---

## 3. Section 5 Mandatory Benchmark Results Comparison

| Check Metric | Expected (Section 5 Spec) | Prototype Actual Result | Status |
| :--- | :--- | :--- | :---: |
| **Flour Closing Balance** | 120 kg (100 + 60 − 40) | **120.0 kg** | **PASS** |
| **Oil Closing Balance** | 19.5 L (30 − 10.5) | **19.5 L** | **PASS** |
| **Pouches Closing Balance** | 306 (188 used + 6 damaged) | **306 pcs** | **PASS** |
| **Finished Goods (after run)** | 238 packets (50 + 188) | **238 packets** | **PASS** |
| **Finished Goods (after dispatch)** | 88 packets (238 − 150) | **88 packets** | **PASS** |
| **Yield Variance** | 188 vs 200 expected, −6%, flagged | **-6.0% (Flagged)** | **PASS** |
| **Oil Consumption Variance** | +5%, flagged | **+5.0% (Flagged)** | **PASS** |
| **Retailer A Invoice** | ₹7,500 + ₹187.50 CGST + ₹187.50 SGST = ₹7,875 | **₹7,875.00** | **PASS** |
| **Retailer A Outstanding** | ₹3,875 (₹7,875 − ₹4,000) | **₹3,875.00** | **PASS** |
| **Distributor B Order** | Shortage of 32 packets flagged; IGST applies | **Shortage of 32 pkts flagged; IGST 5%** | **PASS** |
| **Cost per Packet** | With valuation method & overhead rule stated | **₹30.90 / pkt** (FIFO + direct overheads) | **PASS** |

---

## 4. Scope & Feature Implementation Tiers

### Must Haves (100% Implemented)
- [x] Role-Based Access Control: Salesman, Factory Admin, Production Supervisor, Auditor, Owner.
- [x] Product, customer, raw-material, and BOM master catalog.
- [x] Mobile-friendly order entry and admin approval workflow.
- [x] GST-compliant tax invoices with printable/PDF format (HSN, CGST/SGST/IGST).
- [x] Production run updating raw-material and finished-goods stock automatically.
- [x] Planned vs actual consumption and yield variance tracking.
- [x] Immutable double-entry stock summary and stock movement ledger.
- [x] Sales register and stock report exportable to CSV.

### Should Haves (100% Implemented)
- [x] Inward purchase receipt and supplier records.
- [x] Payments and customer outstanding tracking with aging.
- [x] Cost per packet calculation with labour & power/gas overhead allocation.
- [x] GST outward summary report mapping to GSTR-1 and GSTR-3B.
- [x] Visual variance alerts for deviations beyond ±3% tolerance.
- [x] Owner executive dashboard.

### Stretch Goals
- [x] Shortage detection on order review before invoice creation.
- [x] Reorder levels and low-stock indicators on stock dashboard.
- [x] One-click benchmark runner button right in the UI.

---

## 5. File Structure
```
order-to-audit/
├── app.py           # Zero-dependency HTTP Web Server & REST API
├── database.py      # SQLite schema, connections, and integer-paisa currency math
├── seed.py          # Section 5 Master Data and Opening Stock seed script
├── services.py      # Business logic: Inventory, Sales, GST, Production & Costing
├── benchmark.py     # CLI runner for the mandatory 9-step benchmark scenario
├── test_math.py     # Unit test suite verifying rounding, tax & ledger invariants
├── index.html       # Single-Page Application (Tailwind CSS, Lucide icons)
├── README.md        # System documentation, run commands & benchmark scorecard
└── DESIGN_NOTE.md   # Architectural design note, ER diagram, costing formulas
```
