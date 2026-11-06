"""Panel health vocabulary (PG-01): the one place that says which panel states may receive NEW orders."""

HEALTHY, DEGRADED, UNHEALTHY = "healthy", "degraded", "unhealthy"
# ``degraded`` = some node fails but at least one still serves customers, so the panel keeps selling; ``unhealthy`` leaves server selection.
SELLABLE_STATES = (HEALTHY, DEGRADED)
