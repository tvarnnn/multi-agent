import unittest
from config_reader import get_setting

class TestConfigReader(unittest.TestCase):
    def test_key_present(self):
        config = {'test_key': 'test_value'}
        self.assertEqual(get_setting(config, 'test_key'), 'test_value')

    def test_key_missing(self):
        config = {'test_key': 'test_value'}
        with self.assertRaises(KeyError) as context:
            get_setting(config, 'missing_key')
        self.assertEqual(str(context.exception), 'Key "missing_key" not found in configuration.')

if __name__ == '__main__':
    unittest.main()