# @melorin/api-client

Generated client boundary for `/api/v1`. In the production web builds, generate TypeScript types from Core OpenAPI (`openapi-typescript`) and keep all channel calls here. Channels must not implement pricing, wallet, order, payment or provisioning logic.

## Verbs

- `get/post/put/patch/delete(path, init)` — typed request, parsed JSON in `result.data` / `result.error`, raw `result.response`.
- `rawGet(path, init)` — typed GET that returns the **unread** `Response` (receipt images, CSV, other binary bodies). Path and path parameters are checked against the OpenAPI snapshot; same bearer token and single refresh-on-401 as the other verbs.
- `raw(path, init)` — untyped escape hatch for already-built paths and pre-serialised bodies; prefer the typed verbs.
