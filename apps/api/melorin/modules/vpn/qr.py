"""QR rendering for subscription links (pure python, no Pillow)."""

import io


def render_qr_png(data: str) -> bytes:
    """PNG QR code for ``data`` (pure-python, no Pillow needed)."""
    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()
