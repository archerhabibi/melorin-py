from melorin.domain import account_linking as r

PROOF = frozenset({r.Evidence.OAUTH_GOOGLE})


def _d(provider="google", facts=None, counts=None, ev=PROOF):
    return r.decide_attach(
        provider=provider, target_person_id="A", identity=facts or r.IdentityFacts(), person_active_providers=counts or {}, evidence=ev
    )


def test_free_identity_attaches_and_many_google_allowed():
    assert _d() is r.Verdict.ATTACH
    assert _d(counts={"google": 3}) is r.Verdict.ATTACH


def test_session_alone_never_proves_an_identity():
    assert _d(ev=frozenset({r.Evidence.SESSION})) is r.Verdict.REFUSE_UNPROVEN


def test_identity_of_another_person_is_a_conflict_never_moved():
    assert _d(facts=r.IdentityFacts(True, True, "B")) is r.Verdict.CONFLICT
    assert _d(facts=r.IdentityFacts(True, True, "A")) is r.Verdict.ALREADY
    assert _d(facts=r.IdentityFacts(True, False, "B")) is r.Verdict.REACTIVATE


def test_one_active_telegram_per_person():
    ev = frozenset({r.Evidence.TELEGRAM_BOT})
    assert _d("telegram", counts={"telegram": 1}, ev=ev) is r.Verdict.REFUSE_TELEGRAM_LIMIT
    assert _d("telegram", ev=ev) is r.Verdict.ATTACH


def test_last_login_method_cannot_be_unlinked():
    assert r.can_unlink(active_methods=1, is_target_last_usable=True, target_provider="google", target_is_active=True)[0] is False
    assert r.can_unlink(active_methods=2, is_target_last_usable=False, target_provider="google", target_is_active=True)[0] is True


def test_telegram_choice_required_when_both_have_one():
    assert r.telegram_conflict_resolution(True, True, None)[0] == "need_choice"
    assert r.telegram_conflict_resolution(True, True, "target") == ("ok", "source")


def test_consolidation_plan_blocks_debt_and_in_flight_and_skips_zero():
    w = lambda i, u, b: r.WalletFacts(i, u, "s", "IRT", b)  # noqa: E731
    p = r.plan_consolidation(
        central_user_id="c", sources=[w("w1", "u1", 100), w("w2", "u2", 0)], central_wallets={("s", "IRT"): "cw"}, pending_by_user={}
    )
    assert p.ok and p.transfers == [("w1", "cw", 100, "IRT")]
    p = r.plan_consolidation(
        central_user_id="c", sources=[w("w1", "u1", -5)], central_wallets={}, pending_by_user={"u2": ["payment_in_flight"]}
    )
    assert {b.code for b in p.blockers} == {"negative_balance", "payment_in_flight"}
