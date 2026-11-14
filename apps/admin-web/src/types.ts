import type { ReactNode } from 'react';
// Shared structural types for admin-web (TypeScript migration, T-O03 / T-R11).
// Server payloads that are not yet bound to a generated @melorin/api-client schema use these aliases, so every
// remaining loose spot is greppable (`Json`) and can be tightened one view at a time.

export type { Rec, Json, CallFn, WithChildren, Toast, Id } from '@melorin/web-kit/types';

/** Row of GET /api/v1/admin/orders (mirrors apps/api/melorin/modules/admin/orders.py). */
export interface AdminOrderRow {
  id: string;
  number: string;
  user_id: string;
  store_id: string;
  status: string;
  total: number;
  currency: string;
  needs_review: boolean;
  created_at: string;
}

/** Admin team (apps/api/melorin/modules/admin/admins.py). */
export interface AdminMember {
  id: string;
  email: string | null;
  display_name: string | null;
  role: string | null;
  role_label: string | null;
  state: 'active' | 'invited' | 'invite_expired' | 'suspended';
  is_active: boolean;
  totp_enabled: boolean;
  is_self: boolean;
  created_at: string;
  last_login_at: string | null;
  invite_expires_at: string | null;
}
export interface AdminRoleInfo {
  key: string;
  label: string;
  description: string;
  permissions: string[];
}
export interface AdminInviteResult {
  admin: AdminMember;
  invite_path: string;
  invite_url: string | null;
  expires_at: string;
  emailed: boolean;
}
export interface AdminMe {
  id: string;
  email: string | null;
  display_name: string | null;
  role: string | null;
  role_label: string | null;
  is_owner: boolean;
  permissions: string[];
}
/** POST /auth/admin-invite/inspect and /enroll (apps/api/melorin/modules/identity/routes/admin_invite.py). */
export interface AdminInviteInfo {
  email: string;
  display_name: string | null;
  role: string;
  role_label: string;
  expires_at: string;
}
export interface AdminEnrollment {
  secret: string;
  otpauth_url: string;
  qr_data_uri: string;
}
/** What a screen needs from the app shell: the API base and the signed-in admin. */
export interface ViewApi {
  base: string;
  me?: AdminMe | null;
}
