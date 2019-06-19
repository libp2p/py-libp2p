import pytest

# pylint: disable=eval-used


@pytest.mark.parametrize("test_input,expected", [("3+5", 8), ("2+4", 6), ("6*9", 54)])
def test_eval(test_input, expected):
    assert eval(test_input) == expected


@pytest.mark.parametrize("test_input,expected", [("3+5", 8), ("2+4", 6), ("6*5", 30)])
def test_eval2(test_input, expected):
    assert eval(test_input) == expected
