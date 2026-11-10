"""Panel operations (audit T66): everything an admin does TO a panel, as opposed to selling and delivering VPN accounts (``modules/vpn``).

Operations console, panel readings and Prometheus gauges, settings drift, panel backup verification, the store role and sub-branding.
This package sits ABOVE ``vpn`` in the import stack: it may use ``vpn`` (adapters, capabilities, sync...), and ``vpn`` may never import it.
"""
