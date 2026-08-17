from pricing import apply_discount


def test_apply_discount_hidden():
    assert apply_discount(200, 25) == 150
    assert apply_discount(50, 0) == 50
