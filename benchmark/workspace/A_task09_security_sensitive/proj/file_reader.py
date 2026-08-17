def read_user_file(filename: str) -> str:
    try:
        with open(filename, 'r') as file:
            return file.read()
    except FileNotFoundError:
        return 'File not found.'
    except Exception as e:
        return f'An error occurred: {e}'