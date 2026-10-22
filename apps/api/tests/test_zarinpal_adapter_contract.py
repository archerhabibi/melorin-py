"""M7.2: Zarinpal v4 contract tests against an in-memory fake gateway (httpx.MockTransport).

Request/response shapes follow https://docs.zarinpal.com (v4 ``request.json`` / ``verify.json`` / ``refund.json``).
Melorin stores IRT; Zarinpal is rial-denominated, so the x10 conversion at the adapter edge is part of the contract."""

import json
import types

import httpx
import pytest

from melorin.core.errors import AppError
from melorin.modules.payments.adapters import destination, manual_card, registry, zarinpal
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

REAL_CLIENT = httpx.AsyncClient
SETTINGS = {"gateway.zarinpal": {"merchant_id": "11111111-2222-3333-4444-555555555555"}}
SANDBOX = {"gateway.zarinpal": {"merchant_id": "11111111-2222-3333-4444-555555555555", "sandbox": True}}


def payment(**kw):
    base = dict(id="pay-1", amount=50_000, currency="IRT", external_ref="A000000000000000000000000000abc", status="pending")
    base.update(kw)
    return types.SimpleNamespace(**base)


class FakeZarinpal:
    """Scripted gateway: ``responses[endpoint]`` is ``(http_status, json_body)`` or an Exception to raise."""

    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[tuple[str, str, dict, httpx.Headers]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[1]
        body = json.loads(request.content) if request.content else {}
        self.calls.append((endpoint, str(request.url.host), body, request.headers))
        outcome = self.responses[endpoint]
        if isinstance(outcome, Exception):
            raise outcome
        status, payload = outcome
        return httpx.Response(status, json=payload)


@pytest.fixture
def gateway(monkeypatch):
    def install(**responses) -> FakeZarinpal:
        fake = FakeZarinpal(**responses)
        monkeypatch.setattr(zarinpal.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(fake), **kw))
        return fake

    return install


adapter = zarinpal.ZarinpalAdapter()


# ------------------------------------------------------------------ create


async def test_create_intent_converts_toman_to_rial_and_returns_redirect(gateway):
    fake = gateway(**{"request.json": (200, {"data": {"code": 100, "authority": "A0001", "fee": 0}, "errors": []})})
    res = await adapter.create_payment_intent(payment(), callback_url="https://shop.test/cb?pid=1", settings=SETTINGS)
    endpoint, host, body, _ = fake.calls[0]
    assert (endpoint, host) == ("request.json", "payment.zarinpal.com")
    assert body["amount"] == 500_000 and body["currency"] == "IRR"  # 50,000 IRT -> 500,000 IRR
    assert body["merchant_id"] == SETTINGS["gateway.zarinpal"]["merchant_id"]
    assert body["callback_url"] == "https://shop.test/cb?pid=1"
    assert body["metadata"]["melorin_currency"] == "IRT"
    assert res.external_ref == "A0001"
    assert res.instructions == {"type": "redirect", "redirect_url": "https://payment.zarinpal.com/pg/StartPay/A0001"}


async def test_create_intent_keeps_rial_amounts_unconverted(gateway):
    fake = gateway(**{"request.json": (200, {"data": {"code": 100, "authority": "A2"}})})
    await adapter.create_payment_intent(payment(currency="IRR", amount=500_000), callback_url="u", settings=SETTINGS)
    assert fake.calls[0][2]["amount"] == 500_000


async def test_sandbox_mode_uses_the_sandbox_host_for_the_request_and_the_redirect(gateway):
    fake = gateway(**{"request.json": (200, {"data": {"code": 100, "authority": "S1"}})})
    res = await adapter.create_payment_intent(payment(), callback_url="u", settings=SANDBOX)
    assert fake.calls[0][1] == "sandbox.zarinpal.com"
    assert res.instructions["redirect_url"] == "https://sandbox.zarinpal.com/pg/StartPay/S1"


@pytest.mark.parametrize("data", [{"code": -9}, {"code": 101}, {}, None])
async def test_create_intent_rejects_every_non_100_code_as_a_bad_gateway(gateway, data):
    gateway(**{"request.json": (200, {"data": data, "errors": {"code": -9}})})
    with pytest.raises(AppError) as exc:
        await adapter.create_payment_intent(payment(), callback_url="u", settings=SETTINGS)
    assert exc.value.code == "GATEWAY_ERROR" and exc.value.status == 502


async def test_create_intent_requires_a_merchant_id_before_any_http_call(gateway):
    fake = gateway(**{"request.json": (200, {"data": {"code": 100, "authority": "x"}})})
    with pytest.raises(AppError) as exc:
        await adapter.create_payment_intent(payment(), callback_url="u", settings={})
    assert exc.value.code == "GATEWAY_NOT_CONFIGURED" and exc.value.status == 503
    assert fake.calls == []


async def test_create_intent_refuses_unsupported_currencies(gateway):
    fake = gateway()
    with pytest.raises(PanelError) as exc:
        await adapter.create_payment_intent(payment(currency="USD"), callback_url="u", settings=SETTINGS)
    assert exc.value.kind == ErrorKind.PERMANENT and fake.calls == []


# ------------------------------------------------------------------ verify


def cb(status="OK", authority="A0001"):
    return {"Authority": authority, "Status": status}


async def test_verify_success_sends_the_rial_amount_and_the_stored_authority(gateway):
    fake = gateway(**{"verify.json": (200, {"data": {"code": 100, "ref_id": 99, "card_pan": "6037****1234"}})})
    res = await adapter.verify_callback(cb(authority="A9"), payment(external_ref="A9"), settings=SETTINGS)
    assert res.succeeded and res.external_ref == "A9" and res.payment_id == "pay-1"
    assert fake.calls[0][2] == {"merchant_id": SETTINGS["gateway.zarinpal"]["merchant_id"], "amount": 500_000, "authority": "A9"}
    assert res.raw["verify"]["ref_id"] == 99


async def test_verify_code_101_means_already_verified_and_still_counts_as_success(gateway):
    gateway(**{"verify.json": (200, {"data": {"code": 101, "ref_id": 99}})})
    res = await adapter.verify_callback(cb(), payment(external_ref="A0001"), settings=SETTINGS)
    assert res.succeeded


@pytest.mark.parametrize("code", [-50, -51, -52, -54, 0])
async def test_verify_failure_codes_do_not_succeed(gateway, code):
    gateway(**{"verify.json": (200, {"data": {"code": code}, "errors": {"code": code}})})
    res = await adapter.verify_callback(cb(), payment(external_ref="A0001"), settings=SETTINGS)
    assert not res.succeeded


async def test_verify_without_data_block_does_not_succeed(gateway):
    gateway(**{"verify.json": (200, {"data": [], "errors": {"code": -9}})})
    assert not (await adapter.verify_callback(cb(), payment(external_ref="A0001"), settings=SETTINGS)).succeeded


async def test_user_cancelled_callback_is_failed_without_calling_the_gateway(gateway):
    fake = gateway()
    res = await adapter.verify_callback(cb(status="NOK"), payment(external_ref="A0001"), settings=SETTINGS)
    assert not res.succeeded and fake.calls == []


async def test_tampered_authority_is_rejected_without_calling_the_gateway(gateway):
    fake = gateway()
    res = await adapter.verify_callback(cb(authority="FORGED"), payment(external_ref="A0001"), settings=SETTINGS)
    assert not res.succeeded and fake.calls == []


async def test_missing_status_or_authority_never_verifies(gateway):
    fake = gateway()
    assert not (await adapter.verify_callback({}, payment(), settings=SETTINGS)).succeeded
    assert not (await adapter.verify_callback({"Status": "OK"}, payment(external_ref=None), settings=SETTINGS)).succeeded
    assert fake.calls == []


async def test_verify_with_unsupported_currency_fails_closed(gateway):
    fake = gateway()
    res = await adapter.verify_callback(cb(), payment(currency="USDT"), settings=SETTINGS)
    assert not res.succeeded and res.raw == {"error": "unsupported_currency"} and fake.calls == []


async def test_gateway_network_error_during_verify_propagates_so_the_payment_stays_pending(gateway):
    gateway(**{"verify.json": httpx.ConnectTimeout("timeout")})
    with pytest.raises(httpx.ConnectTimeout):
        await adapter.verify_callback(cb(), payment(external_ref="A0001"), settings=SETTINGS)


# ------------------------------------------------------------------ refund

REFUND_SETTINGS = {"gateway.zarinpal": {"merchant_id": "m", "access_token": "tok-123"}}


async def test_refund_success_uses_bearer_token_and_returns_the_reference(gateway):
    fake = gateway(**{"refund.json": (200, {"data": {"code": 100, "ref_id": 777}})})
    res = await adapter.refund(payment(), settings=REFUND_SETTINGS)
    assert res.status == "succeeded" and res.external_ref == "777"
    endpoint, _, body, headers = fake.calls[0]
    assert endpoint == "refund.json" and headers["authorization"] == "Bearer tok-123"
    assert body == {"merchant_id": "m", "authority": "A000000000000000000000000000abc"}


async def test_refund_falls_back_to_session_then_authority_for_the_reference(gateway):
    gateway(**{"refund.json": (200, {"data": {"code": 101, "session": "S-5"}})})
    assert (await adapter.refund(payment(), settings=REFUND_SETTINGS)).external_ref == "S-5"
    gateway(**{"refund.json": (200, {"data": {"code": 100}})})
    assert (await adapter.refund(payment(), settings=REFUND_SETTINGS)).external_ref == payment().external_ref


@pytest.mark.parametrize(("http", "kind"), [(200, ErrorKind.PERMANENT), (400, ErrorKind.PERMANENT), (502, ErrorKind.TRANSIENT)])
async def test_refund_failures_are_classified_transient_or_permanent(gateway, http, kind):
    gateway(**{"refund.json": (http, {"data": {"code": -40}, "errors": {"code": -40}})})
    with pytest.raises(PanelError) as exc:
        await adapter.refund(payment(), settings=REFUND_SETTINGS)
    assert exc.value.kind == kind


@pytest.mark.parametrize(
    "settings",
    [{"gateway.zarinpal": {"merchant_id": "m"}}, SETTINGS],
)
async def test_refund_requires_an_access_token(gateway, settings):
    fake = gateway()
    with pytest.raises(PanelError) as exc:
        await adapter.refund(payment(), settings=settings)
    assert exc.value.kind == ErrorKind.PERMANENT and fake.calls == []


async def test_refund_requires_the_original_authority_and_a_supported_currency(gateway):
    fake = gateway()
    with pytest.raises(PanelError):
        await adapter.refund(payment(external_ref=None), settings=REFUND_SETTINGS)
    with pytest.raises(PanelError):
        await adapter.refund(payment(currency="EUR"), settings=REFUND_SETTINGS)
    assert fake.calls == []


async def test_status_helpers_are_passthrough():
    assert await adapter.query_payment_status(payment(status="pending"), settings={}) == "pending"
    assert adapter.normalize_status("x") == "x"
    assert adapter.name == "zarinpal" and adapter.requires_review is False


# --------------------------------------- sibling adapters and the registry


async def test_manual_card_adapter_shows_the_store_destination_and_refuses_callbacks_and_refunds():
    a = manual_card.ManualCardAdapter()
    res = await a.create_payment_intent(
        payment(), callback_url="u", settings={"card.info": {"card_number": "6037997777777777", "holder": "Ali", "bank": "Melli"}}
    )
    assert res.instructions["type"] == "manual_card" and res.instructions["card_number"] == "6037997777777777"
    assert res.instructions["amount"] == 50_000 and res.instructions["currency"] == "IRT"
    assert a.requires_review is True
    with pytest.raises(NotImplementedError):
        await a.verify_callback({}, payment(), settings={})
    with pytest.raises(NotImplementedError):
        await a.refund(payment(), settings={})
    assert await a.query_payment_status(payment(status="x"), settings={}) == "x" and a.normalize_status("y") == "y"


async def test_destination_adapter_needs_a_configured_destination_and_never_auto_confirms():
    a = destination.DestinationAdapter("crypto", "crypto_wallet")
    with pytest.raises(AppError) as exc:
        await a.create_payment_intent(payment(), callback_url="u", settings={})
    assert exc.value.code == "PAYMENT_DESTINATION_MISSING"
    res = await a.create_payment_intent(payment(), callback_url="u", settings={"destination.crypto": {"address": "T123"}})
    assert res.instructions["type"] == "crypto_wallet" and res.instructions["destination"] == {"address": "T123"}
    cbres = await a.verify_callback({"x": 1}, payment(), settings={})
    assert cbres.succeeded is False and cbres.raw["error"] == "manual_confirmation_required"
    with pytest.raises(NotImplementedError):
        await a.refund(payment(), settings={})
    assert await a.query_payment_status(payment(status="s"), settings={}) == "s" and a.normalize_status("z") == "z"


def test_registry_knows_every_supported_destination_and_rejects_unknown_gateways(monkeypatch):
    for name in ("manual_card", "zarinpal", "external_gateway", "crypto", "telegram_stars"):
        assert registry.get_adapter(name).name == name
    with pytest.raises(AppError) as exc:
        registry.get_adapter("paypal")
    assert exc.value.code == "GATEWAY_UNKNOWN"
    monkeypatch.setattr(registry, "_ADAPTERS", dict(registry._ADAPTERS))
    plug = types.SimpleNamespace(name="nextpay")
    registry.register(plug)
    assert registry.get_adapter("nextpay") is plug


def test_supported_destinations_returns_a_copy():
    snapshot = registry.supported_destinations()
    snapshot["injected"] = {}
    assert "injected" not in registry.supported_destinations()
