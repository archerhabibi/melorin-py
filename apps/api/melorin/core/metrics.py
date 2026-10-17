"""Small dependency-free Prometheus metrics plus alert state."""

import time
from collections import Counter
from threading import Lock

_lock = Lock()
_counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_alerts: dict[str, dict] = {}


def inc(name: str, **labels: str) -> None:
    with _lock:
        _counters[(name, tuple(sorted((k, str(v)) for k, v in labels.items())))] += 1


def set_gauge(name: str, value: float, **labels: str) -> None:
    with _lock:
        _gauges[(name, tuple(sorted((k, str(v)) for k, v in labels.items())))] = value


def set_alert(name: str, firing: bool, *, summary: str, severity: str = "warning", details: str = "") -> None:
    with _lock:
        state = "firing" if firing else "resolved"
        previous = _alerts.get(name, {}).get("state")
        _alerts[name] = {
            "state": state,
            "severity": severity,
            "summary": summary,
            "details": details,
            "changed_at": time.time() if previous != state else _alerts.get(name, {}).get("changed_at", time.time()),
        }


def alert_snapshot() -> dict[str, dict]:
    with _lock:
        return {name: dict(value) for name, value in _alerts.items()}


def render() -> str:
    with _lock:
        rows = list(_counters.items())
        gauges = list(_gauges.items())
    out = []
    for (name, labels), value in rows:
        label_text = ",".join(f'{k}="{v.replace(chr(92), chr(92) + chr(92)).replace(chr(34), chr(92) + chr(34))}"' for k, v in labels)
        out.append(f"{name}{{{label_text}}} {value}" if label_text else f"{name} {value}")
    for (name, labels), value in gauges:
        label_text = ",".join(f'{k}="{v.replace(chr(92), chr(92) + chr(92)).replace(chr(34), chr(92) + chr(34))}"' for k, v in labels)
        out.append(f"{name}{{{label_text}}} {value}" if label_text else f"{name} {value}")
    for name, alert in _alerts.items():
        labels = f'alertname="{name}",severity="{alert["severity"]}",state="{alert["state"]}"'
        out.append(f"melorin_alert{{{labels}}} 1")
    return "\n".join(out) + ("\n" if out else "")
