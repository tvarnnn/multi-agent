import unittest
from config_reader import get_setting

class TestConfigReader(unittest.TestCase):
    def test_key_present(self):
        config = {'key': 'value'}
        self.assertEqual(get_setting(config, 'key'), 'value')

    def test_key_missing(self):
        config = {'key': 'value'}
        with self.assertRaises(KeyError) as context:
            get_setting(config, 'missing_key')
        self.assertEqual(str(context.exception), 'Key \\