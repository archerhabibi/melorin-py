# I55: J10 Async Password KDF

Password hashing and verification use scrypt and are intentionally
CPU-expensive. They were previously called synchronously from async request
handlers, blocking the entire event loop during login and password changes.

The KDF now runs through `asyncio.to_thread` in the default worker pool.
Authentication and password-setting call sites await the operation, and the
bootstrap CLI awaits the same safe implementation. The cryptographic
parameters remain unchanged, so this fixes event-loop starvation without
changing stored password compatibility.
