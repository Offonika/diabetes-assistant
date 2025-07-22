import pytest
from services import find_protocol_by_diagnosis, build_agrostore_deeplink


def test_find_protocol_found():
    assert find_protocol_by_diagnosis("Диабет 2 типа") == "standard protocol"


def test_find_protocol_not_found():
    assert find_protocol_by_diagnosis("Неизвестный диагноз") is None


def test_build_agrostore_deeplink():
    link = build_agrostore_deeplink("p1", 42, utm_source="test")
    assert "product_id=p1" in link
    assert "user_id=42" in link
    assert "utm_source=test" in link


