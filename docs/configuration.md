# Configuration

## API Keys

### Anthropic

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_BASE_URL=https://your-gateway.example.com  # optional
```

### OpenAI-compatible

```bash
export AUTOXRD_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://your-openai-gateway.example.com
```

OpenAI-compatible mode is the default provider. Configure the endpoint and
model explicitly unless you intentionally use the built-in development
defaults.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AUTOXRD_MODEL` | Model name (e.g. `claude-sonnet-4-5`) |
| `AUTOXRD_MAX_TOKENS` | Max output tokens |
| `AUTOXRD_EFFORT` | Reasoning effort (`low`, `medium`, `high`) |
| `AUTOXRD_PROVIDER` | `anthropic` or `openai` |
| `AUTOXRD_BUDDY_MODEL` | Model for companion pet reactions |
| `AUTOXRD_ADVISOR_MODEL` | Optional model used for advisor calls |
| `AUTOXRD_ADVISOR_MAX_USES` | Maximum advisor calls per task |

## CLI Flags

```bash
autoxrd \
  --provider anthropic \
  --base-url https://your-gateway.example.com \
  --api-key sk-ant-... \
  --model claude-sonnet-4 \
  --max-tokens 64000 \
  --auto-approve \
  --coordinator \
  --resume 1
```

## TOML Config Files

Loaded in order (later files override earlier files; CLI and environment values
override both):

1. `~/.config/autoxrd/config.toml`
2. `.autoxrd.toml` in the current working directory

Point to a specific file with `--config`.

### Anthropic example

```toml
provider = "anthropic"

[anthropic]
base_url = "https://your-gateway.example.com"
model = "claude-sonnet-4"
```

### OpenAI example

```toml
provider = "openai"

[openai]
base_url = "https://your-openai-gateway.example.com/v1"
model = "gpt-4.1-mini"
max_tokens = 8192
effort = "medium"
buddy_model = "gpt-4.1-mini"
```

### OpenRouter (low-cost testing)

```toml
provider = "openai"

[openai]
base_url = "https://openrouter.ai/api/v1"
model = "qwen/qwen3.6-plus-preview:free"
```

When `provider = "openai"`, `OPENAI_API_KEY` / `OPENAI_BASE_URL` are used. When `provider = "anthropic"`, `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` are used.
Keep API keys in environment variables or an ignored `.env` file rather than
committing them to TOML.
