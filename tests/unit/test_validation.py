import pytest
from thxou.validation import normalize_username, validate_name


def test_username_normalizes():
    assert normalize_username("Avery_1") == "avery_1"


@pytest.mark.parametrize("value", ["ab", "1abc", "admin", "bad-name"])
def test_username_rejects(value):
    with pytest.raises(ValueError):
        normalize_username(value)


def test_name_limit():
    with pytest.raises(ValueError):
        validate_name("")
