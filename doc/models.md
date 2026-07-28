# LLM Model Configuration

My GM is AI uses an LLM for two calls per turn:

1. **Ruling** (Call 1) — interprets your input into a structured action
2. **Prose** (Call 2) — narrates the outcome as immersive prose

The system connects to any OpenAI-compatible chat completions endpoint. This document covers all the ways to configure which model to use and how it behaves.

## Quick start

If no model is registered and your terminal is interactive, you will
be prompted for a model name, base URL, and API key.  This information
is saved for future sessions (see below).

Or set three environment variables:

```bash
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_API_KEY="your-api-key"
python -m mgmai.cli adventures/bag-of-holding
```

Or pass everything on the CLI:

```bash
python -m mgmai.cli adventures/bag-of-holding \
  --model "deepseek-v4-flash" \
  --base-url "https://api.deepseek.com" \
  --api-key "your-api-key"
```

The CLI flags (if supplied) have the highest priority, followed by the
environment variables, followed by the saved configuration.

While running the game, you can also type `/model` to view the current
model details, and optionally swap models.

## Configuration files

- `~/.config/mgmai/config.json`: Persistent app config, including
  last-used model name, base URL, adventure path, temperature
  overrides.
- `~/.config/mgmai/credentials.json`: API keys
- `~/.config/mgmai/models.json`: Custom per-model settings

## Model Configuration

The file `~/.config/mgmai/config.json` stores the following fields:

- `"model_name"`: the default model name to use
- `"base_url"`: the base URL for API access

The following models have pre-configured settings (tuned temperature
settings, JSON mode support, and other provider-specific parameters),
and can be used by name without additional setup:

| Model name          | Base URL                        |
|---------------------|---------------------------------|
| `deepseek-v4-flash` | `https://api.deepseek.com`      |
| `kimi-k2.6`         | `https://api.moonshot.ai/v1`    |
| `mimo-v2.5`         | `https://api.xiaomimimo.com/v1` |
| `mistral-small-2603`| `https://api.mistral.ai/v1`     |

To use models that are not in the built-in registry, create the file
`~/.config/mgmai/models.json`, mapping your custom model names to
objects with the following format:

| Field      | Type   | Description                                    |
|------------|--------|------------------------------------------------|
| `base_url` | string | API endpoint URL including prefix (e.g. `/v1`) |
| `name`     | string | Model identifier, if different from model key  |
| `label`    | string | Human-readable label for interactive selector  |
| `provider` | string | Provider ID for `credentials.json`             |
| `ruling_temperature` | float | Custom LLM Call 1 temperature         |
| `prose_temperature`  | float | Custom LLM Call 2 temperature         |
| `extra_body`| object | Extra parameters appended to API request body |
| `request_timeout`    | float | Total request timeout, default `300` s|
| `ruling_max_tokens`  | int   | Max Call 1 output tokens, default 800 |
| `prose_max_tokens`   | int   | Max Call 1 output tokens, default 2000|
| `supports_json_mode` | bool  | Whether to send `response_format: {"type": "json_object"}`. Enable for cloud APIs that support it; disable for local servers where it triggers slow grammar-enforced generation. |

Only `base_url` is required; the other fields are optional.  If
`provider` is unspecified, it is extracted from the base URL
(`api.deepseek.com` → `"deepseek"`).

### Example: local llama.cpp with a Qwen model

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

## API keys

API keys are retrieved from (going from highest to lowest priority):
1. the `--api-key` command-line option (regardless of model)
2. the `MGMAI_API_KEY` environment variable (regardless of model)
3. the keys stored in `~/.config/mgmai/credentials.json`.

In `credentials.json`, API keys are keyed by provider ID (which is
either extracted from the API base URL, or defined explicitly in
`config.json` as explained above):

```json
{
  "api_keys": {
    "deepseek": "sk-deepseek-key",
    "moonshot": "sk-moonshot-key",
    "mistral": "sk-mistral-key"
  }
}
```

In integration tests where the GM, driver, and judge can be different
LLMs, the provider-specific key for each LLM is looked up here.

## Debugging

Run with `--debug` to write LLM prompts and raw responses to the log:

```bash
python -m mgmai.cli adventures/bag-of-holding --model qwen-27b --debug
```

With `--log-file`, the log is also written to a file:

```bash
python -m mgmai.cli adventures/bag-of-holding --model qwen-27b --debug --log-file debug.log
```

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
