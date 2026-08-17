from geometry_utils import area
from shapes import Rectangle

def test_area_calculation():
    rect = Rectangle(3, 4)
    assert area(rect) == 12
