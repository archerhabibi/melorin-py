# Admin Web Architecture Review

> Audit date: 2026-11-13  
> Reviewed ref: `main`  
> Scope: static inspection of `apps/admin-web` and API paths called by its UI.  
> Status: documentation-only proposal. No application code or business behavior changed.

## 1. Executive summary

Admin Web is a React 18 + TypeScript + Vite application. Its navigation is **hash-based and state-driven**, not React Router. `main.tsx` handles session bootstrap, invitation acceptance and the error boundary. `App.tsx` owns the navigation groups, hash-to-section mapping, shell and permission-aware screen selection. `AdminSections.tsx` and `AdminExtra.tsx` dispatch sections to page views; most feature views are lazy-loaded.

The main architectural issue is not missing functionality or a need for a rewrite. It is that a flat list of 30 screens is grouped by mixed concepts (operations, sales, infrastructure and system), while several views combine cross-domain read models or settings. The recommendation is to clarify ownership, improve navigation, and extract features gradually while preserving existing hash URLs and Core API contracts.

**Keep the Modular Monolith. Keep Core API as the owner of business rules. Do not move pricing, wallet/ledger, order state, allocation, provisioning or reconciliation rules into the browser.**

## 2. Scope and method

Inspected:
- `apps/admin-web/package.json`
- `src/main.tsx`, `src/App.tsx`, `src/AdminSections.tsx`, `src/AdminExtra.tsx`
- `src/api.ts`, `src/adminAccess.ts`, `src/infra.tsx`
- Page views registered in `AdminExtra.tsx`, including reports, orders, payments, support, customers, stores/resellers, catalog, infrastructure, communications, identity, audit and admin team.

This is a static frontend audit. API paths below are extracted from UI calls; method, request/response schema, backend module ownership and exact authorization must be cross-checked against Core routers/OpenAPI before implementation. Where a page delegates to a helper or child component, its complete endpoint inventory must be completed in that follow-up pass.

## 3. Current application structure

### Entry and authentication
- `main.tsx` mounts `Root` inside `AdminErrorBoundary`.
- Invitation hashes render `AcceptInvite` without requiring an existing session.
- Otherwise, if there is no in-memory access token, the app posts to `/api/v1/auth/refresh` with credentials to refresh the session.
- A signed-in user sees `App`; otherwise `AdminAuth`.
- `api.ts` provides `authFetch` and `getJson`, bearer-token handling and one transparent refresh on 401. `getJson` uses `@melorin/api-client`; many feature views still call `authFetch` directly.

### Routing
- `groups` in `App.tsx` is the source of navigation titles and hash slugs.
- The Persian section title is the dispatch key; the slug is the URL key.
- Query parameters support deep links and screen state (selected panel, tab, filter, opening a drawer).
- Legacy `#/servers` redirects to `#/panels` because servers are managed within a panel.
- Legacy `#/identity-auto` redirects to `#/identity?tab=devices`.

Do not replace or rename these routes without compatibility redirects and tests. The current implementation is not a React Router route tree.

### Permission model
- `adminAccess.ts` maps each section to a permission area in `SECTION_AREA`.
- `sectionAllowed` filters navigation and redirects a user away from a disallowed section.
- `undefined` permissions mean not loaded yet; `[]` means no access.
- The file explicitly states that Core's `apps/api/melorin/domain/admin_access.py` is the authority for every request. UI permissions are not a security boundary.
- Keep the section-to-area mapping in sync with navigation; the source comments reference a test that checks every screen has an area.

## 4. Current menu and route inventory

There are **30 main screens**:

| Current group | Screen | Hash slug | View |
|---|---|---|---|
| Overview | داشبورد | `home` | Dashboard in App.tsx |
| Overview | گزارشات و نمودارها | `reports` | ReportsView |
| Operations | سفارش‌ها | `orders` | OrdersView |
| Operations | پرداخت‌ها | `payments` | PaymentsView |
| Operations | اکانت‌های VPN | `vpn` | VpnAccountsView |
| Operations | تیکت‌ها | `tickets` | TicketsView |
| Sales & customers | کاربران | `users` | UsersView |
| Sales & customers | فروشگاه‌ها | `stores` | StoresView |
| Sales & customers | نمایندگان | `resellers` | ResellersView |
| Sales & customers | درخواست‌های نمایندگی | `reseller-applications` | ResellerApplicationsView |
| Sales & customers | کارهای دستی | `manual-tasks` | ManualTasksView |
| Sales & customers | پیام همگانی | `broadcasts` | BroadcastView |
| Sales & customers | دکمه‌های تلگرام | `button-styles` | ButtonStylesView |
| Sales & customers | مرکز رویداد | `event-center` | EventCenterView |
| Sales & customers | کوپن‌ها | `coupons` | Coupons in AdminExtra.tsx |
| Sales & customers | برنامه‌های معرفی | `referral-programs` | ReferralProgramsView |
| Sales & customers | باشگاه مشتریان | `loyalty-club` | LoyaltyClubView |
| Infrastructure | پنل‌ها و سرورها | `panels` | PanelsView |
| Infrastructure | ادمین‌های پنل | `panel-admins` | PanelAdminsView |
| Infrastructure | بسته‌های فروش | `bundles` | BundlesView |
| Infrastructure | محصولات VPN | `products` | ProductsView |
| Infrastructure | سلامت زیرساخت | `infra-health` | InfraHealthView |
| Infrastructure | عملیات پنل | `panel-ops` | PanelOpsView |
| Infrastructure | عملیات گروهی | `bulk-operations` | BulkOperationsView |
| Infrastructure | حجم فروشگاه‌ها | `store-governance` | StoreGovernanceView |
| System | تنظیمات | `settings` | Settings in AdminExtra.tsx |
| System | ممیزی | `audit` | AuditView |
| System | هویت | `identity` | IdentityHubView |
| System | مدیران سامانه | `admin-team` | AdminTeamView |
| System | حساب من | `my-account` | MyAccount |

Login, invite acceptance and the global error boundary are application-level flows, not entries in this 30-screen menu.

## 5. Screen-to-API map and domain ownership

The table records concrete API paths visible in the page code. Dynamic IDs and action names are intentionally represented as parameters.

| Screen | API paths observed in frontend | Domain owner (recommended) |
|---|---|---|
| Session / shell | `POST /api/v1/auth/refresh`, `GET /api/v1/admin/me`, `GET /api/v1/me`, `POST /api/v1/auth/logout` | Identity / Admin Access |
| Dashboard | `/api/v1/admin/reports/summary`, `/orders`, `/health`, `/operations/backups`, `/users`, `/tickets`, `/stores`, `/reseller-applications?status=pending`, `/panel-admin-requests?status=pending`, `/manual-tasks?status=open`; export `/reports/orders.csv`; refund `/payments/{id}/refund` | Aggregated Overview; each source/action remains owned by its domain |
| Reports | `/api/v1/admin/reports/analytics`, `/api/v1/admin/reports/analytics.csv`, stores lookup | Reports / Analytics |
| Orders | `/api/v1/admin/orders`, stores, users, `/orders/{id}/{retry|manual-review|refund}` | Orders; financial refund semantics owned by central Payments/Financial use case |
| Payments | `/api/v1/admin/payments`, `/api/v1/admin/settings`, `/payments/{id}/{action}`, `/payments/{id}/receipt`, `/settings/{key}` | Payments / Payment Methods |
| Tickets | `/api/v1/admin/tickets` plus conversation/action calls in ticket child components | Support |
| Users | `/api/v1/admin/users`, `/api/v1/admin/stores` | Customers / Identity, with Stores as ownership source |
| Stores | `/api/v1/admin/stores`, `/api/v1/admin/users` | Stores |
| Resellers | `/api/v1/admin/resellers`, `/api/v1/admin/resellers/{id}` | Reseller capability / Stores |
| Reseller applications | `/api/v1/admin/reseller-applications`, `/{id}/review`, `/{id}/verify-bot` | Reseller onboarding |
| VPN accounts | `/api/v1/admin/vpn-accounts` (query/state/store/limit/offset), stores lookup | Customer Subscriptions / Provisioning read model |
| Products | `/api/v1/admin/products` via shared infra hook; stores lookup; shared panels/servers/bundles data | Catalog / Products |
| Sales bundles | `/api/v1/admin/bundles` via shared infra hook; stores lookup; shared panels/servers/products data | Catalog / Sales Bundles |
| Panels and servers | `/api/v1/admin/panels`, `/servers`, `/panels/{id}/health`, `/panels/{id}/state`, `/servers/{id}/state`, panel/server CRUD paths | Infrastructure / Panel Adapters |
| Panel admins | `/api/v1/admin/panel-admins`, `/panel-admins/profile`, `/panel-admins/{id}/credentials`, `/panel-admins/{id}/reset-password`, `/panel-admin-requests?status=...`, `/panel-admin-requests/{id}/{apply|reject}`, `/panel-admins/sync` | Infrastructure / Panel Operator Accounts |
| Infrastructure health | shared infra lists; `/api/v1/admin/panels/{id}/health` | Infrastructure Health |
| Panel operations | `/api/v1/admin/reconciliation/summary`, `/reconciliation/issues`, `/reconciliation/issues/{id}/action`, `/panel-orphans`, `/panel-orphans/{id}/ignore`, `/panels/{id}/nodes`, `/panels/{id}/reconcile`, stores/panels lookups | Provisioning / Reconciliation / Infrastructure |
| Bulk operations | `/api/v1/admin/bulk-operations?limit=20`, `/bulk-operations/preview`, `/{id}/confirm`, `/{id}/{action}`, `/{id}?limit=100`; panels and stores lookups | Bulk Operations; actual execution in Core/Worker |
| Store governance | `/api/v1/admin/store-admins`, `/store-admins/refresh`, `/store-admins/{id}`, `/resellers/{store_id}/suspend-policy` | Store Governance / Reseller Policy |
| Manual tasks | `/api/v1/admin/manual-tasks?status=all`, `/manual-tasks/{id}/{verb}` | Operations / Human Onboarding Tasks |
| Broadcasts | `/api/v1/admin/broadcasts`, `/broadcasts/audiences` | Communications |
| Telegram event center | `/api/v1/admin/event-center`, `/test`, `/check`, `/provision` | Communications / Telegram Delivery |
| Coupons | `/api/v1/admin/coupons`, `/coupons/{id}`, stores lookup | Promotions / Coupons |
| Referral | `/api/v1/admin/referral-rules?store_id=...`, `/stores/{id}/referrals/summary`, stores lookup | Referral |
| Loyalty | `/api/v1/stores/{id}/loyalty/manage`, stores lookup | Loyalty |
| Identity hub | `/api/v1/admin/identity-link-reviews?status=open`; review/auto/devices tabs delegate to child views | Identity / Account Linking |
| Admin team | `/api/v1/admin/admins` and role listing | Admin Team / Access Control |
| Audit | `/api/v1/admin/audit`, users and stores lookups | Audit |
| Settings | `/api/v1/admin/settings`, `/settings/{key}`, `/feature-flags`, `/feature-flags/{key}`, `/integrations`, `/integrations/{admin-access|email|backup-s3}`, `/auth/admin/password`; Google, Telegram and OCR settings are delegated to child components | System Configuration / Integrations / Identity |
| My account | `/api/v1/admin/me`, `/api/v1/auth/admin/password` | Self-service Identity |

**Inventory caveat:** helper and child components can make additional calls (notably TicketConversation, payment parts, identity sub-tabs and social-login settings). The list above is a page-level map of visible paths, not a generated exhaustive OpenAPI inventory.

## 6. Overlaps, duplication and boundaries

| Area | Evidence | Recommendation |
|---|---|---|
| Orders / Payments / Dashboard | Refund entry points exist in dashboard and order/payment workflows | One Core financial use case with shared permission, audit and idempotency semantics; UI entry points may remain contextual |
| Users / Stores / Resellers | Users and Stores fetch each other's lists; Resellers is store-centric | Store is the primary entity; reseller is a Store type/capability; application is a separate onboarding workflow |
| Products / Bundles / Infrastructure | Products and Bundles use shared `useInfra` data; both are currently under Infrastructure menu | Move Catalog pages under Commerce; keep shared read model, never move allocation rules to frontend |
| Panel Ops / Health / Bulk | Related operational views cover health, reconciliation and bulk execution | Provide an Operations Center aggregator and deep links; keep commands owned by Infrastructure/Provisioning/Bulk domains |
| Settings / My Account / Admin Team | Password and identity settings are spread across system settings and self-service; Admin Team owns staff access | My Account for self-service; Admin Team for staff and roles; System Settings for global configuration |
| Dashboard / Reports | Dashboard summary and analytics report are separate read models | Keep distinct: dashboard = operational pulse; reports = period-based analysis/export |
| Ticket fallback | AdminSections has a simple tickets/payments route fallback, while AdminExtra registers full TicketsView/PaymentsView | Keep one canonical view per section; remove fallback only after route tests prove it is unreachable and unnecessary |
| Store lookup duplication | Several screens independently load stores/users for labels and ownership | Consider shared cache/read-model only if measured; duplicated GET calls do not imply duplicated business logic |

The following are **not** duplicate domains: Orders vs Payments; Referral vs Commission vs Loyalty; Panel vs Server (server is a capacity unit owned by one panel); Bulk Operations vs Provisioning/Reconciliation.

## 7. Proposed navigation

1. **Overview:** Dashboard; Operations Center (aggregated status and deep links); Reports.
2. **Commerce & Catalog:** Orders; Payments and receipts; VPN Products; Sales Bundles; Coupons.
3. **Customers & Support:** Users; VPN Accounts; Tickets; Identity and account linking.
4. **Stores & Resellers:** Stores; Resellers; Reseller Applications; Store Policies/Quotas; panel operator accounts (final placement depends on backend meaning).
5. **Growth & Loyalty:** Referral; Commission (if/when a dedicated screen exists); Loyalty Club.
6. **Infrastructure:** Panels and Servers; Infrastructure Health; Panel Operations/Reconciliation; Bulk Operations.
7. **Communications:** Broadcasts; Telegram Event Center; Telegram Button/Appearance settings.
8. **Administration & Security:** Admin Team; Audit; System Settings; Integrations; My Account (preferably under user menu).

Operations Center is an aggregator, not a new domain owner. Coupons should have one canonical menu location, not be duplicated across Commerce and Growth.

## 8. Current-to-proposed page relocation

| Current page | Proposed location |
|---|---|
| Dashboard | Overview |
| Reports | Overview / Reports |
| Orders | Commerce |
| Payments | Commerce |
| Products | Commerce & Catalog |
| Sales Bundles | Commerce & Catalog |
| Coupons | Commerce & Catalog |
| Users | Customers & Support |
| VPN Accounts | Customers & Support |
| Tickets | Customers & Support |
| Identity | Customers & Support |
| Stores | Stores & Resellers |
| Resellers | Stores & Resellers |
| Reseller Applications | Stores & Resellers |
| Store Governance | Stores & Resellers |
| Panel Admins | Stores & Resellers or Infrastructure after domain confirmation |
| Referral Programs | Growth & Loyalty |
| Loyalty Club | Growth & Loyalty |
| Manual Tasks | Overview / Operations Center |
| Infrastructure Health | Infrastructure |
| Panel Operations | Infrastructure |
| Bulk Operations | Infrastructure |
| Broadcasts | Communications |
| Event Center | Communications |
| Telegram Button Styles | Communications |
| Settings | Administration & Security, split into focused sub-pages |
| Audit | Administration & Security |
| Admin Team | Administration & Security |
| My Account | User menu / Administration & Security |

Keep current hash slugs stable during the navigation-only migration. New grouping must not break bookmarks.

## 9. Proposed frontend feature structure

This is a target structure, not a request for a big-bang file move:

```text
src/
  app/
    shell/          # AdminShell, navigation, header
    routing/        # hash router, route registry, legacy redirects
    auth/           # session, sign-in, invite acceptance
  features/
    overview/
    commerce/
      orders/
      payments/
      products/
      bundles/
      coupons/
    customers/
      users/
      vpn-accounts/
      identity/
      support/
    stores/
      stores/
      resellers/
      applications/
      governance/
      panel-admins/
    growth/
      referrals/
      loyalty/
    infrastructure/
      panels/
      health/
      reconciliation/
      bulk-operations/
    communications/
      broadcasts/
      event-center/
      bot-appearance/
    reports/
    administration/
      team/
      audit/
      settings/
      integrations/
      my-account/
  shared/
    api/            # auth, refresh, typed client, errors
    permissions/
    ui/
    hooks/
    types/
```

### TypeScript and API client

The admin package already has TypeScript, `typecheck`, and an `@melorin/api-client` dependency. Therefore, a TypeScript migration is not a separate project. The real opportunity is to reduce permissive `Json`/generic record types and use precise generated DTOs. Gradually move API calls behind feature-specific typed clients while keeping shared authentication/refresh in `shared/api`.

## 10. Backend changes to evaluate (not assumed required)

1. Verify that refund entry points use one financial command with idempotency, audit events and permission enforcement.
2. Document Product, Sales Bundle and Bundle→Panel relationships in Core; allocation/readiness decisions remain server-owned.
3. Confirm reseller is represented as Store type/capability, with onboarding as a distinct workflow.
4. Clarify Identity, Admin Team, roles and permission policy boundaries.
5. Standardize operational status, retry, idempotency and audit contracts for backups, reconciliation, provisioning, bulk jobs and manual tasks.
6. Split global settings, payment settings, integrations, feature flags and self-service security by ownership and permission.
7. Explain and test the Loyalty endpoint under `/api/v1/stores/{id}/loyalty/manage` alongside the predominantly admin-prefixed endpoints.
8. Add aggregate/lookup read models only when measured latency, repeated network load or consistency problems justify them.

Do not rename API paths merely to make them look uniform. First compare each route to Core routers and OpenAPI.

## 11. Migration and test plan

### Phase 0 — baseline
- Snapshot the current 30 menu entries, hash slugs and permission mapping.
- Extract exact methods, schemas and permissions from Core routers/OpenAPI.
- Test all current deep links and legacy redirects.
- Record lint, typecheck, Vitest, build and first-load bundle budgets.

### Phase 1 — contract clarity
- Introduce one route registry containing slug, title, feature and permission area.
- Make navigation and permission mapping consume that registry.
- Record each feature's API contract and domain owner.
- Add integration tests for financial and provisioning actions.

### Phase 2 — navigation-only change
- Reorganize groups without moving files or changing API contracts.
- Preserve old slugs and redirects.
- Add a lightweight Operations Center with deep links.
- Split Settings into focused tabs/sub-pages without changing endpoint semantics.

### Phase 3 — gradual feature extraction
Suggested order: Communications and Administration; Reports and Overview; Customers and Support; Stores and Resellers; Commerce and Payments; Infrastructure and Provisioning.
Move one feature at a time, test, release and retain rollback capability.

### Phase 4 — typed API and measured deduplication
- Expand `@melorin/api-client` usage.
- Generate precise DTOs from OpenAPI.
- Reduce untyped payloads in mutation paths.
- Remove duplicate fetches only with a clear cache/read model and tests.
- Remove legacy fallbacks only after usage and route tests confirm safety.

### Acceptance tests
- All 30 existing slugs resolve to the correct view.
- Query-based deep links for panels, bundles, products and identity work.
- `#/servers` and `#/identity-auto` redirect correctly.
- Owner, manager, finance, support and viewer see correct navigation and actions.
- Loading permissions, empty permissions, 401, failed refresh, logout and invitation acceptance are covered.
- Server rejects unauthorized direct API calls; hiding a menu item is not security.
- Refund, payment review, provisioning retry, reconciliation and bulk actions have audit and idempotency coverage.
- Store/tenant isolation is tested across Orders, Payments, Users, Resellers, Referral and Loyalty.
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` and bundle budgets pass.
- Backup/restore, worker heartbeat, Telegram/provider integration checks remain in release gates.

## 12. Final decisions

- Preserve the Modular Monolith; microservices do not solve a frontend navigation problem.
- Do not rewrite the admin app wholesale.
- Keep Core as the only authority for pricing, wallet/ledger, orders, payments, allocation, provisioning and reconciliation rules.
- Treat reseller as a Store subtype/capability in UI; keep application onboarding distinct.
- Build Operations Center as an aggregator, not a new command owner.
- Keep backend authorization authoritative.
- Stabilize route registry, API contracts and tests before moving files.

## Code references

- [Admin shell, menu and hash navigation](../apps/admin-web/src/App.tsx)
- [Entry point and session flow](../apps/admin-web/src/main.tsx)
- [Section dispatch](../apps/admin-web/src/AdminSections.tsx)
- [Lazy view registry and settings](../apps/admin-web/src/AdminExtra.tsx)
- [API auth and client wrapper](../apps/admin-web/src/api.ts)
- [UI permission mapping](../apps/admin-web/src/adminAccess.ts)
- [Shared infrastructure read model](../apps/admin-web/src/infra.tsx)
- [Admin package scripts](../apps/admin-web/package.json)
