import unittest
from math_utils import is_even

class TestMathUtils(unittest.TestCase):
    def test_is_even_positive(self):
        self.assertTrue(is_even(2))
        self.assertTrue(is_even(10))

    def test_is_even_negative(self):
        self.assertTrue(is_even(-2))
        self.assertTrue(is_even(-10))

    def test_is_even_edge(self):
        self.assertTrue(is_even(0))

if __name__ == '__main__':
    unittest.main()