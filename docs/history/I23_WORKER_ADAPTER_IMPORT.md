# I23: worker adapter registry import

The worker now imports `build_adapter` at module scope from the VPN adapter
registry. Renewal rollback and account revocation therefore resolve the adapter
without the runtime `NameError` reported in the review.
