"""Account status writes are attributed and checked: lifecycle table AND the writer's own allowed targets."""

from types import SimpleNamespace

import pytest

from melorin.domain.order_state import (
    SOURCE_TARGETS,
    VPN_TRANSITIONS,
    InvalidTransition,
    SourceNotAllowed,
    VpnSource,
    VpnStatus,
    set_vpn_status,
)


def _acc(status):
    return SimpleNamespace(status=status)


def test_every_source_is_declared_and_targets_are_real_statuses():
    assert set(SOURCE_TARGETS) == set(VpnSource)
    for targets in SOURCE_TARGETS.values():
        assert targets and targets <= set(VpnStatus)


def test_allowed_write_returns_an_auditable_transition():
    acc = _acc(VpnStatus.ACTIVE)
    t = set_vpn_status(acc, VpnStatus.SUSPENDED, source=VpnSource.BULK)
    assert acc.status == VpnStatus.SUSPENDED
    assert (t.src, t.dst, t.source, t.changed) == ("active", "suspended", "bulk", True)
    assert t.as_audit() == {"from": "active", "to": "suspended", "source": "bulk"}


def test_repeating_the_same_write_is_idempotent():
    acc = _acc(VpnStatus.SUSPENDED)
    t = set_vpn_status(acc, VpnStatus.SUSPENDED, source=VpnSource.BULK)
    assert acc.status == VpnStatus.SUSPENDED and t.changed is False


@pytest.mark.parametrize(
    ("source", "dst"),
    [(s, d) for s in VpnSource for d in VpnStatus if d not in SOURCE_TARGETS[s]],
)
def test_a_source_cannot_write_a_status_outside_its_list(source, dst):
    acc = _acc(VpnStatus.ACTIVE)
    with pytest.raises(SourceNotAllowed):
        set_vpn_status(acc, dst, source=source)
    assert acc.status == VpnStatus.ACTIVE


def test_lifecycle_table_still_applies_to_an_allowed_source():
    acc = _acc(VpnStatus.REVOKED)
    with pytest.raises(InvalidTransition):
        set_vpn_status(acc, VpnStatus.ACTIVE, source=VpnSource.PROVISIONING)
    assert acc.status == VpnStatus.REVOKED


def test_renewal_path_expired_to_active_is_allowed_for_provisioning_and_sync():
    for source in (VpnSource.PROVISIONING, VpnSource.PANEL_SYNC):
        assert VpnStatus.ACTIVE in VPN_TRANSITIONS[VpnStatus.EXPIRED]
        acc = _acc(VpnStatus.EXPIRED)
        set_vpn_status(acc, VpnStatus.ACTIVE, source=source)
        assert acc.status == VpnStatus.ACTIVE
