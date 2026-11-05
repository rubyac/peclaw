"""Single outbound model boundary. No retries hidden from task/usage accounting."""

import json
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.schemas.agents import AgentResult


class ModelError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def configuration() -> dict:
    settings = get_settings()
    ready = settings.model_provider != "disabled" and bool(
        settings.model_api_key.get_secret_value()
    )
    return {
        "configured": ready,
        "provider": settings.model_provider,
        "model": settings.model_name,
        "max_output_tokens": settings.model_max_output_tokens,
        "daily_token_limit": settings.model_org_daily_token_limit,
        "concurrency": settings.model_org_concurrency,
    }


def embedding(text: str):
    from app.knowledge.embedding import encode

    return encode(text)


@dataclass(frozen=True)
class Completion:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


def messages(system: str, context: dict) -> list[dict]:
    # Data and user instructions are serialized in their own role, never interpolated into system.
    return [
        {
            "role": "system",
            "content": system
            + "\nJSON Schema:\n"
            + json.dumps(AgentResult.model_json_schema(), ensure_ascii=False),
        },
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def complete(system: str, context: dict) -> Completion:
    settings = get_settings()
    if not configuration()["configured"]:
        raise ModelError("MODEL_NOT_CONFIGURED")
    payload = {
        "model": settings.model_name,
        "messages": messages(system, context),
        "temperature": 0,
        "max_tokens": settings.model_max_output_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if len(json.dumps(payload, ensure_ascii=False)) > 60000:
        raise ModelError("CONTEXT_LIMIT")
    started = time.monotonic()
    try:
        with httpx.Client(timeout=settings.model_timeout_seconds, follow_redirects=False) as client:
            with client.stream(
                "POST",
                settings.model_base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + settings.model_api_key.get_secret_value()},
                json=payload,
            ) as response:
                code = response.status_code
                if code in {401, 403}:
                    raise ModelError("MODEL_AUTH_FAILED")
                if code == 429:
                    raise ModelError("MODEL_RATE_LIMIT")
                if code >= 500:
                    raise ModelError("MODEL_UNAVAILABLE")
                if not 200 <= code < 300:
                    raise ModelError("MODEL_REQUEST_REJECTED")
                raw = bytearray()
                for part in response.iter_bytes():
                    if time.monotonic() - started > settings.model_timeout_seconds:
                        raise ModelError("MODEL_TIMEOUT")
                    raw.extend(part)
                    if len(raw) > 1024 * 1024:
                        raise ModelError("MODEL_RESPONSE_TOO_LARGE")
        result = json.loads(raw)
        choice = result["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ModelError("MODEL_INCOMPLETE")
        value = choice["message"]["content"]
        if not isinstance(value, str) or not value or len(value) > 100000:
            raise ModelError("MODEL_INVALID_RESPONSE")
        usage = result.get("usage") or {}

        def token_count(name):
            count = usage.get(name)
            if count is not None and (type(count) is not int or not 0 <= count <= 10000000):
                raise ModelError("MODEL_INVALID_RESPONSE")
            return count

        return Completion(
            value,
            token_count("prompt_tokens"),
            token_count("completion_tokens"),
            int((time.monotonic() - started) * 1000),
        )
    except httpx.TimeoutException:
        raise ModelError("MODEL_TIMEOUT") from None
    except httpx.HTTPError:
        raise ModelError("MODEL_NETWORK_ERROR") from None
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        raise ModelError("MODEL_INVALID_RESPONSE") from None
