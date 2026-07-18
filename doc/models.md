# LLM Model Configuration

My GM is AI uses an LLM for two calls per turn:

1. **Ruling** (Call 1) — low temperature, interprets your input into a structured action
2. **Prose** (Call 2) — moderate temperature, narrates the outcome as immersive prose

The system connects to any [OpenAI-compatible](https://platform.openai.com/docs/api-reference) chat completions endpoint. This document covers all the ways to configure which model to use and how it behaves.

## Quick start

Set three environment variables and go:

```bash
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_API_KEY="your-api-key"
python -m mgmai.cli adventures/bag-of-holding
```

Or pass everything on the CLI:

```bash
python -m mgmai.cli adventures/bag-of-holding \
  --base-url "https://api.deepseek.com" \
  --model "deepseek-v4-flash" \
  --api-key "your-api-key"
```

Or, if you provide none of these and your terminal is interactive, you will be prompted.

While running the game, you can also type `/model` to view the current model details, and optionally swap models.

## Configuration sources (priority order)

Settings are resolved in this order — earlier sources override later ones:

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | CLI flags | `--model`, `--base-url`, `--api-key` |
| 2 | Environment variables | `MGMAI_MODEL`, `MGMAI_BASE_URL`, `MGMAI_API_KEY` |
| 3 | `~/.config/mgmai/config.json` | Saved by interactive prompt or `/model` command |
| 4 | `~/.config/mgmai/credentials.json` | API key only (file permissions set to `0600`) |
| 5 (lowest) | Built-in defaults | `deepseek-v4-flash` if nothing else is set |

## Built-in models

The following models have pre-configured settings and can be used by name without additional setup:

| Model key | API provider | Base URL |
|-----------|-------------|----------|
| `deepseek-v4-flash` | DeepSeek | `https://api.deepseek.com` |
| `kimi-k2.6` | Moonshot | `https://api.moonshot.ai/v1` |
| `mimo-v2.5` | Xiaomi Mimo | `https://api.xiaomimimo.com/v1` |
| `mistral-small-2603` | Mistral | `https://api.mistral.ai/v1` |

Each pre-configured model includes tuned temperature settings, JSON mode support, and any provider-specific parameters (e.g. DeepSeek's thinking-disabled mode).

There is also a `deepseek-reasoner` placeholder for DeepSeek's reasoning
model.  Its exact model name needs to be filled in — see
[Reasoning models](#reasoning-models) below.

## Custom models: `models.json`

To use a model not in the built-in registry (a local llama.cpp server, Ollama, a fine-tune, or any other OpenAI-compatible endpoint), create `~/.config/mgmai/models.json`. This file maps arbitrary model names to their full configuration.

### Example: local llama.cpp with a quantized Qwen model

The GGUF filename is the model ID that llama.cpp serves.  We assign it the nickname `qwen-27b` and set `name` to the actual filename.  Only `base_url` and `name` are strictly required.

```json
{
  "qwen-27b": {
    "name": "Qwen_Qwen3.6-27B-Q4_K_M.gguf",
    "base_url": "http://127.0.0.1:8080/v1",
    "label": "Qwen 3.6 27B (local)",
    "supports_json_mode": false,
    "ruling_max_tokens": 800,
    "prose_max_tokens": 1000,
    "extra_body": {
      "chat_template_kwargs": {
        "enable_thinking": false
      }
    }
  }
}
```

Then run:

```bash
python -m mgmai.cli adventures/bag-of-holding --model qwen-27b --api-key not-needed
```

## ModelConfig fields reference

These are all the fields you can set in `models.json`. Only `base_url` is required for custom models.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | the key (nickname) | Model identifier sent to the API server. Set this when the server expects a different name than your nickname (e.g. a GGUF filename). |
| `base_url` | string | *(required)* | OpenAI-compatible API endpoint URL. Must include the path prefix (e.g. `/v1`). |
| `label` | string | model name | Human-readable label shown in interactive model selection. |
| `ruling_temperature` | float | *(model default)* | Temperature for LLM Call 1 (action interpretation). Lower = more deterministic. Set to `null` to use the API's own default. |
| `prose_temperature` | float | *(model default)* | Temperature for LLM Call 2 (narration). Moderate values (0.6-1.1) work best for creative prose. |
| `supports_json_mode` | bool | `true` (built-in) / `false` (custom) | Whether to send `response_format: {"type": "json_object"}`. Enable for cloud APIs that support it; disable for local servers where it triggers slow grammar-enforced generation. |
| `extra_body` | object | `null` | Additional parameters appended to the API request body. Use for provider-specific options like `{"thinking": {"type": "disabled"}}` (DeepSeek) or `{"chat_template_kwargs": {"enable_thinking": false}}` (Qwen via llama.cpp). |
| `request_timeout` | float | `300.0` | Total request timeout in seconds. The connection timeout is 5 seconds. |
| `ruling_max_tokens` | int | `800` | Maximum output tokens for Call 1. The expected PlayerAction JSON is ~50-150 tokens; a cap prevents verbose models from rambling. |
| `prose_max_tokens` | int | `2000` | Maximum output tokens for Call 2. Narration is typically 100-400 tokens; the generous cap allows for detailed descriptions. |

## Multiple API keys

When models from different providers need separate API keys, expand
`~/.config/mgmai/credentials.json` to include a per-provider map:

```json
{
  "api_key": "sk-fallback-for-any-provider",
  "api_keys": {
    "deepseek": "sk-deepseek-key",
    "moonshot": "sk-moonshot-key",
    "mistral": "sk-mistral-key"
  }
}
```

The provider key is extracted from the model's base URL hostname:
`https://api.deepseek.com` → `"deepseek"`,
`https://api.moonshot.ai/v1` → `"moonshot"`.

Resolution order for each model:

1. CLI `--api-key` (applies to all models)
2. `MGMAI_API_KEY` environment variable (applies to all models)
3. `credentials.api_keys[provider]` (per-provider key)
4. `credentials.api_key` (fallback)

Provider-specific keys are useful for integration tests where the GM,
driver, and judge LLMs are hosted by different providers, or when a
reasoning model from one provider needs a different key than the
fast model from another.

## Reasoning models

Reasoning models (chain-of-thought) work well for tasks that benefit
from extended deliberation, such as the player driver or integration
test judge.  They are less suitable for the GM ruling call, where low
latency matters.

To configure a reasoning model, add an entry to `models.json`:

```json
{
  "my-reasoning-model": {
    "name": "<exact-api-model-name>",
    "label": "My Reasoning Model",
    "base_url": "https://api.provider.com/v1",
    "ruling_temperature": null,
    "prose_temperature": null,
    "extra_body": {"reasoning_effort": "medium"},
    "prose_max_tokens": 4096,
    "supports_json_mode": true
  }
}
```

Key points:

- **Temperature must be `null`** (JSON null, not the string
  `"null"`).  Most reasoning models reject explicit temperature
  settings.
- **`prose_max_tokens`** should be increased to 4096 or higher.  The
  max covers both chain-of-thought and the final answer, so the
  visible output can be much shorter.
- **`extra_body`** passes provider-specific reasoning parameters:

  | Provider | extra_body |
  |----------|------------|
  | DeepSeek | `{"thinking": {"type": "enabled"}}` |
  | OpenAI (o1/o3) | `{"reasoning_effort": "medium"}` (or `"low"` / `"high"`) |
  | Groq | `{}` (enabled by default) |

- **`supports_json_mode`** — set to `false` if the reasoning model
  doesn't support `response_format: {"type": "json_object"}`.

## Environment variables

| Variable | Equivalent CLI flag | Description |
|----------|-------------------|-------------|
| `MGMAI_API_KEY` | `--api-key` | API key or token for authentication |
| `MGMAI_MODEL` | `--model` | Model name (key in `models.json` or built-in name) |
| `MGMAI_BASE_URL` | `--base-url` | API base URL, overrides both built-in and `models.json` defaults |

## CLI flags

| Flag | Description |
|------|-------------|
| `--model MODEL` | Model name |
| `--base-url URL` | API base URL |
| `--api-key KEY` | API key |
| `--config-dir DIR` | Override config directory (default: `~/.config/mgmai/`) |
| `--debug` | Enable debug logging (shows LLM prompts/responses) |

## Files on disk

| File | Purpose | Contains |
|------|---------|----------|
| `~/.config/mgmai/config.json` | Persistent app config | Last-used model name, base URL, adventure path, temperature overrides |
| `~/.config/mgmai/credentials.json` | API credentials (chmod 0600) | Default API key + optional per-provider keys |
| `~/.config/mgmai/models.json` | Custom model registry | Full ModelConfig entries for non-built-in models |

## In-game model switching

Use the `/models` slash command during play to change model, API key, or base URL without restarting:

```
> /models

Model Configuration

  Current model:    deepseek-v4-flash
  Current API key:  sk-...abcd

Known models:
  1. Deepseek v4 Flash (Deepseek API) — https://api.deepseek.com
  2. Kimi K2.6 (Moonshot API) — https://api.moonshot.ai/v1
  3. Mimo 2.5 (Xiaomi API) — https://api.xiaomimimo.com/v1
  4. Mistral Small 4 (Mistral API) — https://api.mistral.ai/v1
  5. Qwen 3.6 27B (local) — http://127.0.0.1:8080/v1
  6. Custom model...

  Select model number (or Enter to keep current):
```

Custom models from `models.json` appear alongside built-in models in this menu.

## Debugging

Run with `--debug` to write LLM prompts and raw responses to the log:

```bash
python -m mgmai.cli adventures/bag-of-holding --model qwen-27b --debug
```

With `--log-file`, the log is also written to a file:

```bash
python -m mgmai.cli adventures/bag-of-holding --model qwen-27b --debug --log-file debug.log
```
