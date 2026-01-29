import pytest

from src.calculator import suma

pytestmark = pytest.mark.unit


def test_suma_positivos():
    assert suma(2, 3) == 5


def test_suma_negativos():
    assert suma(-1, -1) == -2


def test_suma_cero():
    assert suma(0, 0) == 0


def test_suma_mixto():
    assert suma(-5, 10) == 5
