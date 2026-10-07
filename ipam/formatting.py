from decimal import Decimal


NBSP = " "  # bo'linmas probel: summa jadvalda ikki qatorga bo'linib ketmasin


def money(value, currency=True):
    """1250000.5 -> "1 250 000,50 so'm"; butun sonlarda tiyinsiz."""
    if value is None or value == "":
        return "—"
    value = Decimal(value)
    text = f"{value:,.2f}".replace(",", NBSP).replace(".", ",")
    if text.endswith(",00"):
        text = text[:-3]
    return f"{text}{NBSP}so'm" if currency else text


def num(value):
    """Sonni ortiqcha nollarsiz: Decimal("10.00") -> "10", Decimal("2.50") -> "2,5"."""
    if value is None:
        return "—"
    text = f"{Decimal(value).normalize():f}"
    return text.replace(".", ",")


def fmt_date(value):
    return value.strftime("%d.%m.%Y") if value else "—"
