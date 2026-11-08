"""What an order remembers about the product it sold (pure: reads attributes, imports nothing of ours).

Lives in the domain layer so that both ``catalog`` (new orders) and ``vpn`` (manual assignment of a panel user) can write
the same shape without ``vpn`` depending on ``catalog``.
"""

from __future__ import annotations

from typing import Any


def product_snapshot(p: Any) -> dict:
    return {
        "id": str(p.id),
        "code": p.code,
        "name": p.name,
        "duration_days": p.duration_days,
        "traffic_gb": p.traffic_gb,
        "max_devices": p.max_devices,
    }
