# My GM is AI

An AI-driven Game Master (GM) for single-player RPGs.  The objective: replicate the tabletop RPG experience without needing friends.

Unlike freeform AI roleplay chatbots, this AI GM system is not optimized for crafting naturalistic interlocutors with emotional depth, nor can it create open-ended adventures.  Instead, the AI GM runs a pre-generated adventure module faithfully.  You, the player, can attempt anything, and the GM decides (a) if it's possible, (b) what rules apply, and (c) how to describe what happens.  Like a human GM, the AI GM aims to strike a balance between creativity and rules adherence.

This is a work in progress.  Right now, there is a short sample adventure (a handwritten 5-room scenario) that can be played through.  Player stats and combat are not yet implemented.

## How It Works

Each turn, your natural language input flows through a three-stage pipeline:

1. **Ruling** — A large language mode (LLM) call interprets your intent and produces a structured action.
2. **Engine resolution** — A deterministic engine validates the action against the adventure module's rules and the current game state, rolls virtual dice, etc.
3. **Prose narration** — A second LLM call weaves the outcome into natural prose, respecting narrative requirements like keeping secrets hidden.

The adventures will be generated from handwritten RPG scenarios, which are converted into game logic with the help of LLM assistants.  This setup is done ahead of time, just as a human GM prepares adventure modules before each play session.  In time, it is hoped that the conversion process becomes powerful enough to accommodate complex adventure modules written for tabletop play.

## Installation and setup

Requires Python 3 with some packages (Pydantic, Rich, Openai, Jinja2, Platformdirs).  You can install them all via `pip`:

```bash
pip install -e .
```

The AI GM system requires API access to an LLM via an OpenAI-compatible API.  You can set your credentials using environmental variables, e.g.:

```bash
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_API_KEY="your-api-key"
```

Alternatively, on first launch you will be prompted for this information.  These credentials, as well as save files, are saved to `~/.config/mgmai/`.

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
> I poke my head through the window. What do I see?
> open the door with the rusty key
> I nod at the innkeeper. "I need accommodation for a day or so. I prefer a quiet chamber and a bed free of vermin."
```

Use `/help` during play for available commands.

## Debug Mode

Run with `--debug` to display the internal Game Master briefing and engine result for each turn:

```bash
mgmai --debug adventures/bag-of-holding
```

## License

GPL-3.0 — see [LICENSE](LICENSE).
