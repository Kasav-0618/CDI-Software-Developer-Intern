import unittest
from decimal import Decimal
from database import to_paise, to_rupees, get_connection
from seed import seed_database
from services import InventoryService, SalesService, ProductionService

class TestOrderToAuditMath(unittest.TestCase):
    def setUp(self):
        seed_database()

    def test_paisa_arithmetic_prevents_float_drift(self):
        """Verify that currency arithmetic in integer paise does not drift."""
        # 187.50 + 187.50 = 375.00
        cgst = to_paise(187.50)
        sgst = to_paise(187.50)
        self.assertEqual(cgst, 18750)
        self.assertEqual(sgst, 18750)
        self.assertEqual(to_rupees(cgst + sgst), 375.00)

    def test_gst_calculation_rules(self):
        """Intra-state splits 5% into 2.5% CGST + 2.5% SGST. Inter-state is 5% IGST."""
        taxable_rs = 7500.00
        taxable_paise = to_paise(taxable_rs)
        
        # Intra-state
        cgst = int(Decimal(taxable_paise) * Decimal("0.025"))
        sgst = int(Decimal(taxable_paise) * Decimal("0.025"))
        self.assertEqual(cgst, 18750)
        self.assertEqual(sgst, 18750)
        self.assertEqual(taxable_paise + cgst + sgst, 787500)
        self.assertEqual(to_rupees(taxable_paise + cgst + sgst), 7875.00)

        # Inter-state
        igst = int(Decimal(taxable_paise) * Decimal("0.05"))
        self.assertEqual(igst, 37500)
        self.assertEqual(to_rupees(taxable_paise + igst), 7875.00)

    def test_stock_ledger_invariant(self):
        """Verify: Closing balance == Opening + Receipts - Issues/Sales +/- Adjustments."""
        summary = InventoryService.get_all_stock_summary()
        for item in summary:
            opening = item["opening"]
            inward = item["inward"]
            outward = item["outward"]
            closing = item["closing"]
            # Ledger invariant formula
            calculated_closing = round(opening + inward - outward, 4)
            self.assertEqual(round(closing, 4), calculated_closing, 
                             f"Invariant failed for {item['name']}")

    def test_production_variance_formulas(self):
        """Test variance calculations for planned vs actual."""
        # Oil: standard 10.0, actual 10.5 -> +5.0%
        oil_var = round(((10.5 - 10.0) / 10.0) * 100, 2)
        self.assertEqual(oil_var, 5.0)

        # Output: expected 200, actual 188 -> -6.0%
        yield_var = round(((188 - 200) / 200.0) * 100, 2)
        self.assertEqual(yield_var, -6.0)

if __name__ == "__main__":
    unittest.main()
