# I57: J12 Fixed Payment Callback Origin

Payment callback URLs no longer derive from the incoming request's Host or
scheme. They are built from `MELORIN_PUBLIC_API_URL`, a deployment-controlled
origin. Non-development environments require an absolute HTTPS value during
startup, preventing forged Host headers and incorrect HTTP callbacks behind a
reverse proxy.
