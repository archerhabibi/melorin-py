# I48: Store-Scoped Reseller Model

Reseller applications and ownership are now scoped to a target store. An
active member of Main Store may apply to Main Store; an active member of any
other store may apply to that store. The same user may own reseller stores
under multiple parent stores, while duplicate applications remain blocked per
user and target store.

Every approved reseller store records `parent_store_id` and inherits the
parent currency. The financial invariant is explicit: customer purchases
debit `(customer, reseller_store, customer wallet)` and atomically post the
reseller cost against `(reseller owner, Main Store, reseller_credit wallet)`.
Both wallets are locked in stable order. Insufficient customer funds or an
exceeded debt limit abort the transaction before any ledger posting; an
unknown database failure rolls back the complete transaction and is eligible
for manual review through the existing order state machine.

This is account-scale, not concurrent-user capacity sizing: 10,000 to 100,000
registered accounts are supported as the product target. Peak concurrency,
orders per minute, and active VPN account counts remain deployment capacity
inputs and must be load-tested against the chosen PostgreSQL, Redis, worker,
and panel topology before production.
