from calc import add


def test_add_hidden():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
