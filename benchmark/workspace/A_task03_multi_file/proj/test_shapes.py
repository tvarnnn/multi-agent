from shapes import Rectangle

def test_rectangle_creation():
    rect = Rectangle(3, 4)
    assert rect.width == 3
    assert rect.height == 4
