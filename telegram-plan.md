# Telegram Interface — Design Plan

Extend the AI GM with a Telegram bot front-end (bot token from
BotFather), as a first-class sibling of the CLI — not a bolt-on.  The
work splits into two halves:

1. **A modularity refactor** (Phase 0) that separates the game session
   core from terminal-specific I/O, so that neither interface is the
   "real" one, and that makes the engine safe to run as multiple
   concurrent sessions in one process.
2. **The Telegram front-end itself** (Phases 1–3): bot plumbing,
   per-chat session management, in-chat adventure selection /
   load / restart, and re-implementations of the combat panel and
   rest-mode bookkeeping UI.

---

## 1. Goals and non-goals

### Goals

- Play a full adventure over Telegram: natural-language turns, combat,
  dialogue, rests (including the rest-mode bookkeeping UI), game over.
- In-interface session lifecycle: choose an adventure, start, save,
  list/load saves, restart, quit — replacing the CLI's command-line
  options and quit-and-relaunch workflow.
- CLI and Telegram as equal front-ends over one shared core; the
  headless/integration-test harness benefits from the same cleanup.
- Multiple chats playing independently in one bot process — no shared
  mutable state between sessions.
- Survive bot restarts: sessions resume from autosaves.

### Non-goals (v1)

- Character-sheet upload (`--char-sheet` equivalent) — future work
  (Telegram file upload → `StateManager._apply_char_sheet_data`, the
  dict-level variant at `manager.py:378-422`, so no temp file needed).
- In-chat model switching (`/model` shows config only; switching stays
  in config files for v1).
- Group chats, multiple concurrent players in one chat, channels.
- Webhook deployment — long-polling only (webhook stays possible later
  with no design change).
- Streaming/partial narration — turns reply once, when complete.

---

## 2. Why a refactor is needed (current state)

Today the CLI is the de-facto "real" interface:

- `GameLoop` (`mgmai/game/loop.py`, ~700 lines) mixes three jobs: the
  turn pipeline (`_run_turn` :229 / `_execute_turn` :305 /
  `_finalize_turn` :440), input dispatch (`_dispatch_input` :182), and
  the terminal REPL (`_repl` :159, `input()` :163, readline history at
  module level :44-86 with `atexit.register(_save_history)` :86).
- `Display` (`mgmai/game/display.py`) is a concrete Rich-terminal
  renderer; `GameLoop` is typed against it directly.  The headless
  harness works only by subclassing it (`RecordingDisplay`) and by
  reaching into private loop methods (`_dispatch_input` and `_run_turn`
  at `headless.py:411,415`, `_display.render_intro` at :349,
  `_last_result`/`_last_action` at :440,449).  The integration harness
  also reaches in: `tests/integration/indicator_runner.py:242` calls
  `session.loop._call_prose(...)`.
- `Commands` (`mgmai/game/commands.py`) is front-end agnostic in its
  output path (renders through an injected callable) and already has
  an interactivity guard for `/model` (see 4.4) — but it owns the
  config-dir concept that the per-chat sandbox design must refine
  (4.7).
- Adventure selection, `--load`, and `--char-sheet` are CLI arguments
  in `cli.py`; restarting means quitting and re-invoking the command.
- The combat status panel (`Display._render_combat_status`,
  `display.py:168-403`) and the rest-mode menu (`RestMode`) are the two
  UI elements a Telegram front-end must re-implement.  Rest mode is
  already single-step and terminal-free by design (`rest_mode.py:17-29`
  explicitly anticipates non-terminal front-ends); the combat panel is
  not — its data assembly (nested closures sharing locals, plus
  terminal-width detection at :182-187) is fused with Rich rendering.
- **The engine is not multi-session safe.** `event_bus._disabled_once`
  is a module-level global (`mgmai/engine/event_bus.py:37-42`), and
  `StateManager.load_all` resets it (`manager.py:144-146`).  Two
  sessions in one process would corrupt each other: one chat loading a
  game wipes the other's disabled once-reactions, and concurrent turns
  share the set.  This must be fixed before any multi-chat bot ships.
- **Autosave has gaps that matter for "resume from autosave":** the
  game-over turn is never autosaved (`_finalize_turn` returns before
  `_auto_save`, `loop.py:445-455`), and when `config_dir` is None the
  autosave path falls back to a CWD-relative `autosave.json`
  (`loop.py:478`) — the stray file in the repo root is exactly that
  leak.

The existing `HeadlessSession` (`mgmai/game/headless.py`) proves the
composition pattern a Telegram back-end needs: StateManager + loop +
recording view + single-turn `submit()`.  Phase 0 promotes that pattern
from test harness to public architecture.

---

## 3. Target architecture

```
                    ┌──────────────────────────────┐
                    │          GameSession         │   front-end agnostic
                    │  turn pipeline, dispatch,    │   (no input(), no Rich,
                    │  rest mode, autosave,        │    no REPL)
                    │  game-over detection         │
                    └───────┬──────────────┬───────┘
                            │              │
                     GameView protocol (mgmai/game/view.py)
                            │              │
                 ┌──────────┴───┐   ┌──────┴─────────┐
                 │   RichView   │   │  TelegramView  │
                 │  (terminal)  │   │ (buffers events│
                 │              │   │  → chat msgs)  │
                 └──────────┬───┘   └──────┬─────────┘
                            │              │
                     ┌──────┴─────┐  ┌─────┴──────────────┐
                     │ CLI front- │  │ Telegram front-end │
                     │ end REPL   │  │ PTB handlers,      │
                     │            │  │ session registry,  │
                     │            │  │ keyboards          │
                     └────────────┘  └────────────────────┘

        HeadlessSession (tests/automation) = GameSession + RecordingView
```

Shared structured view-models (`mgmai/game/status.py`) feed both
renderers, so the combat panel is computed once and rendered per
front-end.

---

## 4. Phase 0 — Core refactor (behavior-preserving)

All existing tests must stay green; each step is independently
mergeable.  Roughly 90–100 tests touch `GameLoop`/`Display`/
`HeadlessSession` internals directly (`test_loop.py` alone has 25
tests calling `_execute_turn`/`_run_turn`/`_repl`), so keeping the old
names as aliases and keeping the moved private methods reachable is
the cheap path.

### 4.1 Extract `GameSession` from `GameLoop`

New `mgmai/game/session.py`:

- Move into `GameSession`: `_run_turn`, `_execute_turn`,
  `_finalize_turn`, `_dispatch_input`, `_maybe_enter_rest_mode`,
  `_call_ruling`, `_call_prose`, `_strip_invalid_positioning`,
  `_strip_invalid_embellishments`, `_auto_save`, `_on_game_loaded`,
  `_on_model_change`, `_chat_log`, `ruling_retries`, `turn_combat_log`.
- Public API:

  ```python
  class GameSession:
      def __init__(self, state_manager, llm_client, *, view,
                   config_dir=None, saves_dir=None, debug=False,
                   interactive=None, prose_validation_enabled=True): ...
      def begin(self) -> None            # render intro (no REPL)
      def submit(self, line: str) -> TurnResult
      finished: bool                     # game over (or /exit) reached
      in_rest_mode: bool
      rest_mode: RestMode | None         # for structured menu access
      state_manager / hard_state / corpus properties
  ```

- `submit` returns a structured result, not `str | None`: today's
  private `_run_turn` returns `str | None`, but the real consumer
  contract is `HeadlessSession.submit`'s `TurnTranscript`
  (`headless.py:97-144` — narration, `StatusSnapshot`, game_over,
  errors, combat log, engine outcome).  Define a public `TurnResult`
  carrying those fields; `HeadlessSession` becomes a thin adapter that
  maps `TurnResult` onto `TurnTranscript` without touching privates.
  The single structured return is the chosen design, not merely the
  preferred one: the alternative (the headless adapter assembling
  `TurnTranscript` from public session state) would re-create exactly
  the `_last_result` / `_last_action` private-peeking this refactor
  removes.
- Thread the existing `interactive` kwarg (currently on `GameLoop`,
  forwarded to `Commands`, `loop.py:145`) through `GameSession` so the
  `/model` guard keeps working.
- **Game over becomes state, not REPL control.** `_finalize_turn`
  currently calls `_do_exit()` (which sets `_running = False` and
  renders goodbye, `loop.py:700-702`) when `hard.game_over` is set.  In
  `GameSession`, set `finished` and render `render_game_over`; the
  *front-end* decides what "finished" means (CLI: exit the REPL;
  Telegram: offer restart/new/load buttons).
- REPL concerns leave the loop: `input()`, readline setup, and the
  history file stay in the CLI front-end.  The module-level
  `atexit.register(_save_history)` moves with them.  (Note the history
  path hardcodes `~/.config/mgmai/history` rather than using
  `get_config_dir()` — harmless, but fix while moving it.)
- `GameLoop` survives as a thin CLI wrapper (REPL over a `GameSession`)
  or is folded into the CLI front-end module; keep the name as an alias
  for one release so existing imports/tests keep working.  The moved
  private methods must remain reachable on the wrapper (or be
  re-exported) until `test_loop.py`, `test_ruling_validation.py`, and
  `tests/integration/indicator_runner.py:242` (`session.loop._call_prose`)
  are migrated.
- `HeadlessSession` is re-implemented on the public `GameSession` API —
  no more private-method access.

### 4.2 Define the `GameView` protocol

New `mgmai/game/view.py`:

```python
class GameView(Protocol):
    def render_intro(self, state: StateManager) -> None: ...
    def render_narration(self, text: str) -> None: ...
    def render_status(self, state: StateManager) -> None: ...
    def render_error(self, text: str) -> None: ...
    def render_rest_menu(self, text: str) -> None: ...
    def render_game_over(self, result: Any) -> None: ...
    def render_goodbye(self) -> None: ...
    def print(self, text: str) -> None: ...   # command output (markup)
```

- `Display` becomes the Rich implementation (`RichView`; keep
  `Display` as an alias so imports/tests keep working).
  `RecordingDisplay` becomes `RecordingView` (alias likewise).
- `Display.format_exits` is **not** part of the protocol: it is a pure
  staticmethod that the turn pipeline calls directly
  (`loop.py:279,292`; tests mock it).  Keep it as a module-level
  helper in `display.py` (or move it to `status.py`) and have
  `GameSession` call it directly; re-export from `display.py` so
  existing imports and mocks keep working.
- `Commands` already receives `render` as a callable — it conforms via
  `view.print`; no change needed there beyond 4.4.

### 4.3 Shared status/combat view-models

New `mgmai/game/status.py`:

- Promote `_snapshot_status` / `StatusSnapshot` out of `headless.py`
  (:215-305, :56-94; headless re-imports them, no API change for
  tests).
- Extract the combat-panel *data assembly* currently fused into
  `Display._render_combat_status` (`display.py:168-403`): per-combatant
  rows (name, hp/max, status effects, fled, engagement, impeded),
  initiative order + current actor, discovered mitigations, and the
  player footer (AC, weapon, ability uses, usable items —
  `_combat_player_footer`, :405-455) into a structured `CombatView`
  builder.  Note this is a rewrite of the method body, not a
  cut-paste: the assembly is nested closures (`_row_data`,
  `_status_effects_text`, `_mitigation_text`, …) sharing locals
  (`discovered`, `effect_defs`, `bar_width`), and the terminal-width
  adaptation (`self._console.width` / `shutil.get_terminal_size`,
  :182-187) must move into the Rich renderer (bar width becomes a
  renderer parameter; `RecordingView` keeps its pinned width of 120,
  `headless.py:161-165`).
- `RichView.render_status` consumes `CombatView` (same output as
  today); `TelegramView` renders the same data as a chat message
  (5.6).

### 4.4 `Commands`: injectable prompter for `/model`

The blocking-`input()` hazard is already handled: `Commands` has an
`interactive` flag (constructor kwarg, `commands.py:75,88`, defaulting
to a TTY probe at :51-61); non-interactive `/model` prints the config
block plus an "edit config files / env vars" hint and returns
(:296-302), and `HeadlessSession` passes `interactive=False`
(`headless.py:345`).  `test_model_non_interactive_never_prompts`
covers it.

What remains is a refinement: route the interactive prompts
(`input()` at :305,319,377, `getpass.getpass()` at :349, all inside
`_cmd_model` :242-412) through an optional injectable prompter
(defaulting to terminal `input()`/`getpass()` when interactive).  This
keeps the CLI behavior identical and leaves the door open to a
conversational model-switcher later.  For Telegram v1, `/model` runs
non-interactive (display-only).

(Longer-term option: convert switching to the same single-step
state-machine idiom as `RestMode` so any front-end can drive it; not
required for v1.)

### 4.5 Structured rest-mode menu

`RestMode` keeps its exact `handle(line) -> str` contract, and gains a
read-only snapshot so button-based front-ends don't parse text:

```python
@dataclass
class RestMenuSnapshot:
    kind: str            # "short" | "long"
    state: str           # "top" | "prepare" | "spend" | "exited"
    summary: str         # rest result summary
    status_line: str     # HP / hit dice / slots
    feedback: str
    options: list[str]   # labels, in numbering order

def menu(self) -> RestMenuSnapshot: ...
```

Option numbering in the prepare/spend menus is positional and dynamic
(varies with spellbook contents), so `options` stays an ordered label
list and button presses map to `handle(str(index))`.  The `"exited"`
state represents the post-"Done" condition (`_exited` set, farewell
text, no menu) so a button UI knows to tear its keyboard down.

CLI ignores the snapshot; Telegram builds inline keyboards from it
(5.6).

### 4.6 Per-session engine state (multi-session safety)

Move the once-reaction tracking off the module level:

- `event_bus._disabled_once` (`engine/event_bus.py:37-42`) becomes
  per-session state owned by `StateManager` (or the event-bus
  instance), and `load_all`'s `reset_disabled_once()` call
  (`manager.py:144-146`) resets that per-session set instead of a
  global.  Behavior for a single session is unchanged; two sessions in
  one process no longer corrupt each other.
- Audit while there: the shared global RNG (`random.randint` in
  `engine/systems/five_e.py:159-163,225`, `engine/combat.py:429`) is
  functionally fine under threads; per-chat determinism is a non-goal.
  `/debug` flips the process-global `mgmai` logger level
  (`commands.py:232-240` → `mgmai/logging.py:73-79`) — acceptable for
  the CLI; Telegram disables or ignores `/debug` (5.5).

### 4.7 Save/directory plumbing

The bot needs per-chat save isolation *without* breaking global config
resolution.  Today `Commands._cmd_model` reads/writes `config.json`,
`credentials.json`, and `models.json` from its `config_dir`
(`commands.py:279-281`), while saves go to
`get_saves_dir(adventure, config_dir)` (`config.py:53-57`) — one
`config_dir` serves both purposes, so sandboxing it would also sandbox
model config (wrong) and not sandboxing it would share saves (wrong).

- Introduce an explicit `saves_dir` override (on `StateManager` and/or
  `Commands`, defaulting to `get_saves_dir(adventure, config_dir)`).
  All save/load paths — autosave (`loop.py:_get_autosave_path`),
  `/save` (`commands.py:196-207`), `/load` — honor it.  `config_dir`
  keeps its config/credentials meaning.  Note `StateManager.config_dir`
  is stored but currently unused inside manager.py (save paths are
  directed by callers); the `saves_dir` override is where the behavior
  actually lives.
- Autosave the game-over turn too (currently skipped,
  `loop.py:445-455`) so resume-after-restart captures final state.
- Autosave rest-mode bookkeeping too: rest steps run through
  `_dispatch_input` (`loop.py:192-197`), which never autosaves, and
  neither does `/quit` → `_do_exit` (`loop.py:700-702`) — today a
  player who spends hit dice and quits loses the changes.  Save after
  each rest-mode step that mutates state (and on clean session end).
  This is an existing CLI bug, but it becomes user-visible under the
  bot's resume-after-restart goal (5.3), where a restart can land in
  the middle of rest mode.
- Require an explicit `config_dir`/`saves_dir` in `GameSession` (no
  CWD-relative `autosave.json` fallback, `loop.py:478`); the CLI
  front-end passes the resolved config dir as today.  Delete the
  stray repo-root `autosave.json` artifact.
- Store `latest_narration` in *named* saves as well: today only the
  autosave path passes it (`loop.py:465-467`); `Commands._cmd_save` →
  `StateManager.save()` (`manager.py:1109-1115`) does not.  The
  Telegram save browser (5.5) shows the snippet for every save.

### 4.8 Small cleanups folded into Phase 0

- Remove dead code: `Display.rule` (`display.py:48-52`) has no
  callers.
- `Commands` reaches into `StateManager._adventure_dir`
  (`commands.py:192-193`, `loop.py:481`) — expose a public accessor
  while touching these files.

---

## 5. Telegram front-end

### 5.1 Library and packaging

- **python-telegram-bot v21+** (PTB), pinned `>=21,<22`: asyncio-native,
  inline keyboards, callback queries, long polling, mature docs.
  (Alternative: aiogram — also fine, but PTB's API is simpler for a
  single-bot, single-developer project.)
- Optional dependency extra in `pyproject.toml`:

  ```toml
  [project.optional-dependencies]
  telegram = ["python-telegram-bot>=21,<22"]

  [project.scripts]
  mgmai-telegram = "mgmai.telegram:main"
  ```

- New package `mgmai/telegram/` (bot.py, sessions.py, view.py,
  keyboards.py, textutil.py).  Importing it is optional — the CLI and
  tests never require PTB.

### 5.2 Configuration and credentials

- Bot token: `MGMAI_TELEGRAM_BOT_TOKEN` env var, or
  `~/.config/mgmai/credentials.json`.  The latter needs a small
  `Credentials` schema change (`config.py:133-155` currently
  serializes only `{"api_keys": {...}}` and would silently drop a
  `"telegram"` key on any `save_credentials` round-trip): add a
  `"telegram": {"bot_token": ...}` section with the same 0600
  permissions (`config.py:170-185`).  Never logged.
- New keys in `AppConfig` (`config.json`; extend the dataclass plus
  `to_dict`/`from_dict`, `config.py:68-104`):
  - `telegram_allowed_chat_ids: list[int]` — **mandatory allow-list**.
    A public bot is an open proxy to the LLM API budget; messages from
    other chats get a polite refusal.
  - `telegram_adventures_dir: str | None` — where to scan for
    adventures (subdirectories containing `corpus.json`).  Required:
    no implicit CWD-relative default (that is the class of leak §4.7
    removes from autosaves) — unset, or a directory containing no
    adventure, aborts bot startup with a clear message.  From a repo
    checkout, point it at `./adventures`.
- LLM model config is resolved once at bot startup using the existing
  resolution chain (env → config file).  No interactive prompting —
  `_prompt_for_llm_config` stays CLI-only; a missing config aborts bot
  startup with a clear message.

### 5.3 Session registry and lifecycle

New `mgmai/telegram/sessions.py`:

```python
@dataclass
class ChatSession:
    chat_id: int
    adventure_path: Path
    session: GameSession
    view: TelegramView
    lock: asyncio.Lock          # serialize turns per chat
    status_message_id: int | None   # in-place-updated status panel

class SessionRegistry:
    def get(chat_id) -> ChatSession | None
    def start_new(chat_id, adventure_path) -> ChatSession
    def load_save(chat_id, save_path) -> ChatSession
    def end(chat_id) -> None
    # persisted index: config_dir/telegram/sessions.json
    #   chat_id -> {adventure_path, last_save}
```

- **Per-chat save sandbox:** each chat gets
  `config_dir/telegram/<chat_id>/saves/` as its `saves_dir` (4.7), so
  autosaves and `/save` files of two chats playing the same adventure
  never collide (today a single `saves/<adventure>/autosave.json` per
  config dir is shared — fine for one CLI user, wrong for a multi-chat
  bot).  `config_dir` stays the real one, so model config and
  credentials resolve globally.
- **Bot restarts:** the registry index maps chat_id → adventure +
  latest save.  On the first message from a known chat with no live
  session, the bot offers **Continue** (loads the autosave) or
  **New game**.
- **Concurrency:** turns run via `asyncio.to_thread(session.submit,
  text)` under the per-chat lock (the engine and `LLMClient` are
  synchronous; client retries use blocking `time.sleep`,
  `llm/client.py:150-162`, which is fine inside a worker thread).
  While a turn runs, the bot sends periodic
  `send_chat_action("typing")` (a turn = 2 LLM calls plus retries,
  typically 5–30 s).  Queued second messages from the same chat wait
  on the lock rather than interleaving.
- **Game over:** `session.finished` → final panel with buttons:
  Restart adventure / Load save / Choose adventure.

### 5.4 Message flow (one turn)

1. Text message arrives → allow-list check → session lookup (else main
   menu, 5.5).
2. Acquire chat lock; start typing-action heartbeat.
3. `TelegramView` begins buffering; run `session.submit(text)` in a
   worker thread.
4. Flush buffered view events to the chat, in order:
   - `render_narration` → one message (chunked at Telegram's 4096-char
     limit, split on paragraph boundaries — `textutil.py`).
   - `render_status` → the status/combat panel message.  If the chat
     already has one from a previous turn, **edit it in place**
     (`edit_message_text`) instead of posting a new one, to avoid
     spam; during combat this panel is the persistent battle display.
     When combat ends, the same message is edited into the plain
     out-of-combat status line so no stale battle panel lingers (the
     message id is kept either way — there is always exactly one
     status message per chat).  Identical-content edits raise
     `BadRequest` ("message is not modified") in PTB: compare text
     before editing and treat a no-op as success.
   - `render_rest_menu` → menu message + inline keyboard (5.6).
   - `render_game_over` → final panel + lifecycle buttons.
   - `render_error` → plain error message.
5. Callback queries (buttons) are answered the same way under the same
   lock.

### 5.5 In-interface session lifecycle

Replaces CLI args / quit-and-relaunch:

| Command | Behavior |
|---|---|
| `/start` | Welcome + main menu: **New game**, **Continue** (when a saved session exists), **Help**. |
| `/new` | Adventure picker: inline keyboard listing adventures found in `telegram_adventures_dir` (title from `corpus.adventure.title` plus a truncated `introduction` — there is no dedicated blurb field; if truncation reads badly, add an optional `summary` field to the adventure block).  Confirm if a session is already active. |
| `/restart` | Restart the current adventure from the beginning (confirmation button). |
| `/load` | Save browser: inline keyboard over the chat's sandboxed saves dir (filename, mtime, `latest_narration` snippet — stored in all saves after 4.7), plus the autosave. |
| `/save [name]` | Explicit save via the existing `Commands._cmd_save` path (sandboxed dir). |
| `/quit` | End the session (state is autosaved every turn, plus game-over turns and rest-mode steps after 4.7). |
| `/status`, `/inv`, `/char`, `/help` | Existing `Commands` handlers, output converted (5.6). |
| `/model` | Display-only (non-interactive mode, 4.4). |

- Register these with `set_my_commands` so they appear in Telegram's
  command menu.
- In-game slash commands (`/save` etc.) arrive as ordinary message
  text and route through `session.submit` → `Commands` exactly as in
  the CLI — no duplication.  PTB caveat: the default text filter
  (`filters.TEXT & ~filters.COMMAND`) excludes `/…` messages, so the
  session's message handler must be registered command-inclusive for
  in-game commands (lifecycle commands like `/new` get their own
  `CommandHandler`s); the command *logic* is never re-implemented in
  the bot layer.
- Classic shortcuts (`n`, `x spider`, …) work unchanged via
  `normalize_player_input` (`mgmai/game/input_normalizer.py:48`), which
  is pure and front-end-agnostic already.
- `/debug` is disabled (or answered with a refusal) on Telegram: it
  flips the process-global `mgmai` logger level and would affect every
  chat (4.6).
- Rest mode caveat (unchanged from CLI): while rest mode is active,
  menu input takes precedence over slash commands (`_dispatch_input`
  routes to rest mode first, `loop.py:192-197`) — on Telegram the
  inline keyboard makes this explicit.

### 5.6 UI re-implementations

**Combat display.** Render the shared `CombatView` (4.3) as a single
message, edited in place between turns:

```
⚔ Combat — Round 2
Initiative: player → goblin → wolf

Party
  Player        HP ████████░░ 8/10  [poisoned 2]
Enemies
  Goblin        HP ███░░░░░░░ 3/7   (resists piercing) ⚔ Player
  Wolf †        HP ░░░░░░░░░░ 0/5

AC 14 · longsword (1d8 slashing) · Items: potion x2
It's your turn.
```

- Sent inside a `<pre>` block (HTML parse mode) so the bars align.
  HTML is chosen over MarkdownV2 because escaping is trivial.
- HP bars, status-effect labels, discovered mitigations, engagement
  markers — all from the shared builder; nothing re-derived.  Bar
  width is a fixed renderer parameter here (no terminal to measure).

**Rest mode (ability assignment).** Inline keyboards driven by
`RestMode.menu()` (4.5):

- Top menu: one button per option (Prepare spells / Spend hit dice /
  Done).
- Prepare-spells menu: one toggle button per spellbook entry
  (`✅ Fire Bolt` / `▫️ Fire Bolt`) plus **Confirm** and **Back**;
  each press maps to `RestMode.handle(str(index))` and re-renders by
  editing the menu message.  Confirm = `handle("0")`.
- Spend-hit-dice menu: Spend another / Done buttons.
- When `menu().state == "exited"`, remove the keyboard (edit the menu
  message to the farewell text).
- The CLI's numbered-input mode is untouched.

**Intro / room panels.** `TelegramView.render_intro` posts the
adventure title, introduction, credits, and the starting room
(description + visible exits, via the shared `format_exits` helper) as
plain messages.

**Rich-markup conversion.** `Commands` output (`/inv`, `/char`,
`/help`) uses Rich markup (`[bold]…`).  `textutil.py` provides a small
Rich-markup → Telegram-HTML converter (bold/italic/dim/cyan →
b/i/code), with tag stripping as the fallback.  This keeps `Commands`
shared and unmodified.

### 5.7 Security / operational notes

- Allow-list enforced before anything else (5.2).
- Token and API keys only in `credentials.json` / env; never in logs
  (PTB logging configured at WARNING for the httpx/PTB loggers).
- Graceful shutdown (`SIGINT`): end sessions; state is autosaved each
  turn (including game-over turns and rest-mode steps, after 4.7).
- Long turns: PTB handler timeouts are not an issue because work is
  dispatched to threads and replies are sent explicitly; set
  `concurrent_updates` conservatively (per-chat lock is the real
  serializer).

---

## 6. New / changed files

```
mgmai/
├── game/
│   ├── session.py        NEW  GameSession + TurnResult (from loop.py)
│   ├── view.py           NEW  GameView protocol
│   ├── status.py         NEW  StatusSnapshot + CombatView builders,
│   │                          format_exits helper
│   ├── loop.py           CHG  thin CLI REPL over GameSession; moved
│   │                          privates stay reachable (alias/delegate)
│   ├── display.py        CHG  RichView (alias Display); combat data
│   │                          assembly moved to status.py; drop dead
│   │                          rule(); width logic stays here
│   ├── headless.py       CHG  re-implemented on public GameSession;
│   │                          re-exports from status.py
│   ├── commands.py       CHG  injectable prompter for /model (4.4);
│   │                          saves_dir override; latest_narration in
│   │                          named saves; public adventure_dir accessor
│   └── rest_mode.py      CHG  + RestMenuSnapshot / menu()
├── engine/event_bus.py   CHG  per-session once-reaction state (4.6)
├── state/manager.py      CHG  owns once-reaction set; saves_dir
│                              override; latest_narration in save()
├── telegram/             NEW
│   ├── __init__.py            main() entry point
│   ├── bot.py                 PTB Application, handlers, typing loop
│   ├── sessions.py            SessionRegistry, ChatSession, persistence
│   ├── view.py                TelegramView (buffering GameView)
│   ├── keyboards.py           adventure/save/rest/game-over keyboards
│   └── textutil.py            chunking, Rich→HTML conversion
├── cli.py                CHG  uses GameSession/RichView (thin)
├── config.py             CHG  telegram config keys; Credentials
│                              "telegram" section
pyproject.toml            CHG  telegram extra + mgmai-telegram script
tests/
├── test_session.py       NEW  GameSession public API (migrated from
│                              test_loop.py as needed)
├── test_telegram_view.py NEW  rendering/chunking/conversion
├── test_telegram_sessions.py NEW  registry with stubbed PTB objects
├── test_loop.py          CHG  migrated off private methods where
│                              practical (25 tests call them today)
├── integration/indicator_runner.py  CHG  off session.loop._call_prose
└── (remaining suites unchanged, green)
```

---

## 7. Phasing

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Refactor** | §4.1–4.8. No behavior change for a single session, except the deliberate save-handling fixes itemized in §4.7. | Full pytest suite green including the integration harness (`indicator_runner` migrated); `HeadlessSession` uses only public API; two `GameSession`s in one process run interleaved turns without cross-talk (new test over the once-reaction state). |
| **1 — Bot skeleton** | §5.1–5.2, 5.4. One hardcoded/configured adventure; text in → turn → narration out; typing indicator; allow-list. | Manual playthrough of a few turns; unit tests for TelegramView with FakeLLMClient (project convention: no network in unit tests). |
| **2 — Lifecycle** | §5.3, 5.5: registry, per-chat saves sandbox, `/new` `/load` `/save` `/restart` `/quit`, resume-after-bot-restart. | Two chats play the same adventure independently (including once-reactions not leaking across chats); kill/restart bot and continue. |
| **3 — UI polish** | §5.6: combat panel (in-place edits), rest-mode keyboards, intro panels, markup conversion, message chunking. | Combat-heavy and rest-heavy playthroughs over Telegram; unit tests for keyboards/view. |

Testing follows project conventions: fake LLM clients, no network
(`tests/helpers.py`, `test_headless.py` as templates); PTB objects
stubbed with plain fakes; live-bot smoke checks documented but not in
CI.

---

## 8. Risks and open questions

- **LLM latency UX.** A turn is two sequential LLM calls (plus
  retries).  Typing indicator + in-place status edits should carry it;
  if not, consider "thinking…" placeholder messages edited into the
  narration.  Streaming is deliberately deferred.
- **Message editing limits.** Editing the status panel every turn is
  fine, but Telegram rate-limits edits (~30/s global, lower per chat);
  at single-player cadence this is not a problem.
- **Save-file growth.** Per-chat sandboxes duplicate saves per chat;
  acceptable at this scale.  A pruning policy (keep N latest) is a
  possible follow-up.
- **`/model` in Telegram.** Display-only in v1; a single-step
  conversational switch (RestMode-style) is the natural v2.
- **Char sheets.** File-upload support maps cleanly onto
  `_apply_char_sheet_data` (no temp file needed); deferred.
- **PTB version churn.** Pin `>=21,<22` (v22 changes a few handler
  signatures); the front-end isolates PTB to `mgmai/telegram/`.
