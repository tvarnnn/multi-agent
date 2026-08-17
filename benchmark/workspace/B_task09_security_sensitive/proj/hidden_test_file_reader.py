from pathlib import Path
from file_reader import read_user_file


def test_read_user_file_hidden(tmp_path):
    p = tmp_path / 'sample.txt'
    p.write_text('hello world')
    assert read_user_file(str(p)) == 'hello world'
