"""Tests for CostTracker."""

import pytest
from features.cost_tracker import (
    CostTracker, _tier_for_model, _fmt_tokens, _fmt_duration,
    REQUIRED_MODEL_FIELDS, ModelInfo, MODEL_REGISTRY,
    validate_model_info, get_model_info,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def test_fmt_tokens_small():
    assert _fmt_tokens(500) == "500"
    assert _fmt_tokens(0) == "0"


def test_fmt_tokens_k():
    assert _fmt_tokens(1000) == "1k"
    assert _fmt_tokens(2400) == "2.4k"
    assert _fmt_tokens(10_500) == "10.5k"


def test_fmt_tokens_m():
    assert _fmt_tokens(1_000_000) == "1m"
    assert _fmt_tokens(1_500_000) == "1.5m"


def test_fmt_duration():
    assert _fmt_duration(0) == "0s"
    assert _fmt_duration(45) == "45s"
    assert _fmt_duration(90) == "1m 30s"
    assert _fmt_duration(3661) == "1h 1m 1s"


# ---------------------------------------------------------------------------
# Pricing tier resolution
# ---------------------------------------------------------------------------

def test_tier_sonnet():
    tier = _tier_for_model("claude-sonnet-4-20250514")
    assert tier.input == 3.0
    assert tier.output == 15.0


def test_tier_opus_4():
    tier = _tier_for_model("claude-opus-4-20250514")
    assert tier.input == 15.0
    assert tier.output == 75.0


def test_tier_opus_4_5():
    tier = _tier_for_model("claude-opus-4-5-20250514")
    assert tier.input == 5.0
    assert tier.output == 25.0


def test_tier_opus_4_6():
    tier = _tier_for_model("claude-opus-4-6")
    assert tier.input == 5.0
    assert tier.output == 25.0
    
    tier_fast = _tier_for_model("claude-opus-4-6", {"speed": "fast"})
    assert tier_fast.input == 30.0
    assert tier_fast.output == 150.0


def test_tier_haiku_35():
    tier = _tier_for_model("claude-3-5-haiku-20241022")
    assert tier.input == 0.80
    assert tier.output == 4.0


def test_tier_haiku_45():
    tier = _tier_for_model("claude-haiku-4-5-20251001")
    assert tier.input == 1.0
    assert tier.output == 5.0


def test_tier_unknown_defaults_to_sonnet():
    tier = _tier_for_model("some-unknown-model")
    assert tier.input == 3.0
    assert tier.output == 15.0


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------

def test_calculate_cost_basic():
    cost = CostTracker.calculate_cost("claude-sonnet-4-20250514", {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
    })
    # $3/MTok input + $15/MTok output = $18
    assert abs(cost - 18.0) < 0.001


def test_calculate_cost_with_cache():
    cost = CostTracker.calculate_cost("claude-sonnet-4-20250514", {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_read_input_tokens": 500_000,
        "cache_creation_input_tokens": 200_000,
    })
    # input_tokens already excludes cached tokens (Anthropic API semantics)
    # cost = 1M * 3/M + 500k * 0.30/M + 200k * 3.75/M
    #      = 3.0 + 0.15 + 0.75 = 3.9
    assert abs(cost - 3.9) < 0.001


def test_calculate_cost_small():
    cost = CostTracker.calculate_cost("claude-sonnet-4-20250514", {
        "input_tokens": 1000,
        "output_tokens": 500,
    })
    # 1000 * 3/1M + 500 * 15/1M = 0.003 + 0.0075 = 0.0105
    assert abs(cost - 0.0105) < 0.00001


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------

def test_add_usage_accumulates():
    tracker = CostTracker()
    tracker.add_usage("claude-sonnet-4-20250514", {
        "input_tokens": 100,
        "output_tokens": 50,
    }, api_duration_s=1.5)
    tracker.add_usage("claude-sonnet-4-20250514", {
        "input_tokens": 200,
        "output_tokens": 100,
    }, api_duration_s=2.0)
    assert tracker.total_cost_usd > 0
    mu = tracker._model_usage["claude-sonnet-4-20250514"]
    assert mu.input_tokens == 300
    assert mu.output_tokens == 150
    assert abs(mu.api_duration_s - 3.5) < 0.001


def test_add_usage_multiple_models():
    tracker = CostTracker()
    tracker.add_usage("claude-sonnet-4-20250514", {
        "input_tokens": 1000, "output_tokens": 500,
    })
    tracker.add_usage("claude-opus-4-20250514", {
        "input_tokens": 1000, "output_tokens": 500,
    })
    assert len(tracker._model_usage) == 2
    # Opus costs more per token
    opus_cost = tracker._model_usage["claude-opus-4-20250514"].cost_usd
    sonnet_cost = tracker._model_usage["claude-sonnet-4-20250514"].cost_usd
    assert opus_cost > sonnet_cost


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_format_cost_empty():
    tracker = CostTracker()
    assert "No API usage" in tracker.format_cost()


def test_format_cost_with_data():
    tracker = CostTracker()
    tracker.add_usage("claude-sonnet-4-20250514", {
        "input_tokens": 10000, "output_tokens": 5000,
    }, api_duration_s=3.0)
    output = tracker.format_cost()
    assert "Total cost:" in output
    assert "Total duration (API):" in output
    assert "Total duration (wall):" in output
    assert "Usage by model:" in output
    assert "claude-sonnet-4-20250514" in output
    assert "10k input" in output
    assert "5k output" in output


def test_format_cost_shows_cache():
    tracker = CostTracker()
    tracker.add_usage("claude-sonnet-4-20250514", {
        "input_tokens": 60000,
        "output_tokens": 2000,
        "cache_read_input_tokens": 50000,
        "cache_creation_input_tokens": 5000,
    })
    output = tracker.format_cost()
    assert "cache read" in output
    assert "cache write" in output


# ---------------------------------------------------------------------------
# Model registry & validation
# ---------------------------------------------------------------------------

def test_required_model_fields_contains_essentials():
    assert "id" in REQUIRED_MODEL_FIELDS
    assert "provider" in REQUIRED_MODEL_FIELDS
    assert "pricing_tier" in REQUIRED_MODEL_FIELDS


def test_all_registry_entries_pass_validation():
    for model_id, info in MODEL_REGISTRY.items():
        errors = validate_model_info(info)
        assert errors == [], f"{model_id} has missing fields: {errors}"


def test_validate_model_info_catches_missing_id():
    from features.cost_tracker import _TIER_3_15
    bad = ModelInfo(id="", provider="anthropic", pricing_tier=_TIER_3_15)
    errors = validate_model_info(bad)
    assert "id" in errors


def test_registry_deprecated_models():
    deprecated = {k: v for k, v in MODEL_REGISTRY.items() if v.deprecated}
    assert len(deprecated) > 0
    for model_id, info in deprecated.items():
        assert info.deprecation_message, f"{model_id} is deprecated but has no message"


def test_registry_hugging_face_ids():
    hf_models = {k: v for k, v in MODEL_REGISTRY.items() if v.hugging_face_id}
    assert len(hf_models) > 0
    for model_id, info in hf_models.items():
        assert info.hugging_face_id.startswith("anthropic/")


def test_get_model_info_exact():
    info = get_model_info("claude-opus-4-6")
    assert info is not None
    assert info.id == "claude-opus-4-6"
    assert info.hugging_face_id == "anthropic/claude-opus-4-6"


def test_get_model_info_with_date_suffix():
    info = get_model_info("claude-sonnet-4-6-20250514")
    assert info is not None
    assert info.id == "claude-sonnet-4-6"


def test_get_model_info_unknown():
    info = get_model_info("gpt-5.1-codex")
    assert info is None


def test_get_model_info_deprecated_flag():
    info = get_model_info("claude-3-5-sonnet-20241022")
    assert info is not None
    assert info.deprecated is True
    assert "claude-sonnet-4-6" in info.deprecation_message
