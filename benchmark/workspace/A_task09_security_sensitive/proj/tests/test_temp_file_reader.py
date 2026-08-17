import unittest
import tempfile
import os
from file_reader import read_user_file

class TestTempFileReader(unittest.TestCase):
    def test_read_temp_file(self):
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
            temp_file.write('Hello, world!')
            temp_file.flush()
            content = read_user_file(temp_file.name)
            self.assertEqual(content, 'Hello, world!')
            os.remove(temp_file.name)

if __name__ == '__main__':
    unittest.main()