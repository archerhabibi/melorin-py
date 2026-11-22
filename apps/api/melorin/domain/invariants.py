"""The exception for a broken runtime invariant (pure: no imports of ours, so every layer may use it)."""


class InvariantViolation(RuntimeError):
    """A condition the code guarantees was false: a bug, never a user error (maps to a 500 and is logged)."""
