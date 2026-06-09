from app.services.life_records.service import infer_record_type_for_query, parse_life_record_text


def test_parse_expense_record() -> None:
    record = parse_life_record_text("记账 午饭花了 35 元")

    assert record is not None
    assert record.record_type == "expense"
    assert record.amount is not None
    assert str(record.amount) == "35"
    assert record.currency == "CNY"


def test_parse_weight_record() -> None:
    record = parse_life_record_text("记录体重 70.5 kg")

    assert record is not None
    assert record.record_type == "weight"
    assert str(record.amount) == "70.5"
    assert record.currency == "kg"


def test_infer_expense_query_type() -> None:
    assert infer_record_type_for_query("最近花了多少") == "expense"
