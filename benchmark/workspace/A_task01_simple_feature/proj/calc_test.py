import unittest
from calc import add

class TestAddFunction(unittest.TestCase):
    def test_add_integers(self):
        self.assertEqual(add(1, 2), 3)
        self.assertEqual(add(-1, -1), -2)
        self.assertEqual(add(-1, 1), 0)

    def test_add_floats(self):
        self.assertAlmostEqual(add(0.1, 0.2), 0.3, places=5)
        self.assertAlmostEqual(add(-0.1, -0.2), -0.3, places=5)
        self.assertAlmostEqual(add(-0.1, 0.1), 0.0, places=5)

    def test_add_mixed_types(self):
        self.assertAlmostEqual(add(1, 0.5), 1.5, places=5)
        self.assertAlmostEqual(add(-1, -0.5), -1.5, places=5)
        self.assertAlmostEqual(add(-1, 0.5), -0.5, places=5)

if __name__ == '__main__':
    unittest.main()
