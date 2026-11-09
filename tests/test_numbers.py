import pytest

from app.utils.numbers import (
    NumberParseError,
    format_money,
    format_percent,
    parse_int,
    parse_number,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.5", 1234.5),
        ("1,234.50", 1234.5),
        ("$ 1 200", 1200.0),
        ("EUR 99", 99.0),
        ("(300)", -300.0),
        ("-42", -42.0),
        ("12%", 12.0),
        ("1.234,56", 1234.56),
        ("1,5", 1.5),
        ("1,000", 1000.0),
        ("1.234.567", 1234567.0),
        (7, 7.0),
        (2.5, 2.5),
    ],
)
def test_parse_number_accepts_common_formats(text, expected):
    parsed = parse_number(text)
    assert parsed.value == pytest.approx(expected)
    assert parsed.warning is None


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_is_zero_with_visible_warning(blank):
    parsed = parse_number(blank, "Amount")
    assert parsed.value == 0.0
    assert parsed.warning == "Amount was blank, so 0 was used."


@pytest.mark.parametrize("bad", ["abc", "1-2", "--", "$", float("nan"), float("inf"), True])
def test_parse_number_rejects_garbage(bad):
    with pytest.raises(NumberParseError):
        parse_number(bad)


def test_parse_int_requires_whole_number():
    assert parse_int("12").value == 12
    with pytest.raises(NumberParseError):
        parse_int("1.5")


def test_format_money():
    assert format_money(1234.5) == "$1,234.50"
    assert format_money(-1234.5, "EUR ") == "-EUR 1,234.50"
    assert format_money(-0.001) == "$0.00"
    assert format_money(float("nan")) == "N/A"


def test_format_percent():
    assert format_percent(12.345) == "12.3%"
    assert format_percent(None) == "N/A"
    assert format_percent(-0.01) == "0.0%"
