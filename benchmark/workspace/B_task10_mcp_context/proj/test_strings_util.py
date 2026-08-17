import unittest
from strings_util import reverse_string
class TestStringsUtil(unittest.TestCase):
    def test_reverse_string(self):
        self.assertEqual(reverse_string('hello'), 'olleh')
        self.assertEqual(reverse_string(''), '')
        self.assertEqual(reverse_string('a'), 'a')
        self.assertEqual(reverse_string('Python'), 'nohtyP')

if __name__ == '__main__':
    unittest.main()