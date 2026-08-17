import os

def read_user_file(filename: str) -> str:
    # Validate input to prevent directory traversal attacks
    if not os.path.basename(filename) == filename:
        raise ValueError('Invalid filename')
    
    try:
        with open(filename, 'r') as file:
            return file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f'The file {filename} does not exist.')
    except Exception as e:
        raise Exception(f'An error occurred while reading the file: {e}')

if __name__ == '__main__':
    import tempfile
    import unittest

    class TestFileReader(unittest.TestCase):
        def test_read_user_file(self):
            # Create a temporary file and write sample data to it
            with tempfile.NamedTemporaryFile(delete=False, mode='w+') as temp_file:
                temp_file.write('Hello, world!')
                temp_file.flush()
                
                # Test reading the file
                content = read_user_file(temp_file.name)
                self.assertEqual(content, 'Hello, world!')
                
            # Clean up the temporary file
            os.unlink(temp_file.name)

    unittest.main()