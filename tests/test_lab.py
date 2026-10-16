import unittest
import lab


class MarketTests(unittest.TestCase):
    def test_round_trip(self):
        account = lab.Account()
        account.fill("buy", 99, fee=0.1)
        account.fill("sell", 101, fee=0.1)
        self.assertEqual(account.inventory, 0)
        self.assertAlmostEqual(account.equity(100), 1.8)
        self.assertAlmostEqual(account.fees, 0.2)

    def test_mark_to_market_identity(self):
        result = lab.simulate()
        self.assertAlmostEqual(result["terminal_equity"], result["terminal_cash"] + result["terminal_inventory"] * result["terminal_mid"])
        self.assertLessEqual(result["max_abs_inventory"], 25)

    def test_repeatability(self):
        self.assertEqual(lab.simulate(steps=50), lab.simulate(steps=50))

    def test_invalid_order(self):
        with self.assertRaises(ValueError):
            lab.Account().fill("hold", 100)


if __name__ == "__main__":
    unittest.main()
