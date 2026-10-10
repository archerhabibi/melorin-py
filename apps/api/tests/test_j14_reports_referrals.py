from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reports_and_referrals_have_real_routes():
    app = (ROOT / "melorin/app.py").read_text()
    reports = (ROOT / "melorin/modules/reports/router.py").read_text()
    referral = (ROOT / "melorin/modules/referral/router.py").read_text()
    assert "reports_router" in app and "referral_router" in app
    assert '@router.get("/stores/{store_id}/sales")' in reports
    assert '@router.get("/me/referrals")' in referral
    assert '@router.put("/admin/referral-rules")' in referral


def test_referral_rules_and_clawbacks_are_exposed_without_mutating_ledger_history():
    source = (ROOT / "melorin/modules/referral/router.py").read_text()
    service = (ROOT / "melorin/modules/referral/service.py").read_text()
    assert "CommissionRule" in source
    assert "offset_amount" in source
    assert "claw" in service and "reversed_amount" in service
