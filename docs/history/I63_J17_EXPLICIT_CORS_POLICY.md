# I63: J17 Explicit CORS Policy

CORS no longer uses wildcard methods or headers while credentials are enabled.
The API has explicit configurable allowlists for origins, methods, and
headers. Outside development, wildcard values are rejected during settings
validation, preventing an accidental broad cross-origin policy from reaching
staging or production.

The example environment documents the JSON configuration and includes only
the headers required by browser/API flows: authorization, content type,
idempotency, bot service, request correlation, and accept.
