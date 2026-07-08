# Plan: Programmatic hard state generation from the corpus

## Background and motivation

The project currently requires three JSON files to define an adventure:
`corpus.json` (immutable adventure content), `hard-state.json` (initial
mutable state), and `soft-state.json` (initial narrative state). The
corpus and hard-state files are both LLM-authored, using the workflow
described in `schema/scenario-generation.md`.

This is redundant *for the world state*. The corpus already carries all
the information needed to derive the initial world state:

- **Room / entity state fields** are declared in the corpus with their
  type, description, and — per the corpus schema docs — an `initial`
  value (though the Pydantic model `StateFieldDecl` doesn't yet expose
  this field).

- **Flags** are enumerated in `flags_declared` and universally start
  `false`.

- **Containment** (`room_contains`, `entity_contains`) is already
  initialised programmatically from the corpus `contains` fields by
  `StateManager._init_contains_from_corpus()`.

- **Player location** is determined by the room with `is_start_room: true`.

Requiring the LLM to duplicate this information into a separate file
creates a synchronisation problem with no benefit.

**However, the player block is a different concern.** `hard_state.player`
(ability scores, level, HP, AC, saves) is *not* derivable from the
corpus: the corpus declares stat *definitions* and the resolution
*system*, but not a specific character's values. The earlier draft of
this plan assumed `_init_player_combat_defaults()` could produce these.
That is wrong — that function only derives HP/AC/proficiency *from
already-populated stats and level* (`manager.py:342-377`), and its HP
formula is **level-1 only** (`base_max_hp = 8 + CON mod`,
`five_e.py:455-456`). It cannot reproduce, say, a level-4 rogue's 27 HP.
So the player block needs its own home.

The design therefore splits the initial state along this seam:

- **World state** (rooms, entities, flags, containment) → *generated*
  from the corpus.
- **Player character** (stats, level, HP, AC, saves) → a new
  `default-player.json`, reusing the existing character-sheet format.

This follows the D&D boxed-set model: the booklet (corpus) describes the
world and its initial conditions; a separate pre-generated character
sheet (`default-player.json`) supplies the bundled default hero; the
player may instead bring their own character sheet (`--char-sheet`).

## Design decisions

### 1. State sources and the role of each file

| File                | Required?                  | Role                                                          |
|---------------------|----------------------------|---------------------------------------------------------------|
| `corpus.json`       | always                     | Immutable world content + stat/system definitions             |
| `soft-state.json`   | always                     | Initial narrative state (trivially empty today)              |
| `default-player.json` | iff `corpus.stats` present | Default player character (char-sheet format)                  |
| `hard-state.json`   | optional override          | World-state overrides + optional player-block override        |

`hard-state.json` becomes an **optional override**. If present, it is
loaded and validated as today (minus the changes below); if absent, the
`StateManager` generates the initial world state from the corpus. The
override is useful for post-publication tweaks (e.g. a harder mode with
different room/entity starting values) without editing the canonical
corpus.

### 2. `default-player.json` and the player-block cascade

`default-player.json` carries the adventure's default player character.
It **reuses the character-sheet schema** — `{"system": "5e", "player": {...}}`
— so there is exactly one player-data format and one field-merge path
(the existing per-field `setattr` merge in `manager.py:181-187`).

At new-game init, the player block is resolved as a **field-by-field
overlay** (lowest priority first):

1. **Base**: `location` seeded from the start room; all other `PlayerState`
   fields `None`.
2. **`default-player.json`** (if present) — the adventure's default hero.
3. **`hard-state.json`'s `player` block** (if present) — the author's
   tweak (e.g. hard-mode starting HP).
4. **`--char-sheet`** (if supplied) — the player's own character,
   applied via the existing `apply_char_sheet()`.

This is an *overlay*, not an either/or: a partial `--char-sheet` that
sets only `inventory` composes on top of `default-player.json`'s stats,
preserving the current partial-sheet behaviour (`manager.py:181-187`).

**"The scenario needs player data"** ⟺ `corpus.stats is not None` (this
is already how `_validate_player_stats` decides, `manager.py:330-333`).
If player data is needed and none of the three sources supplies it, the
game does not start (load error). Stat-less adventures need no
`default-player.json` and behave exactly as today.

**HP is not derivable for multi-level characters.** Because
`_init_player_combat_defaults` only computes the level-1 base HP,
`default-player.json` MUST carry the full combat block explicitly —
`stats`, `level`, `max_hp`, `current_hp`, `ac`, `proficiency_bonus`,
`save_proficiencies` — for any character above level 1. The init helper
fills only fields left `None` after the cascade.

`default-player.json` is consulted **only at new-game init**. Saves
already serialise the full player block (`manager.py:466-469`), so
`load_save()` is unchanged and never reads `default-player.json`.

### 3. World state generation from the corpus

When `hard-state.json` is absent, `StateManager` generates the initial
world state from the corpus:

- **Room states**: for every room `rid` — seed `{"visited": false}`, then
  for each `(field, decl)` in `room.state_fields`: `decl.initial` if set,
  else the reserved-field default (e.g. `visited → false`), else the type
  default.
- **Entity states**: for every entity with at least one declared state
  field — for each `(field, decl)`: `decl.initial` if set; else special
  rules for `attitude` (← `dialogue.attitude_limits.initial`) and
  `current_hp` (← `combat.hp`); else `RESERVED_STATE_FIELD_DEFAULTS`;
  else the type default.
- **Flags**: `corpus.flags_initial` (see §6).
- **Containment** (`room_contains`, `entity_contains`): left to the
  existing `_init_contains_from_corpus()`.
- **Player location**: the room with `is_start_room: true` (error if
  none or multiple).
- **Constants**: `turn_count: 0`, `game_over: null`, `combat: null`.

The player block is *not* generated here; it is resolved by the cascade
in §2 and attached to the generated `HardGameState`.

### 4. Adding `initial` to `StateFieldDecl`

The corpus schema already documents `initial` (`schema/corpus.md` lines
538, 593, 975), but the Pydantic model only has `type` and `description`.
The model gains:

```python
class StateFieldDecl(BaseModel):
    type: Literal["boolean", "number", "string"]
    description: str
    initial: Any = None  # validated against 'type' at model-validate time
```

Validation: if `initial` is not `None`, it must match `type`:
- `boolean` → `isinstance(value, bool)`
- `number` → `isinstance(value, (int, float)) and not isinstance(value, bool)`
  (bool subclasses int in Python, so `True` must not be accepted as the
  number `1`)
- `string` → `isinstance(value, str)`

The sentinel `None` means "no explicit initial" — the generator uses the
fallback (reserved-field default or type default).

### 5. Reserved state fields: special initial values

Reserved fields with well-known initial semantics are handled specially
by the generator. These default rules are documented in `corpus.md`:

| Reserved field  | Initial value                          |
|-----------------|----------------------------------------|
| `alive`         | `true`                                 |
| `hidden`        | declared `initial`, otherwise `false`  |
| `attitude`      | `dialogue.attitude_limits.initial`     |
| `current_hp`    | `combat.hp` (if entity has combat)     |
| `fled`          | `false`                                |
| `following`     | `false`                                |
| `open`          | declared `initial`, otherwise `true`   |
| `visited`       | `false` (room reserved field)          |
| `is_current`    | auto-computed, never in initial state  |

Authors may set an explicit `initial` on any reserved field; the
generator prefers the explicit value. If the field lacks both an explicit
`initial` and a special rule, it falls back to the type default.

### 6. Non-reserved (author-defined) state fields: type defaults

If an author-defined state field omits `initial`, the generator uses:

| Type      | Default |
|-----------|---------|
| `boolean` | `false` |
| `number`  | `0`     |
| `string`  | `""`    |

This is documented in `corpus.md` alongside the state field spec.

### 7. Flags: default false, with optional non-false initial

`flags_declared` changes from `List[str]` to accept entries with an
optional initial value. The new corpus format is:

```json
"flags_declared": [
  "spider_fled",
  { "injured": false },
  { "quest_started": true }
]
```

Plain strings mean "start false" (the common case). Dict entries
specify a non-false initial value. The Pydantic model changes:

```python
flags_declared: Optional[List[Union[str, Dict[str, bool]]]] = None
```

with a normalising validator and a `flags_initial: Dict[str, bool]`
property:
- Plain strings → `{"flag_id": false}`
- Dict entries → extracted directly
- The raw list is preserved for JSON round-trip; the property is the
  canonical runtime view.

Flags not listed in `flags_declared` but referenced in corpus conditions
are a corpus authoring error, caught by cross-validation (see B4).

All other hard state fields (`turn_count: 0`, `game_over: null`,
`combat: null`) are constant at game start and require no corpus change.

---

## Implementation phases

### Phase A: Model changes (`mgmai/models/`)

**A1. `corpus.py` — `StateFieldDecl.initial`**

Add `initial: Any = None`. Add a `@model_validator(mode="after")` that
validates `initial` against `type` when not `None`, per §4 (including
the `not isinstance(value, bool)` guard for `number`).

**A2. `corpus.py` — `ModuleCorpus.flags_declared`**

Change type from `Optional[List[str]]` to
`Optional[List[Union[str, Dict[str, bool]]]]`. Add a normalising validator
and a `flags_initial: Dict[str, bool]` property (plain strings →
`{"flag_id": false}`; dict entries extracted directly). The raw list is
preserved for JSON round-trip.

**A3. `corpus.py` — Reserved state field constants**

Add a module-level dict mapping reserved field names to their default
initial-value rules, for use by the generator in Phase B:

```python
RESERVED_STATE_FIELD_DEFAULTS: dict[str, Any] = {
    "alive": True,
    "fled": False,
    "following": False,
    "open": True,
    "visited": False,
}
```

Fields needing context (`attitude`, `current_hp`, `hidden`) are handled
by the generator inline; `hidden` defaults to `false`, `attitude` to
`attitude_limits.initial`, `current_hp` to `combat.hp`.

No changes to `actions.py`, `hard_state.py`, or `soft_state.py`.
`PlayerState` / `HardGameState` stay strict: `player` remains required in
the in-memory model. Optionality of the player block lives at the
loader/override layer (see B3), not in the model.

### Phase B: State generation (`mgmai/state/manager.py`)

**B1. `_init_world_state_from_corpus()` — new method**

Builds and returns the *world* portion of a `HardGameState` from the
corpus: `room_states`, `entity_states`, `flags`, `turn_count`,
`game_over`, `combat`. Algorithm per §3:

1. **Player location**: find the room with `is_start_room: true`. Error
   if none or multiple. (`validate_adventure.py` already checks this;
   the generator checks too so `load_all` fails fast without the script.)
2. **Room states**: seed `{"visited": false}`; then for each declared
   `(field, decl)`: `decl.initial` → reserved default → type default.
3. **Entity states**: for every entity with ≥1 declared state field, for
   each `(field, decl)`: `decl.initial` → `attitude`/`current_hp` special
   rule → `RESERVED_STATE_FIELD_DEFAULTS` → type default.
4. **Flags**: `corpus.flags_initial` if `flags_declared` is set, else `{}`.
5. **Containment**: not set here; `_init_contains_from_corpus()` handles it.
6. **Constants**: `turn_count=0`, `game_over=None`, `combat=None`.

**B2. `_resolve_player_block()` — new method**

Returns a `PlayerState` by overlaying (lowest priority first):
1. Base: `location` = start room; all other fields `None`.
2. `default-player.json` (if present) — loaded and merged field-by-field
   via the same logic as `apply_char_sheet` (`manager.py:181-187`); the
   `system` field is validated against `corpus.stats.system`.
3. `hard-state.json`'s `player` block (if the override is present and
   contains one) — overlaid field-by-field on top of the default.

The `--char-sheet` is *not* applied here; it is applied afterwards by
the existing `apply_char_sheet()`, which overlays on top of whatever
`load_all` produced.

If `corpus.stats is not None` and none of the sources supplies a player
block, raise `ValueError` ("scenario requires player data but none was
provided"). If `corpus.stats is None`, no player data is required and a
minimal `PlayerState` (location only) is returned.

**B3. `load_all()` — orchestrate generation, override, and the cascade**

Rewrite to:
1. Always load `corpus.json` and `soft-state.json`.
2. Resolve the player block via `_resolve_player_block()` (which itself
   reads `default-player.json` and any `hard-state.json` player block).
3. World state:
   - If `hard-state.json` exists: load it as the override; inject the
     resolved player block into it (replacing/merging its `player`) so
     the resulting `HardGameState` has the cascaded player.
   - If absent: call `_init_world_state_from_corpus()` and attach the
     resolved player block.
4. Reset once-reaction tracking (`reset_disabled_once()`).
5. Run the existing validation pipeline: `validate_cross_references()`,
   `_validate_stats_system()`, `_validate_player_stats()`,
   `_init_player_combat_defaults()`, `_init_contains_from_corpus()`.

`apply_char_sheet()` is unchanged; called externally (from the CLI) after
`load_all`, it overlays the supplied sheet on top of the already-resolved
player and re-validates.

**B4. Strengthen and migrate validation**

- **Migrate the flags check.** `validate_cross_references()` currently
  does `set(self.corpus.flags_declared)` (`manager.py:293-294`), which
  will raise `TypeError: unhashable type: 'dict'` once `flags_declared`
  is the mixed str/dict list. Change it to use the new property:
  `declared_set = set(self.corpus.flags_initial.keys())`.

- **Missing-`initial` warning.** When the world state is generated, emit
  `logging.warning()` for any state field that lacks an explicit
  `initial` and has no reserved-field default (it falls back to the type
  default, which may not be the author's intent). During initial
  development this may be promoted to an error in strict mode.

- **Flag cross-validation.** After `flags_initial` is populated, verify
  every flag referenced in any corpus condition string or `set_flag`
  result appears in `flags_initial` (or in the loaded override). Catches
  corpus authoring mistakes.

### Phase C: Schema and documentation

**C1. `schema/corpus.md`**

- Note that `initial` on `StateFieldSpec` (lines 593, 975) is now
  enforced by the Pydantic model.
- Document the fallback: "If `initial` is omitted, the field defaults to
  `false` (boolean), `0` (number), or `""` (string)."
- Update the reserved state fields table with default initial values
  (alive → true, fled → false, etc.).
- Document the new `flags_declared` mixed string/dict format.

**C2. `schema/hard-state.md`**

- Update the opening paragraph (lines 7-9): world state is generated
  from the corpus; `hard-state.json` is an optional override; the player
  block comes from `default-player.json` (or `--char-sheet`), not from
  generation.
- Mark the `player` block as **optional** in `hard-state.json` (present
  only when overriding the default player).
- Remove/update the line (165-166) about "If an initial value is not
  specified by the Corpus, it defaults to…" — this is now a corpus-spec
  concern, documented there.

**C3. `default-player.json` schema (new doc, or a section in `doc/player-stats.md`)**

- Document the format: identical to the character-sheet schema
  (`{"system": ..., "player": {...}}`).
- When it is required (iff `corpus.stats` present).
- The resolution cascade and overlay semantics (§2).
- That multi-level characters must carry explicit `max_hp`/`current_hp`/
  `ac`/`proficiency_bonus`/`save_proficiencies`.

**C4. `schema/scenario-generation.md`**

- **Step 5 (Build hard-state.json):** replace with **"Build
  `default-player.json`"**. The LLM extracts the player-character section
  from `scenario.md` (e.g. the "RPG Mechanics" block at
  `adventures/bag-of-holding/scenario.md:13-29`) into the char-sheet
  format. The LLM no longer produces a separate world-state file.
- Update Steps 2-4 to emphasise that `initial` on state fields directly
  determines starting world state, and should be set explicitly.
- Update the cross-validation checklist: remove hard-state.json-specific
  world-state checks (now generation guarantees); add a check that
  `default-player.json` is present when `corpus.stats` is set, and that
  its `system` matches.

**C5. `scripts/validate_adventure.py`**

- Do not require `hard-state.json` (lines 57-58, 62-63). Instead: load
  corpus + soft-state, generate world state, resolve the player block,
  then run all existing checks.
- Require `default-player.json` iff `corpus.stats` is present.
- Remove the `current_hp`-in-hard-state check (lines 234-239) — it is now
  a generation guarantee (`current_hp ← combat.hp`).
- Keep the orphaned-entity check (section 6).

**C6. `doc/player-stats.md`**

- Update "Player stats in hard state" (lines 53-55) to state that the
  default source of player stats at game start is `default-player.json`,
  overridable by `--char-sheet`, and that `hard_state.player.stats` is
  the runtime (engine-authoritative) copy.

### Phase D: Existing adventure migration

**D1. `adventures/bag-of-holding/default-player.json` (new)**

Create from the player block currently in `hard-state.json:2-19`,
carrying the **full** combat block (HP is not derivable for this level-4
character):

```json
{
  "system": "5e",
  "player": {
    "stats":       { "STR": 10, "DEX": 13, "CON": 12, "INT": 11, "WIS": 10, "CHA": 10 },
    "level":       4,
    "max_hp":      27,
    "current_hp":  27,
    "ac":          11,
    "proficiency_bonus": 2,
    "save_proficiencies": ["DEX", "INT"]
  }
}
```

**D2. Fix the `spider.current_hp` bug**

`corpus.json:176` has `spider.combat.hp = 14` and `scenario.md:348`
says "HP 14", but `hard-state.json:73` has `current_hp = 15`. The
hard-state value is wrong. With generation, `current_hp` is derived from
`combat.hp` (14) automatically. If `hard-state.json` is kept as an
override, correct the `15` → `14` there as well.

**D3. `adventures/bag-of-holding/corpus.json`**

Add `"initial": <value>` to every state field declaration that currently
lacks it:
- `"initial": true` — `alive` on player/stuck_fly/spider/korbar; `hidden`
  on stuck_fly/spider/padlock/giant_handkerchief/toenail_sword/secret_flap.
- `"initial": false` — `fled`, `following`, `convinced_spider_dead`,
  `examined`, `moved`.
- `"initial": 14` on `spider.current_hp` and `"initial": 29` on
  `korbar.current_hp` (matching their `combat.hp` values — the generator
  picks these up automatically, but explicit is better). Note: spider is
  **14**, not 15.
- `attitude` fields need no explicit `initial`; the generator derives them
  from `attitude_limits.initial` (spider −2, korbar 0, stuck_fly 0).

**D4. `adventures/bag-of-holding/hard-state.json`**

Strip the `player` block (now in `default-player.json`). The remaining
world-state entries become an optional override; once Phase B is stable,
the generated world state matches them, so the file can be deleted.

**D5. `adventures/bag-of-holding/soft-state.json`**

No changes (already starts empty).

### Phase E: Tests

**E1. New tests — `test_hard_state_generation.py`**

- Generated **world state** (`room_states`, `entity_states`, `flags`)
  matches the existing `hard-state.json` world state (modulo ordering).
  This is the acceptance test for generation. (The player block is *not*
  compared here — it comes from `default-player.json`.)
- Generated **player block** matches `default-player.json` after the
  cascade (no `--char-sheet`).
- Reserved-field defaults: alive → true, fled → false, etc.
- `attitude` picks up `attitude_limits.initial` when no explicit `initial`.
- `current_hp` picks up `combat.hp` (spider → 14).
- Type-default fallback for fields without `initial`.
- `flags_declared` with mixed strings and dicts; verify `flags_initial`.

**E2. New tests — `test_default_player.py`**

- Cascade: `default-player.json` base → `hard-state.json` player overlay
  → `--char-sheet` overlay (field-by-field, not replacement).
- A partial `--char-sheet` (e.g. only `inventory`) overlays
  `default-player.json` without wiping stats.
- Error when `corpus.stats` is present but no `default-player.json`,
  `hard-state.json` player block, or `--char-sheet` supplies player data.
- Stat-less adventure (`corpus.stats is None`): no `default-player.json`
  needed; game starts with a minimal player.

**E3. Existing test updates**

- `conftest.py` (line 45): keep the `fixtures/hard-state.json` fixture;
  add a fixture that generates world state from `fixtures/corpus.json`
  plus a `fixtures/default-player.json`.
- `test_state_manager.py`: add tests for `load_all()` with and without
  `hard-state.json`, and with and without `default-player.json`.
- `test_hard_state.py`: add model tests for `StateFieldDecl.initial`
  validation, including rejecting `bool` as a `number`.
- `test_encounters.py`, `test_resolver.py`, `test_followers.py`,
  `test_post_validate.py`, `test_equip_gear.py`: these load
  `fixtures/hard-state.json` directly. No changes — the fixture still
  works, and the generated state is tested separately.
- `validate_adventure.py` tests: verify the script works with corpus +
  soft-state + default-player only (no `hard-state.json`).

### Phase F: Cleanup (future)

- Once stable, delete `hard-state.json` from all adventures. Scaffolding
  for new adventures should produce `corpus.json` + `soft-state.json` +
  `default-player.json`, not `hard-state.json`.
- `schema/scenario-generation.md` Step 5 should instruct the LLM to
  verify `initial` values in the corpus and to produce
  `default-player.json`, not a world-state file.
- Now that file count holds at three, the soft-state open question
  (generate the trivially-empty `soft-state.json` too) becomes more
  attractive.

---

## Files touched

| File | Phase | Nature of change |
|------|-------|------------------|
| `mgmai/models/corpus.py` | A1-A3 | Add `StateFieldDecl.initial` (with bool/number guard), change `flags_declared` type + `flags_initial` property, add reserved-field constants |
| `mgmai/state/manager.py` | B1-B4 | Add `_init_world_state_from_corpus()` and `_resolve_player_block()`, rewrite `load_all()` for generation + cascade, migrate flags validation |
| `schema/corpus.md` | C1 | Document `initial`, fallbacks, reserved defaults, new `flags_declared` format |
| `schema/hard-state.md` | C2 | Update opening paragraph, mark `player` optional in override, remove stale default-typing line |
| `doc/player-stats.md` | C3/C6 | Document `default-player.json` format, cascade, and source-of-truth change |
| `schema/scenario-generation.md` | C4 | Replace Step 5 with `default-player.json` authoring; update cross-validation |
| `scripts/validate_adventure.py` | C5 | Don't require `hard-state.json`; require `default-player.json` iff stats present |
| `adventures/bag-of-holding/default-player.json` | D1 | New file: default player character |
| `adventures/bag-of-holding/corpus.json` | D3 | Add explicit `initial` to state_fields |
| `adventures/bag-of-holding/hard-state.json` | D2/D4 | Fix spider HP 15→14; strip player block (optional override) |
| `tests/test_hard_state_generation.py` | E1 | New test file |
| `tests/test_default_player.py` | E2 | New test file |
| `tests/test_hard_state.py` | E3 | Add `StateFieldDecl.initial` validation tests |
| `tests/test_state_manager.py` | E3 | Add generation / cascade load tests |
| `tests/conftest.py` | E3 | Add generation fixture |
| `plan.md` | — | This document |

## Open questions

- **Should the generator warn or error when a state field lacks an
  explicit `initial`?** A warning (via `logging`) is appropriate — the
  type-default fallback is always safe, but the author probably forgot.
  During initial development, make it an error in strict validation mode
  to catch gaps; demote to warning later.

- **Should `flags_declared` entries default to `false` or to an explicit
  value of `false`?** Both are equivalent. The mixed-list format where a
  plain string means `false` is more ergonomic for authors, since the
  vast majority of flags start `false`.

- **Should `default-player.json` declare `system`?** Yes — reusing the
  char-sheet schema means declaring `system` (validated against
  `corpus.stats.system`) for format uniformity and to share the loader/
  validator path. The alternative (inferring `system` from the corpus)
  saves one field but forks the format; not recommended.

- **Should we also programmatically generate `soft-state.json`?** Not in
  this plan. The initial soft state is trivially empty (all `{}`, `[]`,
  `null`). It could be eliminated in a follow-up; now that the required
  file count holds at three, the benefit is larger and this is the
  natural next step.
