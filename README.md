# My GM is AI

An AI-driven Game Master for tabletop RPG adventures — play through a pre-written adventure module with an AI GM that adjudicates your actions and narrates the outcome.

Unlike freeform AI roleplay chatbots, MGMAI runs a **fixed adventure module** with mechanical fidelity. You can attempt anything, and the GM decides (a) if it's possible, (b) what rules apply, and (c) how to describe what happens. It aims to strike a balance between AI creativity and rules adherence (similar to what a human GM must manage).

## How It Works

Each turn, your natural-language input flows through a two-stage pipeline:

1. **Ruling** — A large language mode (LLM) interprets your intent and produces a structured action (move, examine, interact, talk, transfer, wait).
2. **Engine resolution** — A deterministic engine validates the action against the adventure module's rules, applies state changes, and checks for encounters or game-over conditions.
3. **Prose narration** — A second LLM call weaves the mechanical outcome into natural prose, respecting hidden information and attitude mechanics.

Game state (inventory, flags, room states, entity states, NPC attitudes, dialogue) is tracked rigorously between turns and persisted to disk.

## Installation

Requires Python 3 with some packages (Pydantic, Rich, Openai, Jinja2, Platformdirs).  You can install them all via `pip`:

```bash
pip install -e .
```

## Setup

The LLMs are accessed via an OpenAI-compatible API.  You can set your credentials using environmental variables, e.g.:

```bash
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_API_KEY="your-api-key"
```

Alternatively, on first launch you will be prompted for this information, which will be saved to your config files.

## Usage

Start a new game from an adventure directory:

```bash
mgmai adventures/bag-of-holding
```

Resume a saved game:

```bash
mgmai adventures/bag-of-holding --load save.json
```

During play, type natural-language commands. Examples:

```
> look around
> examine the wooden chest
> take the rusty key
> open the door with the rusty key
> talk to the innkeeper
> attack the spider
> check my inventory
```

Use `/help` during play for available commands.

## Debug Mode

Run with `--debug` to display the internal Game Master briefing and engine result for each turn:

```bash
mgmai --debug adventures/bag-of-holding
```

## Configuration

Credentials and preferences are stored in `~/.config/mgmai/`.

| Variable | Default | Description |
|----------|---------|-------------|
| `MGMAI_API_KEY` | — | API key (required) |
| `MGMAI_BASE_URL` | `https://api.deepseek.com` | API base URL |
| `MGMAI_MODEL` | `deepseek-v4-flash` | Model name |
| `MGMAI_RULING_TEMPERATURE` | `0.9` | Temperature for action ruling |
| `MGMAI_PROSE_TEMPERATURE` | `1.1` | Temperature for prose narration |

## License

GPL-3.0 — see [LICENSE](LICENSE).
