# I36: operations CLI

The operational CLI now supports:

```text
python -m melorin.cli bootstrap
python -m melorin.cli outbox-replay EVENT_UUID
python -m melorin.cli rotate-encryption-key NEW_FERNET_KEY
```

`outbox-replay` resets one event to pending and clears its error state.
`rotate-encryption-key` re-encrypts the explicitly modeled Store bot tokens,
panel credentials, and payment secrets in one transaction. It does not perform
a blind JSON rewrite or silently rotate unknown fields.
