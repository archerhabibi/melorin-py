# I56: J11 Admin Security

Admin access now requires TOTP enrollment. Password login rejects a
super-admin without 2FA, and `require_admin` blocks administrative routes until
2FA is enabled. The login row is locked while the TOTP counter is checked and
persisted, so reusing a code in the same or an older 30-second window is
rejected.

The schema also introduces `admin_roles` metadata and migration `0007` as the
foundation for separating finance, support, and operator permissions. Existing
administrative routes remain owner-level until each route is assigned a role,
so this change does not pretend that RBAC is complete.
