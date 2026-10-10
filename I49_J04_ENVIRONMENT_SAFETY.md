# I49: J04 Environment Safety

`MELORIN_ENV` is now a closed enum: only `development`, `staging`, and
`production` are accepted. Values such as `prod` or `Production ` fail during
settings construction instead of silently bypassing production safeguards.

Outside development, startup now validates the Fernet encryption key and
requires absolute `http`/`https` CORS origins. This prevents the service from
booting with an invalid encryption key or malformed cross-origin policy.
Regression tests cover invalid environment values, invalid/valid Fernet keys,
and production security settings.
