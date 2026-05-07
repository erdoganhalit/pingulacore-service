from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.usage import RequestUsage, RunUsage

from app.utils.usage import extract_token_usage
from app.utils.usage import estimate_cost_usd


def test_estimate_cost_supports_provider_prefixed_gemini_model() -> None:
    cost, status = estimate_cost_usd(
        "google-gla:gemini-2.5-flash",
        input_tokens=100_000,
        output_tokens=10_000,
    )
    assert status == "estimated"
    assert cost > 0


def test_estimate_cost_supports_provider_prefixed_anthropic_alias() -> None:
    cost, status = estimate_cost_usd(
        "anthropic:claude-sonnet-4-6",
        input_tokens=100_000,
        output_tokens=10_000,
    )
    assert status == "estimated"
    assert cost > 0


def test_estimate_cost_supports_provider_prefixed_image_alias() -> None:
    cost, status = estimate_cost_usd(
        "google-gla:gemini-2.5-flash-image",
        input_tokens=100_000,
        output_tokens=10_000,
    )
    assert status == "estimated"
    assert cost > 0


def test_estimate_cost_unknown_model_still_unknown() -> None:
    cost, status = estimate_cost_usd(
        "google-gla:unknown-model-x",
        input_tokens=100_000,
        output_tokens=10_000,
    )
    assert status == "unknown_pricing"
    assert cost == 0.0


@dataclass
class _FakeResponseWithUsageMethod:
    def usage(self) -> RunUsage:
        return RunUsage(
            input_tokens=123,
            output_tokens=45,
            cache_read_tokens=7,
            cache_write_tokens=3,
        )


@dataclass
class _InnerResponse:
    usage: RequestUsage


@dataclass
class _FakeResponseWithInnerUsage:
    response: _InnerResponse


def test_extract_token_usage_reads_pydantic_ai_usage_method() -> None:
    usage = extract_token_usage(_FakeResponseWithUsageMethod())
    assert usage["input_tokens"] == 123
    assert usage["output_tokens"] == 45
    assert usage["total_tokens"] == 168
    assert usage["cache_read_tokens"] == 7
    assert usage["cache_write_tokens"] == 3


def test_extract_token_usage_reads_inner_response_usage() -> None:
    fake = _FakeResponseWithInnerUsage(response=_InnerResponse(usage=RequestUsage(input_tokens=10, output_tokens=4)))
    usage = extract_token_usage(fake)
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 4
    assert usage["total_tokens"] == 14
