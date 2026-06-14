from dataclasses import dataclass
from datetime import datetime

PUBLIC_USER_ID_MIN = 10_000_000_000_000
PUBLIC_USER_ID_MAX = 99_999_999_999_999
DEFAULT_PRODUCT_CODE = "11"
DEFAULT_WECHAT_CHANNEL_CODE = "01"
DEFAULT_WEB_BETA_CHANNEL_CODE = "02"


@dataclass(frozen=True)
class PublicUserIdParts:
    product_code: str
    channel_code: str
    year_code: str
    sequence: int
    check_digit: int


def sequence_key(product_code: str, channel_code: str, year_code: str) -> str:
    _validate_fixed_digits(product_code, 2, "product_code")
    _validate_fixed_digits(channel_code, 2, "channel_code")
    _validate_fixed_digits(year_code, 2, "year_code")
    return f"user:{product_code}:{channel_code}:{year_code}"


def year_code_from_datetime(value: datetime) -> str:
    return f"{value.year % 100:02d}"


def calculate_check_digit(first_13_digits: str) -> int:
    _validate_fixed_digits(first_13_digits, 13, "first_13_digits")
    return sum(int(char) for char in first_13_digits) % 10


def build_public_user_id(
    sequence: int,
    *,
    product_code: str = DEFAULT_PRODUCT_CODE,
    channel_code: str = DEFAULT_WECHAT_CHANNEL_CODE,
    year_code: str,
) -> int:
    _validate_fixed_digits(product_code, 2, "product_code")
    _validate_fixed_digits(channel_code, 2, "channel_code")
    _validate_fixed_digits(year_code, 2, "year_code")
    if sequence < 1 or sequence > 9_999_999:
        raise ValueError("sequence must be between 1 and 9,999,999")

    # The first 13 digits are stable business information; the final digit is only
    # for human-entry error detection and is not part of the sequence capacity.
    first_13_digits = f"{product_code}{channel_code}{year_code}{sequence:07d}"
    check_digit = calculate_check_digit(first_13_digits)
    public_user_id = int(f"{first_13_digits}{check_digit}")
    if public_user_id < PUBLIC_USER_ID_MIN or public_user_id > PUBLIC_USER_ID_MAX:
        raise ValueError("public_user_id must be a 14-digit number")
    return public_user_id


def parse_public_user_id(public_user_id: int) -> PublicUserIdParts:
    if public_user_id < PUBLIC_USER_ID_MIN or public_user_id > PUBLIC_USER_ID_MAX:
        raise ValueError("public_user_id must be a 14-digit number")

    # Store the ID as bigint for efficient indexing, but parse it as a fixed-width
    # 14-digit string when validating or showing the structured segments.
    value = str(public_user_id)
    first_13_digits = value[:13]
    check_digit = int(value[13])
    expected_check_digit = calculate_check_digit(first_13_digits)
    if check_digit != expected_check_digit:
        raise ValueError("public_user_id check digit mismatch")

    return PublicUserIdParts(
        product_code=value[:2],
        channel_code=value[2:4],
        year_code=value[4:6],
        sequence=int(value[6:13]),
        check_digit=check_digit,
    )


def _validate_fixed_digits(value: str, length: int, name: str) -> None:
    if len(value) != length or not value.isdigit():
        raise ValueError(f"{name} must be exactly {length} digits")
