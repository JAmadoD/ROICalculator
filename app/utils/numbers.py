"""Number parsing and formatting helpers. Pure Python, no Qt."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


class NumberParseError(ValueError):
    """Raised when text cannot be read as a number."""


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    value: float
    warning: str | None = None


_ALLOWED = re.compile(r"[^0-9.,\-]")


def parse_number(text: Any, field: str = "Value") -> ParsedNumber:
    """Read a number typed by a person.

    Accepts things like "1,234.50", "$ 1 200", "(300)", "12%", "1.234,5".
    Blank text gives 0 with a warning, so the caller can show it.
    Anything that is not a number raises NumberParseError.
    """
    if text is None:
        return ParsedNumber(0.0, f"{field} was blank, so 0 was used.")
    if isinstance(text, bool):
        raise NumberParseError(f"{field} is not a number.")
    if isinstance(text, (int, float)):
        value = float(text)
        if not math.isfinite(value):
            raise NumberParseError(f"{field} must be a finite number.")
        return ParsedNumber(value)

    raw = str(text).strip()
    if not raw:
        return ParsedNumber(0.0, f"{field} was blank, so 0 was used.")

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1].strip()

    cleaned = _ALLOWED.sub("", raw)
    if cleaned.startswith("-"):
        negative = not negative
        cleaned = cleaned[1:]
    if "-" in cleaned or not any(ch.isdigit() for ch in cleaned):
        raise NumberParseError(f'{field} "{text}" is not a number.')

    cleaned = _normalize_separators(cleaned)
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise NumberParseError(f'{field} "{text}" is not a number.') from exc
    if not math.isfinite(value):
        raise NumberParseError(f"{field} must be a finite number.")
    return ParsedNumber(-value if negative else value)


def _normalize_separators(text: str) -> str:
    """Turn grouping and decimal separators into a plain float string."""
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        # Whichever separator comes last is the decimal mark.
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")
    if has_comma:
        parts = text.split(",")
        # A single comma followed by one or two digits is a decimal comma.
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            return parts[0] + "." + parts[1]
        return text.replace(",", "")
    if text.count(".") > 1:
        # "1.234.567" style grouping.
        return text.replace(".", "")
    return text


def parse_int(text: Any, field: str = "Value") -> ParsedNumber:
    """Like parse_number but the value must be a whole number."""
    parsed = parse_number(text, field)
    if abs(parsed.value - round(parsed.value)) > 1e-9:
        raise NumberParseError(f"{field} must be a whole number.")
    return ParsedNumber(float(round(parsed.value)), parsed.warning)


def format_money(value: float, symbol: str = "$", decimals: int = 2) -> str:
    """Format a money amount, for example -1234.5 -> "-$1,234.50"."""
    if value is None or not math.isfinite(value):
        return "N/A"
    if abs(value) < 0.5 * 10 ** (-decimals):
        value = 0.0
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.{decimals}f}"


def format_percent(value: float | None, decimals: int = 1) -> str:
    """Format a percentage that is already scaled (12.5 -> "12.5%")."""
    if value is None or not math.isfinite(value):
        return "N/A"
    if abs(value) < 0.5 * 10 ** (-decimals):
        value = 0.0
    return f"{value:,.{decimals}f}%"
