// Shared structural types for admin-web (TypeScript migration, T-O03 / T-R11).
// Server payloads that are not yet bound to a generated @melorin/api-client schema use these aliases, so every
// remaining loose spot is greppable (`Json`) and can be tightened one view at a time.

export type { Rec, Json, CallFn, WithChildren, Toast, Id } from '@melorin/web-kit/types';
