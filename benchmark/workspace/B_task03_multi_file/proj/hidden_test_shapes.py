from shapes import Rectangle
from geometry_utils import area


def test_area_hidden():
    r = Rectangle(3, 4)
    assert area(r) == 12
