"""Panel operations (audit T66): everything an admin does TO a panel, as opposed to selling and delivering VPN accounts (``modules/vpn``).

Operations console, panel readings and Prometheus gauges, settings drift, panel backup verification, the store role and sub-branding,
the store's admin on each panel (``panel_admins``), volume governance and usage, service access, panel-event admin, bulk operations,
subscription checks, account re-creation on a panel and the store digest (moved here from ``vpn``, arch review 2026-11-13 §4.1).
This package sits ABOVE ``vpn`` in the import stack: it may use ``vpn`` (adapters, capabilities, sync...), and ``vpn`` may never import it.
"""
