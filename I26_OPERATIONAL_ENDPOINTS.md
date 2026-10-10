# I26: operational endpoint exposure

Production API docs, ReDoc, and OpenAPI are now disabled at the FastAPI
application level. Caddy explicitly returns `404` for those paths and for
`/metrics` on both public domains instead of proxying them.

Health endpoints remain public for load-balancer checks. Prometheus should
scrape the API service directly on the backend network, not through a public
domain.
