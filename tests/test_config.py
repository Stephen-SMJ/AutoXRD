from argparse import Namespace
from pathlib import Path

import pytest

from core.config import (
    DEFAULT_PROVIDER,
    DEFAULT_MODEL,
    default_max_tokens_for_model,
    load_app_config,
    resolve_model,
)


def _args(**overrides):
    values = {
        "prompt": None,
        "print": False,
        "auto_approve": False,
        "config": None,
        "provider": None,
        "api_key": None,
        "base_url": None,
        "model": None,
        "max_tokens": None,
        "effort": None,
        "buddy_model": None,
        "memory_dir": None,
        "no_auto_dream": False,
        "dream_interval": None,
        "dream_min_sessions": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_resolve_model_keeps_full_model_name():
    assert resolve_model("claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"


def test_default_max_tokens_follow_model_family():
    # Matches official getModelMaxOutputTokens() in context.ts
    assert default_max_tokens_for_model("claude-sonnet-4", provider="anthropic") == 32000
    assert default_max_tokens_for_model("claude-opus-4-6", provider="anthropic") == 64000
    assert default_max_tokens_for_model("claude-opus-4-1-20250805", provider="anthropic") == 32000
    assert default_max_tokens_for_model("claude-3-5-haiku-20241022", provider="anthropic") == 8192


def test_load_app_config_reads_anthropic_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOXRD_MODEL", raising=False)
    monkeypatch.delenv("AUTOXRD_MAX_TOKENS", raising=False)

    config_path = tmp_path / "autoxrd.toml"
    config_path.write_text(
        '[anthropic]\n'
        'api_key = "config-key"\n'
        'base_url = "https://example.test"\n'
        'model = "claude-3.7-sonnet"\n',
        encoding="utf-8",
    )

    config = load_app_config(_args(config=str(config_path), provider="anthropic"))

    assert config.provider == "anthropic"
    assert config.api_key == "config-key"
    assert config.base_url == "https://example.test"
    assert config.model == "claude-3-7-sonnet"
    assert config.max_tokens == 32000  # 3-7-sonnet: 32k per official context.ts


def test_load_app_config_cli_overrides_env_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "autoxrd.toml"
    config_path.write_text(
        'api_key = "file-key"\n'
        'base_url = "https://file.test"\n'
        'model = "claude-3-5-haiku"\n'
        'max_tokens = 2048\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.test")
    monkeypatch.setenv("AUTOXRD_MODEL", "claude-opus-4")
    monkeypatch.setenv("AUTOXRD_MAX_TOKENS", "1234")

    config = load_app_config(
        _args(
            config=str(config_path),
            api_key="cli-key",
            base_url="https://cli.test",
            model="claude-sonnet-4",
            max_tokens=999,
        )
    )

    assert config.api_key == "cli-key"
    assert config.base_url == "https://cli.test"
    assert config.model == "claude-sonnet-4"
    assert config.max_tokens == 999


def test_load_app_config_uses_defaults_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("AUTOXRD_MODEL", raising=False)
    monkeypatch.delenv("AUTOXRD_MAX_TOKENS", raising=False)

    config = load_app_config(_args())

    assert config.provider == DEFAULT_PROVIDER
    assert config.api_key is None
    assert config.base_url == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert config.model == "mimo-v2.5-pro"
    assert config.max_tokens == 8192
    assert config.effort == "high"


def test_load_app_config_rejects_invalid_max_tokens(tmp_path: Path):
    config_path = tmp_path / "autoxrd.toml"
    config_path.write_text('max_tokens = "abc"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid max_tokens"):
        load_app_config(_args(config=str(config_path)))


def test_load_app_config_reads_openai_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTOXRD_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    config_path = tmp_path / "autoxrd.toml"
    config_path.write_text(
        'provider = "openai"\n'
        '[openai]\n'
        'api_key = "openai-key"\n'
        'base_url = "https://openai.test"\n'
        'model = "gpt-4.1-mini"\n'
        'max_tokens = 4096\n'
        'effort = "low"\n'
        'buddy_model = "gpt-4.1-nano"\n',
        encoding="utf-8",
    )

    config = load_app_config(_args(config=str(config_path)))

    assert config.provider == "openai"
    assert config.api_key == "openai-key"
    assert config.base_url == "https://openai.test"
    assert config.model == "gpt-4.1-mini"
    assert config.max_tokens == 4096
    assert config.effort == "low"
    assert config.buddy_model == "gpt-4.1-nano"


def test_openai_env_wins_when_provider_is_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTOXRD_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.env")
    monkeypatch.setenv("AUTOXRD_MODEL", "gpt-4.1")
    monkeypatch.setenv("AUTOXRD_BUDDY_MODEL", "gpt-4.1-mini")

    config = load_app_config(_args())

    assert config.provider == "openai"
    assert config.api_key == "openai-env-key"
    assert config.base_url == "https://openai.env"
    assert config.model == "gpt-4.1"
    assert config.buddy_model == "gpt-4.1-mini"
