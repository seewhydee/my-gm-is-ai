# Playing via Telegram

My GM is AI can be played through a Telegram bot, as an alternative to
the CLI.  You chat with your own bot (created via BotFather), and each
message you send is one turn of the game.

The Telegram front-end is a work in progress (see `telegram-plan.md`).
This document describes the current state; see "Limitations" below for
what is not there yet.

## Setup

### 1. Install the Telegram dependencies

```bash
pip install -e ".[telegram]"
```

This pulls in `python-telegram-bot` (v21) and provides the
`mgmai-telegram` command.  The CLI does not require these dependencies.

### 2. Create a bot and get a token

Talk to [@BotFather](https://t.me/BotFather) in Telegram, use `/newbot`,
and copy the token it gives you.  Provide it either as an environment
variable:

```bash
export MGMAI_TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
```

or in `~/.config/mgmai/credentials.json`:

```json
{
  "api_keys": { ... },
  "telegram": { "bot_token": "123456:ABC-DEF..." }
}
```

The environment variable takes precedence.  The token is never logged.

### 3. Configure the bot

Add two keys to `~/.config/mgmai/config.json`:

```json
{
  "telegram_allowed_chat_ids": [123456789],
  "telegram_adventures_dir": "/path/to/my-gm-is-ai/adventures"
}
```

- `telegram_allowed_chat_ids` (**mandatory**): the allow-list of chat
  IDs the bot will talk to.  A public bot is an open proxy to your LLM
  API budget, so the bot refuses to start without this.  To find your
  chat ID, message a bot such as `@userinfobot`.
- `telegram_adventures_dir` (**mandatory**): where to scan for
  adventures (subdirectories containing `corpus.json`).  From a repo
  checkout, point it at the `adventures/` folder.  No implicit default:
  unset, or containing no adventure, aborts startup with a clear
  message.

### 4. Model configuration

The bot resolves the LLM model the same way as the CLI (environment
variables, then config files — see [models.md](models.md)), once at
startup.  Unlike the CLI, it never prompts interactively: a missing API
key or base URL aborts startup with a clear message.

## Running

If you installed with `pip install -e ".[telegram]"`, run it like this:

```bash
mgmai-telegram
```

To run directly from the source directory without installing (the
interpreter must have python-telegram-bot available, e.g. the project
`.venv`):

```bash
python -m mgmai.telegram
# or: .venv/bin/python -m mgmai.telegram
```

The bot uses long polling; just leave it running.  Stop it with
Ctrl-C.

## Playing

- Send `/start` for the main menu: **New game**, **Continue** (shown
  when you have a saved session), **Help**.  The same menu appears if
  you send a game message while no session is live.
- **New game** (or `/new`) shows an adventure picker listing every
  adventure found in `telegram_adventures_dir`.  Picking one starts the
  game and delivers the intro (title, introduction, starting room)
  right away.  If a game is already live, you are asked to confirm
  first.
- **Continue** resumes your latest save (the per-turn autosave).  This
  also works after the bot process was stopped and restarted: the bot
  remembers your adventure and last save.
- Type in natural language, exactly as in the CLI (`look around`, `n`,
  `x spider`, `attack the goblin`, …).  Classic shortcuts work
  unchanged.  Each message is one turn.
- While a turn is being processed (typically 5–30 seconds: two LLM
  calls), the bot shows a "typing…" indicator.  Messages you send
  during a turn are queued and processed in order.
- Session commands: `/new`, `/load` (a save browser with one button
  per save — filename, timestamp, and a narration snippet — autosave
  included), `/save [name]`, `/restart` (with confirmation), `/quit`
  (ends the session; your autosave is kept, so **Continue** works).
- In-game slash commands work as they do in the CLI: `/help`, `/inv`,
  `/char`, `/status`.  `/model` is display-only (switching models stays
  in the config files).  `/debug` is disabled, because it would flip
  the process-global log level for every chat.
- In combat, the bot posts a text battle panel (HP bars, initiative
  order, status effects) after each turn.  During rests, the rest-mode
  bookkeeping menu arrives as a plain numbered menu — reply with the
  number as in the CLI.
- When the adventure ends, the bot delivers the ending and a final
  panel with buttons: **Restart adventure**, **Load save**, **Choose
  adventure**.
- Multiple chats can play independently in one bot process; each chat
  gets its own save sandbox under
  `~/.config/mgmai/telegram/<chat_id>/saves/<adventure>/`, so autosaves
  and `/save` files never collide — even when one chat plays several
  adventures.  The `/load` browser shows all of the chat's saves,
  across adventures (loading another adventure's save switches to that
  adventure).

## Limitations (current phase)

Notable gaps, all planned in `telegram-plan.md`:

- **Combat/status panels are plain messages**, reposted each turn
  (in-place edits are a later phase), and **rest mode uses the numbered
  text menu** rather than inline keyboards.
- **No character-sheet upload, no group chats, no streaming** (turns
  reply once, when complete), and **model switching is display-only**
  (`/model` shows the config; switching stays in the config files).

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
