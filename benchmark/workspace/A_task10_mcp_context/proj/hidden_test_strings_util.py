from strings_util import reverse_string


def test_reverse_string_hidden():
    assert reverse_string('hello') == 'olleh'
    assert reverse_string('') == ''
