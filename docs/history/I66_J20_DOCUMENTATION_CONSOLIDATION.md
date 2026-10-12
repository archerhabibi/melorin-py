# I66: J20 Documentation Consolidation

The documentation set now has an explicit source-of-truth policy:
`docs/RELEASE-EVIDENCE-MATRIX.md` is the only current release-status record.
The index identifies the requirements, architecture, API, operations, change
log, and release matrix documents; phase and finding reports remain historical
implementation evidence and are not release approvals.

The API map now includes the reports, referral, and bot/store binding surfaces.
The migration smoke gate was corrected to verify the current head
`0008_bot_store_bindings` instead of the obsolete `0005` revision. The release
matrix checker rejects stale `0005` references in the authoritative matrix and
requires the J01-J19 remediation table.
