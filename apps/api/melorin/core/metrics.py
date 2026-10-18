"""Small dependency-free Prometheus metrics plus alert state."""

import time
from collections import Counter
from threading import Lock

_lock = Lock()
_counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_alerts: dict[str, dict] = {}
_hist: dict[tuple[str, tuple[tuple[str, str], ...]], dict] = {}
_hist_buckets: dict[str, tuple[float, ...]] = {}

# M7.6: default latency buckets in seconds (Prometheus-style, cumulative on render).
DEFAULT_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def inc(name: str, **labels: str) -> None:
    with _lock:
        _counters[(name, tuple(sorted((k, str(v)) for k, v in labels.items())))] += 1


def set_gauge(name: str, value: float, **labels: str) -> None:
    with _lock:
        _gauges[(name, tuple(sorted((k, str(v)) for k, v in labels.items())))] = value


def observe(name: str, value: float, *, buckets: tuple[float, ...] = DEFAULT_BUCKETS, **labels: str) -> None:
    """Record one observation into a histogram (``_bucket``/``_sum``/``_count`` series on render)."""
    key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
    with _lock:
        bounds = _hist_buckets.setdefault(name, buckets)
        h = _hist.setdefault(key, {"counts": [0] * len(bounds), "sum": 0.0, "count": 0})
        for i, upper in enumerate(bounds):
            if value <= upper:
                h["counts"][i] += 1
        h["sum"] += value
        h["count"] += 1


def reset() -> None:
    """Forget every series (used by tests)."""
    with _lock:
        _counters.clear()
        _gauges.clear()
        _alerts.clear()
        _hist.clear()
        _hist_buckets.clear()


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _labels(pairs: tuple[tuple[str, str], ...], extra: str = "") -> str:
    parts = [f'{k}="{_esc(v)}"' for k, v in pairs]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


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
        alerts = list(_alerts.items())
        hists = [(k, {"counts": list(v["counts"]), "sum": v["sum"], "count": v["count"]}) for k, v in _hist.items()]
        bounds = dict(_hist_buckets)
    out: list[str] = []
    typed: set[str] = set()

    def declare(name: str, kind: str) -> None:
        if name not in typed:
            typed.add(name)
            out.append(f"# TYPE {name} {kind}")

    for (name, labels), value in rows:
        declare(name, "counter")
        out.append(f"{name}{_labels(labels)} {value}")
    for (name, labels), value in gauges:
        declare(name, "gauge")
        out.append(f"{name}{_labels(labels)} {value}")
    for (name, labels), h in hists:
        declare(name, "histogram")
        for upper, count in zip(bounds[name], h["counts"], strict=True):
            out.append(f"{name}_bucket{_labels(labels, f'le="{upper}"')} {count}")
        out.append(f"{name}_bucket{_labels(labels, 'le="+Inf"')} {h['count']}")
        out.append(f"{name}_sum{_labels(labels)} {h['sum']}")
        out.append(f"{name}_count{_labels(labels)} {h['count']}")
    for name, alert in alerts:
        declare("melorin_alert", "gauge")
        labels = f'alertname="{name}",severity="{alert["severity"]}",state="{alert["state"]}"'
        out.append(f"melorin_alert{{{labels}}} 1")
    return "\n".join(out) + ("\n" if out else "")
