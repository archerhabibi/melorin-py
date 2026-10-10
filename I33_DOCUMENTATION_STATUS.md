# I33: documentation status policy

The release evidence matrix is the single source of current release status.
Phase and finding completion reports remain useful historical records, but
cannot imply runtime or production approval.

The policy is enforced by the release-matrix checker and documented in both
the matrix and the project README. New implementation work must land in source
and tests first, then update the canonical evidence record.
