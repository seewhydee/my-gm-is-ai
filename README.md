# My GM is AI

An experimental AI-driven Game Master (GM) for single-player RPGs.
Experience tabletop RPGs without friends!

Unlike freeform AI roleplay chatbots, this AI GM system does not
create open-ended adventures, nor is it optimized for naturalistic
interlocutors with emotional depth.  Instead, it aims to run a
pre-generated adventure module faithfully.  You, the player, can
attempt anything, and the GM decides if it's possible, what rules
apply, and how to describe what happens.  Like a human GM, the system
tries to strike a balance between creativity and rules adherence.

This is a work in progress.  There is a short sample adventure, in the
form of a handwritten 5-room scenario that can be played through.  A
subset of 5e SRD rules has been implemented, including core player
stats, standard equipment, and basic combat rules.

## Installation and setup

Requires Python 3 with some packages (pydantic, rich, openai, jinja2,
platformdirs).  You can install them all via `pip`:

```bash
pip install -e .
```

### Model configuration

The AI GM requires API access to an large language model (LLM) via an
OpenAI-compatible API.  There are three ways to set your credentials:

1. Using environmental variables, e.g.:
```bash
export MGMAI_MODEL="deepseek-v4-flash"
export MGMAI_BASE_URL="https://api.deepseek.com"
export MGMAI_API_KEY="<your_api_key>"
```
2. Alternatively, on first launch you will be prompted for the above
   information, which is saved to `~/.config/mgmai/` for future sessions.
3. You can also specify model details directly in your config files
   (see below).

To switch between models, use the `--model <model_id>` option:

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

Provider IDs (keys for `api_keys`) are derived from the base URL
hostname by default.  You can also specify custom model parameters in
`~/.config/mgmai/models.json`.  See the [Models doc](doc/models.md)
for details.

## Usage

If you installed with `pip install -e .`, run it like this:

```bash
mgmai adventures/bag-of-holding
```

To run directly from the source directory without installing:

```bash
python -m mgmai.cli adventures/bag-of-holding
```

To resume a saved game:

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

### Telegram bot

You can also play through a Telegram bot instead of the terminal:

```bash
pip install -e ".[telegram]"
mgmai-telegram
```

This requires a bot token from BotFather and some configuration (a
mandatory chat-ID allow-list and an adventures directory).  See
[doc/telegram.md](doc/telegram.md) for setup and play instructions.
The Telegram front-end is a work in progress; see `telegram-plan.md`.

## How It Works

Each turn, the player's natural language input flows through a
three-stage pipeline:

1. **Ruling** — An LLM call interprets your intent and produces a structured action.
2. **Engine resolution** — A gameplay engine validates the action against the adventure module's rules and the current game state, rolls virtual dice, etc.
3. **Prose narration** — A second LLM call weaves the outcome into natural prose, respecting narrative requirements like keeping secrets hidden.

Adventure rules are generated ahead of time (usually using LLMs), just
as a human GM prepares modules before each play session.  In time, it
is hoped that the system becomes strong enough to run converted
tabletop modules.

## Scenario Generation

To construct a playable adventure, write it up in natural language,
and save it in `adventures/SCENARIO-ID/scenario.md`.  See
`adventures/bag-of-holding/scenario.md` for an example.  Next, fire up
an LLM of your choice and instruct it to follow the steps in
`schema/scenario-generation.md`, to convert your scenario into JSON.
Finally, playtest extensively, and ask the LLM to fix the scenario's
JSON files until it works satisfactorily (or not).

In future, it will be interesting to try constructing playable
scenarios from other sources, such as scanned PDFs, using multimodal
LLMs.  Success/failure reports are welcome.

## Testing

The regular test suite uses fake LLM clients, with no network access needed:

```bash
pytest                  # run the full unit suite (fast, no API calls)
pytest tests/test_combat.py -k "flee"   # run a specific subset
```

There is also a separate suite of LLM-driven integration tests, which
run a LLM as the player against the real GM LLM, along with an LLM
judge.  See [tests/integration/README.md](tests/integration/README.md)
for details.

## Documentation

The design documentation is in the `doc/` folder:

- [doc/intro.md](doc/intro.md): Architecture guide.
- [doc/npcs.md](doc/npcs.md): Implementation of non-player characters.
- [doc/player-stats.md](doc/player-stats.md) — Player stats (WIP).
- [doc/soft.md](doc/soft.md) — The soft state system (soft notes, soft items).
- [doc/models.md](doc/models.md) — LLM model configuration guide.
- [doc/telegram.md](doc/telegram.md) — Playing via the Telegram bot.

## Copyright and License

My GM Is AI is (C) 2026 Chong Yidong (cyd@stupidchicken.com).

This is free software licensed under the terms of the GNU General
Public License (GPL), version 3.0.  See [LICENSE](LICENSE).

Dedicated to the memory of Logan Goh (1980-2026): programmer, gamer, dreamer.

The sample adventure(s) in the `adventures/` folder are based on
original works copyrighted by various authors, used and distributed
under GPL-compatible (e.g., Creative Commons-type) licenses.  Refer to
those files for copyright and licensing information.

Some of the RPG rules implemented therein follow material from
the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the
Coast LLC, available at https://www.dndbeyond.com/srd.  The SRD 5.2.1
is licensed under the [Creative Commons Attribution 4 License](https://creativecommons.org/licenses/by/4.0/legalcode).
