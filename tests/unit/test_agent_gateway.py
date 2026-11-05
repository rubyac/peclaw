import json

import httpx
import pytest
from fixtures.agent_provider import synthetic_result, wire_response
from pydantic import SecretStr, ValidationError

from app.agents import gateway
from app.agents.gateway import ModelError
from app.agents.prompts import prompt
from app.agents.validation import validate_result
from app.core.config import get_settings
from app.schemas.agents import TaskInput


def configured(monkeypatch, handler):
    cfg = get_settings().model_copy(
        update={
            "model_provider": "openai_compatible",
            "model_api_key": SecretStr("unit-test-secret"),
            "model_base_url": "https://provider.example/v1",
        }
    )
    monkeypatch.setattr(gateway, "get_settings", lambda: cfg)
    client = httpx.Client
    monkeypatch.setattr(
        gateway.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return cfg


def context():
    return {"workflow": "company_profile", "candidate_company_ids": [], "evidence": []}


def test_gateway_real_http_contract_and_usage(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer unit-test-secret"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"} and not body.get("tools")
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json=wire_response(context()))

    configured(monkeypatch, handler)
    result = gateway.complete(prompt("company_profile")[2], context())
    assert result.input_tokens == 120 and result.output_tokens == 80
    assert validate_result(result.content, context())["workflow"] == "company_profile"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "MODEL_AUTH_FAILED"),
        (403, "MODEL_AUTH_FAILED"),
        (429, "MODEL_RATE_LIMIT"),
        (500, "MODEL_UNAVAILABLE"),
        (307, "MODEL_REQUEST_REJECTED"),
        (400, "MODEL_REQUEST_REJECTED"),
    ],
)
def test_provider_error_classification_without_body_or_retry(monkeypatch, status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private content and secret must not escape")

    configured(monkeypatch, handler)
    with pytest.raises(ModelError, match=code) as error:
        gateway.complete("system", context())
    assert str(error.value) == code and len(calls) == 1


def test_timeout_is_bounded_and_not_implicitly_retried(monkeypatch):
    configured(
        monkeypatch,
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("sensitive")),
    )
    with pytest.raises(ModelError, match="MODEL_TIMEOUT"):
        gateway.complete("s", context())


@pytest.mark.parametrize("value", ["not json", '{"workflow":"company_profile"}'])
def test_malformed_structured_result_rejected(value):
    with pytest.raises(ModelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_result(value, context())


def test_invented_reference_and_unverified_fact_rejected():
    ctx = {
        **context(),
        "evidence": [{"id": "chunk:test", "verification": "unverified"}],
    }
    value = synthetic_result(ctx)
    value["summary"]["classification"] = "fact"
    with pytest.raises(ModelError, match="OUTPUT_FACT_UNVERIFIED"):
        validate_result(json.dumps(value), ctx)
    value = synthetic_result(ctx)
    value["summary"]["evidence_ids"] = ["other-tenant"]
    with pytest.raises(ModelError, match="OUTPUT_REFERENCE_INVALID"):
        validate_result(json.dumps(value), ctx)


def test_disabled_gateway_makes_no_request(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: get_settings().model_copy(update={"model_provider": "disabled"}),
    )
    monkeypatch.setattr(
        gateway.httpx, "Client", lambda **kwargs: pytest.fail("No HTTP when disabled")
    )
    with pytest.raises(ModelError, match="MODEL_NOT_CONFIGURED"):
        gateway.complete("s", context())


def test_input_requires_explicit_document_consent_and_typed_scope():
    from uuid import uuid4

    value = {
        "kind": "bp_screening",
        "question": "核实授权项目材料",
        "document_ids": [str(uuid4())],
        "idempotency_key": str(uuid4()),
    }
    with pytest.raises(ValidationError):
        TaskInput.model_validate(value)
    with pytest.raises(ValidationError):
        TaskInput.model_validate(
            {**value, "allow_private_to_model": True, "organization_id": str(uuid4())}
        )
    assert (
        TaskInput.model_validate({**value, "allow_private_to_model": True}).kind == "bp_screening"
    )
