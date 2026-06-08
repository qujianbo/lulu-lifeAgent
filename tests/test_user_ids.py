from datetime import UTC, datetime

import pytest

from app.services.user_ids import (
    build_public_user_id,
    calculate_check_digit,
    parse_public_user_id,
    sequence_key,
    year_code_from_datetime,
)


def test_year_code_from_datetime() -> None:
    assert year_code_from_datetime(datetime(2026, 6, 8, tzinfo=UTC)) == "26"


def test_sequence_key() -> None:
    assert sequence_key("11", "01", "26") == "user:11:01:26"


def test_calculate_check_digit() -> None:
    assert calculate_check_digit("1101260000001") == 2


def test_build_public_user_id() -> None:
    assert build_public_user_id(1, year_code="26") == 11_012_600_000_012


def test_parse_public_user_id() -> None:
    parts = parse_public_user_id(11_012_600_000_012)
    assert parts.product_code == "11"
    assert parts.channel_code == "01"
    assert parts.year_code == "26"
    assert parts.sequence == 1
    assert parts.check_digit == 2


@pytest.mark.parametrize("sequence", [0, 10_000_000])
def test_sequence_range(sequence: int) -> None:
    with pytest.raises(ValueError, match="sequence"):
        build_public_user_id(sequence, year_code="26")


def test_check_digit_validation() -> None:
    with pytest.raises(ValueError, match="check digit"):
        parse_public_user_id(11_012_600_000_013)

