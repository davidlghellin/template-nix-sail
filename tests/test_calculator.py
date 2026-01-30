import pytest

from src.calculator import suma

pytestmark = pytest.mark.unit


def test_suma_positive():
    assert suma(2, 3) == 5


def test_suma_negative():
    assert suma(-1, -1) == -2


def test_suma_zero():
    assert suma(0, 0) == 0


def test_suma_mixed():
    assert suma(-5, 10) == 5
