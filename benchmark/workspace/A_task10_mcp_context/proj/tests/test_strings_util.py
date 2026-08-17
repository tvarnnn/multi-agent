import unittest
from strings_util import reverse_string

class TestStringsUtil(unittest.TestCase):
    def test_reverse_string_empty(self):
        self.assertEqual(reverse_string(''), '')
    
    def test_reverse_string_normal(self):
        self.assertEqual(reverse_string('hello'), 'olleh')

if __name__ == '__main__':
    unittest.main()
