import unittest
from math_utils import is_even

class TestMathUtils(unittest.TestCase):

    def test_is_even_positive_even(self):
        self.assertTrue(is_even(2))

    def test_is_even_positive_odd(self):
        self.assertFalse(is_even(3))

    def test_is_even_negative_even(self):
        self.assertTrue(is_even(-2))

    def test_is_even_negative_odd(self):
        self.assertFalse(is_even(-3))

    def test_is_even_zero(self):
        self.assertTrue(is_even(0))

if __name__ == '__main__':
    unittest.main()