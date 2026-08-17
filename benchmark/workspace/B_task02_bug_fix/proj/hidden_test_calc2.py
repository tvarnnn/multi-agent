from calc2 import subtract


def test_subtract_hidden():
    assert subtract(10, 4) == 6
    assert subtract(0, 0) == 0
