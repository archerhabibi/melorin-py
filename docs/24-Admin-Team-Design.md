# 24 - Admin team: roles and invitations

Status: implemented (migration `0055_admin_team`). Code: `domain/admin_access.py`, `domain/password_policy.py`,
`modules/identity/admin_team.py`, `modules/admin/admins.py`, `modules/identity/routes/admin_invite.py`; web: `AdminTeamView`, `AcceptInvite`, `MyAccountView`.

## Model
Everyone who signs in to the admin panel has `users.is_super_admin = true` (the channel gate: password + TOTP).
What they may do is the role in `users.admin_roles`. The first known role wins; an empty or unknown list has **no access** (fail closed).
The migration gives every existing admin `owner`, so nobody loses access on upgrade.

## Permission matrix (r = read, rw = read + write)
| Area | owner | manager | finance | support | viewer |
|---|---|---|---|---|---|
| overview, reports | rw | rw | r | overview r | r |
| orders | rw | rw | rw | r | r |
| payments | rw | rw | rw | r | r |
| catalog | rw | rw | r | r | r |
| infrastructure | rw | rw | - | - | r |
| resellers | rw | rw | r | - | r |
| customers | rw | rw | r | rw | r |
| support | rw | rw | - | rw | r |
| audit | rw | r | - | - | - |
| system (settings, integrations, flags) | rw | - | - | - | - |
| admins (this feature) | rw | - | - | - | - |
| self (own password, `/admin/me`) | rw | rw | rw | rw | rw |

## Enforcement
* `require_admin_session` runs `admin_area_guard`: the request path maps to an area via the ordered `PATH_RULES` (first match wins);
  GET/HEAD = read, other methods = write; GETs that reveal secrets (panel credentials, service access, bank-SMS token) count as writes.
* A path no rule knows maps to `system` (owner only), so a new route is too strict, never too open.
* Store-context endpoints (reseller panel, loyalty, referrals) additionally need the matching resellers + catalog grants.
* Denials return 403 `ADMIN_ROLE_FORBIDDEN` and record the security event `admin_area_denied`.
* The web hides screens using `GET /admin/me` permissions, as a convenience only.

## Invitation flow
1. The owner invites an e-mail + role: an inactive shell user plus a one-time token (256 bit, stored as SHA-256, 72 h, one live invite per user). The link is shown once and e-mailed when mail is configured; it lives in the URL fragment (`/#/accept-invite?t=...`).
2. The invitee opens it (`inspect`), starts enrolment (`enroll`: their own TOTP seed and QR), then `accept` with a password that passes the policy and one valid TOTP code. Five wrong codes lock the invite.
3. No session is issued; the invitee signs in through the normal password + TOTP login.
Public endpoints are rate limited (20 per 5 min per IP).

## Safeguards
* Nobody can demote, suspend, remove or reset themselves; the last active owner is protected.
* Suspend, remove and reset-access revoke refresh tokens. A removed admin is archived (audit trail still resolves) and can be re-invited from scratch.
* Password policy: 12+ characters, not repetitive, not containing the e-mail name, not common, mixed character classes.
* Every change is written to the audit log; no secret is ever logged.
