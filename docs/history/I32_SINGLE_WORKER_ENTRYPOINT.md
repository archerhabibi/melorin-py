# I32: single worker entrypoint

ARQ is now the only supported worker runtime. The legacy polling loop was
removed from `worker/runner.py`; Compose and Makefile both launch
`arq melorin.worker.arq_app.WorkerSettings`.

The runner module remains the shared implementation boundary for claims and
handlers, but it is no longer an alternate process entrypoint with different
scheduling semantics.
