import pytest
from config_reader import get_setting


def test_get_setting_present_hidden():
    assert get_setting({'a': '1'}, 'a') == '1'


def test_get_setting_missing_hidden():
    with pytest.raises(KeyError):
        get_setting({'a': '1'}, 'b')
