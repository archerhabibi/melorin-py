# I19: outbox session safety and replay protection

Outbox claims are committed before processing. The worker therefore reloads
each event by ID in the processing session, locks that row, and updates the
same managed instance to `processed`.

Failures reload the row again before scheduling a bounded retry. Provisioning
remains guarded by the order state machine, so a replayed `ORDER_PAID` event
cannot create a second account after the order is completed.
