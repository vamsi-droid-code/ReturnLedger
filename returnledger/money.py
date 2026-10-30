"""Integer-cent money helpers. All rounding is half-up and deterministic."""


def half_up_div(numerator: int, denominator: int) -> int:
    """Round numerator/denominator half-up for non-negative integers."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        return -half_up_div(-numerator, denominator)
    return (2 * numerator + denominator) // (2 * denominator)


def apply_rate(cents: int, rate_bp: int) -> int:
    """cents * rate, where rate is in basis points (1/10000)."""
    return half_up_div(cents * rate_bp, 10_000)


def prorate(total_cents: int, part: int, whole: int) -> int:
    """Share of total_cents for `part` units out of `whole` units."""
    return half_up_div(total_cents * part, whole)


def fmt(cents) -> str:
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"


def parse(text: str) -> int:
    text = text.strip()
    neg = text.startswith("-")
    if neg:
        text = text[1:]
    whole, _, frac = text.partition(".")
    frac = (frac + "00")[:2]
    value = int(whole or 0) * 100 + int(frac)
    return -value if neg else value
