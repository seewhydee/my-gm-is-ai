# My GM is AI

An experimental AI-driven Game Master (GM) for single-player RPGs.  The goal: replicate the tabletop RPG experience without friends.

Unlike freeform AI roleplay chatbots, this AI GM system is not optimized for crafting naturalistic interlocutors with emotional depth, nor does it create open-ended adventures.  Instead, the AI GM runs a pre-generated adventure module faithfully.  You, the player, can attempt anything, and the GM decides (a) if it's possible, (b) what rules apply, and (c) how to describe what happens.  Like a human GM, the AI GM aims to strike a balance between creativity and rules adherence.

This is a work in progress.  Right now, there is a short sample adventure (a handwritten 5-room scenario) that can be played through.  Major subsystems, like combat and inventory management, are unimplemented or barely implemented.

## Installation and setup

Requires Python 3 with some standard packages (pydantic, rich, openai, jinja2, platformdirs).  You can install them all via `pip`:

```bash
pip install -e .
```

### Model configuration

The AI GM requires API access to an LLM via an OpenAI-compatible API.
There are three ways to set your credentials:

1. Using environmental variables, e.g.:
```bash
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_API_KEY="<your_api_key>"
```
2. Alternatively, on first launch you will be prompted for the above
   information, which will also be saved to `~/.config/mgmai/` for
   future sessions.
3. You can also specify model details directly in your config files
   (see below).

The system supports switching between different models with the
`--model <model_id>` command-line option:

```bash
mgmai adventures/bag-of-holding --model kimi-k2.6
```

It's best to use a cheap fast model, operating in non-reasoning mode
for responsiveness.  The following models come pre-configured:

- `deepseek-v4-flash`
- `kimi-k2.6`
- `mimo-v2.5`
- `mistral-small-2603`

API keys are stored in `~/.config/mgmai/credentials.json`:

```json
{
  "api_keys": {
    "deepseek": "sk-deepseek-key",
    "moonshot": "sk-moonshot-key",
    "mistral": "sk-mistral-key"
  }
}
```

The provider IDs (keys for `api_keys`) are derived from the base URL
hostname by default.  You can also specify custom model parameters in
`~/.config/mgmai/models.json`.  See the [Models doc](doc/models.md)
for details.

## Usage

If you installed the package with `pip install -e .`, you can use the `mgmai` command:

```bash
mgmai adventures/bag-of-holding
```

To run directly from the source directory without installing, use:

```bash
python -m mgmai.cli adventures/bag-of-holding
```

Resume a saved game:

```bash
mgmai adventures/bag-of-holding --load save.json
# or: python -m mgmai.cli adventures/bag-of-holding --load save.json
```

During play, type commands in natural language, e.g.:

```
> look around
> I poke my head through the window. What do I see?
> open the door with the rusty key
> I nod at the innkeeper. "I need accommodation for a day or so. I prefer a quiet chamber and a bed free of vermin."
```

Use `/help` during play for a list of special commands.

## How It Works

Each turn, the player's natural language input flows through a three-stage pipeline:

1. **Ruling** — A large language mode (LLM) call interprets your intent and produces a structured action.
2. **Engine resolution** — A deterministic engine validates the action against the adventure module's rules and the current game state, rolls virtual dice, etc.
3. **Prose narration** — A second LLM call weaves the outcome into natural prose, respecting narrative requirements like keeping secrets hidden.

The adventures are generated from handwritten RPG scenarios, converted into game logic with the help of LLM assistants.  This setup is done ahead of time, just as a human GM prepares adventure modules before each play session.  In time, it is hoped that the conversion process becomes powerful enough to accommodate complex adventure modules written for tabletop play.

## Scenario Generation

To construct a playable scenario, write up a "scenario file" in natural language, describing the adventure as systematically as possible, and save it in `adventures/SCENARIO-ID/scenario.md`. See `adventures/bag-of-holding/scenario.md` for an example.

Then fire up an LLM of your choice and instruct it to follow the steps in `schema/scenario-generation.md`.  This will convert your scenario file into JSON.

Finally, playtest extensively, and ask the LLM to fix the scenario's JSON files until it works satisfactorily (or not).

## Testing

The regular test suite is deterministic and uses fake LLM clients — it runs in a few seconds with no network access:

```bash
pytest                  # run the full unit suite (fast, no API calls)
pytest tests/test_combat.py -k "flee"   # run a specific subset
```

### LLM integration tests

A separate suite of **LLM-driven integration tests** lives in `tests/integration/`.  These run a "driver" LLM as the player against the real GM LLM, verifying the full two-call pipeline (ruling → engine → prose) plus narration quality via an LLM judge.

See [tests/integration/README.md](tests/integration/README.md) for details on the test architecture, scenarios, configuration, and how to modify or extend them.

### Headless harness

The integration tests are built on `mgmai.game.headless.HeadlessSession`, a programmatic entry point that composes `StateManager` + `GameLoop` + a recording display.  It bypasses the interactive REPL and captures every turn's narration, status, and combat log — useful for automation and scripting beyond testing.

## Documentation

The design documentation is in the `doc/` folder:

- [doc/intro.md](doc/intro.md): Architecture guide.
- [doc/npcs.md](doc/npcs.md): Implementation of non-player characters.
- [doc/player-stats.md](doc/player-stats.md) — Player stats (WIP).
- [doc/soft.md](doc/soft.md) — The soft state system (soft notes, soft items).
- [doc/models.md](doc/models.md) — LLM model configuration guide.

## Copyright and License

My GM Is AI is (C) 2026 Chong Yidong (cyd@stupidchicken.com).

It is free software licensed under the terms of the GNU General Public
Licencse (GPL), version 3.0.  See [LICENSE](LICENSE).

Dedicated to the memory of Logan Goh (1980-2026): programmer, gamer, dreamer.

The sample adventure(s) in the `adventure/` folder are based on original works copyrighted by various authors, used and distributed under GPL-compatible (e.g., Creative Commons-type) licenses.  Refer to those files for copyright and licensing information.
