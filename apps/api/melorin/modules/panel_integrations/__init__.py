"""Provider integration boundary: adapters, sessions, readers, capabilities and target config.

Everything that talks to (or translates the contract of) an external panel (Sanaei, PasarGuard, upstream bot) lives here.
It is the lowest feature layer: `vpn` (customer accounts) and `panelops` (admin actions) both depend on it, never the reverse.
"""
