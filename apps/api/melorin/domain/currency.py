"""Per-store currency (v1.1). No implicit conversion between currencies."""


class CurrencyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


ALLOWED = {"IRT", "IRR", "USD", "EUR", "USDT", "AED", "TRY", "XTR"}


def normalize(code: str) -> str:
    c = (code or "").strip().upper()
    if c not in ALLOWED:
        raise CurrencyError("CURRENCY_UNSUPPORTED", f"واحد پول {code} پشتیبانی نمی‌شود.")
    return c


def require_same(*codes: str) -> str:
    s = {c for c in codes if c}
    if len(s) != 1:
        raise CurrencyError("CURRENCY_MISMATCH", "واحد پول ناهمخوان است؛ تبدیل خودکار ارز مجاز نیست.")
    return s.pop()
