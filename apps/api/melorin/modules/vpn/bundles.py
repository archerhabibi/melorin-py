import re


def clean_custom_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", value or "")[:40]
