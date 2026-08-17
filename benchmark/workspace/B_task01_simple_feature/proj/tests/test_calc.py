def test_add():
    assert add(1, 2) == 3
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
    assert add(2.5, 3.5) == 6.0
    assert add(-2, -3) == -5
