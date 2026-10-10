# I24: webhook SSRF guard

The private-IP rejection is now outside the hostname parsing `ValueError`
handler, so `WebhookUrlError` cannot be swallowed. Direct private, loopback,
reserved, and IPv6 targets are rejected, and DNS-resolved private addresses
are checked before delivery as well.

Regression coverage includes private IPv4, IPv6, hostname, and resolved-IP
targets. Live DNS-rebinding and delivery tests still belong in staging.
