"""URL helpers shared by the Google and Telegram login flows (audit T02: one ``_origin`` instead of copies)."""

from urllib.parse import urlparse


def origin(url: str | None) -> str | None:
    """Reduce ``url`` to ``scheme://host[:port]`` (http/https only), or ``None`` when it is not such a URL."""
    p = urlparse((url or "").strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None
