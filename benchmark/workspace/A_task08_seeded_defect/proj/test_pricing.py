from pricing import apply_discount


def test_apply_discount():
    assert apply_discount(100, 10) == 90
