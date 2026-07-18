# Combat Expansion Plan: Party Combat, Richer Stats, Abilities

This plan supersedes the previous contents of `plan.md` (a completed
soft-state revision).  It lays out the phased expansion of the combat
subsystem in three directions:

1. **Richer player combat stats** — a digestible subset of D&D 5e that
   makes combat mechanically interesting, *not* the whole rulebook.
2. **Abilities in combat** — usable by the player and by NPCs.
3. **Allied NPCs (followers) in combat** — enabling party-vs-mobs battles.

## Constraints and design principles

- **No new LLM calls.**  The per-turn budget stays at exactly two calls
  (Call 1 ruling, Call 2 prose).  All NPC combat decisions are made by a
  deterministic, rule-of-thumb **combat AI in the engine**, configured
  per-NPC through the corpus.  (The alternative — having Call 1 or Call 2
  pick NPC actions — was rejected: it is nondeterministic, hard to test,
  inflates prompts, and contradicts the "engine is the source of truth for
  rules" architecture.  Call 2 already narrates everything the engine
  decides, so narration quality does not suffer.)
- **Digestible chunks.**  Each phase below is independently mergeable with
  the full test suite green.  Phase 3 is further split into independent
  sub-chunks.
- **Backward compatibility.**  All new corpus/state fields are optional
  with defaults.  Existing adventures and save files load unchanged, and
  solo player-vs-mobs combat behaves exactly as today (asserted by tests).
- **System-agnostic engine preserved.**  All 5e-specific maths stay behind
  the `ResolutionSystem` interface (`mgmai/engine/systems/`); the combat
  loop orchestrates state and turns only.

## Deliberate 5e simplifications

These hold for all phases and are documented in `doc/combat.md` as we go:

- No positioning, range, cover, or tactical maps (a "ranged" weapon only
  changes which ability score is used).
- No bonus actions, reactions, or opportunity attacks.
- Conditions are combat-scoped (cleared when combat ends).
- Prone combatants automatically stand at the start of their turn.
- Player at 0 HP = game over (no death saving throws yet); allies die at
  0 HP (no unconscious state).
- NPCs have no ability scores; NPC saving throws against abilities use a
  flat `save_bonus` from their combat block.

## Current state (verified inventory)

- `mgmai/engine/combat.py` — combat loop: `enter_combat`,
  `resolve_combat_turn`, `resolve_combat_enemies`, `roll_initiative`.
  Enemies always attack the player; victory checked only after the
  player's action.
- `mgmai/engine/systems/base.py` / `five_e.py` — `ResolutionSystem` ABC
  and the 5e implementation.  `resolve_npc_attack` is hardwired to target
  the player (`player_hp_delta`).
- `mgmai/models/combat.py` — `CombatState` (`combatants`,
  `initiative_order`, `round_number`, `log`); no side/allies concept.
- `mgmai/models/corpus.py` — `CombatBlock` (hp/ac/atk/dmg/initiative_mod/
  flee_dc/on_hit_effects), `EquipBlock`, `StatsBlock`.
- `mgmai/models/actions.py` — `CombatAction` with
  `combat_action: "attack"` only.
- `mgmai/engine/utils.py` — `get_following_npc_ids`; followers already
  exist (dialogue NPCs with `following: true`) and are already excluded
  from enemy `combat_group` expansion in `resolve_combat_enemies`.
- `mgmai/context/assembler.py` — `_build_combat_state` briefing;
  `mgmai/engine/stat_checks.py` — `format_combat_prefix` (already generic
  for npc→npc lines); `mgmai/game/display.py` — combat status panel.
- Equipment system (weapon `damage_expr`/`hit_bonus`, armour
  `ac_override`/`ac_bonus`, `stat_effects`) already exists; see
  `doc/gear.md`.

---

## Phase 1 — Combat core generalization (behavior-preserving refactor)

**Goal.**  Restructure the loop so any NPC actor can attack any
combatant, and end-of-combat conditions are checked after every action —
with zero observable behavior change for solo player-vs-mobs.  This is
the foundation for Phases 2 and 4 and is cheapest while the combat
surface is small.

**Changes.**

- `mgmai/engine/systems/base.py`
  - `ResolutionSystem.resolve_npc_attack(npc_id, hard, corpus, target_id,
    target_ac, round_number)` — new `target_id` parameter replacing the
    hardwired player target.
  - `NPCAttackResult`: rename `player_hp_delta` → `target_hp_delta`; add
    `target_died: bool`; drop `game_over` (the engine decides: game over
    iff `target_id == "player"` and the player is dead).
- `mgmai/engine/systems/five_e.py` — implement the new signature; read
  target HP from player state when `target_id == "player"`, else from
  `entity_states[target_id]["current_hp"]`.  Log-entry shapes unchanged.
- `mgmai/engine/combat.py`
  - `CombatState` gains `allies: list[str] = []` (populated in Phase 2).
  - New `_side_of(combat, cid) -> "player" | "party" | "enemy"`.
  - New `_resolve_npc_turn(actor_id, ...)` helper: choose target via
    `_choose_target` (hardwired to `"player"` in this phase), resolve the
    attack, apply the HP delta to the right place (`player_hp_delta` vs
    `entity_state_changes`), append death entries, resolve on-hit effects
    only when the target is the player (they reference player stats).
  - `enter_combat` and `resolve_combat_turn` use the helper for every NPC
    actor; after **every** NPC action, check victory (no living enemies)
    and player death, and stop processing on either.  (Today victory is
    checked only after the player's action — equivalent without allies,
    since only the player can kill, but the generalized check is required
    in Phase 2 and harmless now.)
- Callers updated for the renamed result field: `mgmai/engine/resolver.py`,
  `mgmai/engine/engine.py`, `tests/test_combat.py`, `tests/test_systems.py`.

**Tests.**  Full suite green with no behavior changes except the field
rename; new unit tests for `resolve_npc_attack` against an NPC target
(direct system calls).

**Docs.**  `doc/combat.md` internals note only; no schema changes.

---

## Phase 2 — Allied NPCs (party combat) + combat AI

**Goal.**  Followers with combat blocks automatically fight on the
player's side; all NPCs (both sides) act via rule-of-thumb AI.

**Corpus.**

- `CombatBlock` gains an optional `ai` block (`CombatAIBlock`):
  - `targeting`: `"last_attacker"` (default), `"player"`, `"lowest_hp"`,
    `"random"`.
  - `flee_below_hp_pct`: int 1–99, optional; default = never flee.
- Validators for the new literals; `scripts/validate_adventure.py` checks.

**State.**

- `CombatState.allies` populated at entry; new
  `last_attacker: dict[str, str]` (target → most recent attacker, updated
  on every hit) and `player_last_target: str | None`.

**Engine (`mgmai/engine/combat.py`).**

- `resolve_combat_allies(hard, corpus)`: alive followers (via
  `get_following_npc_ids`) that have a `combat` block.
- `enter_combat` auto-includes allies: initiative rolls for them too;
  `combatants = ["player"] + allies + enemies`; pre-player NPC turns use
  `_resolve_npc_turn`.
- Target selection:
  - **Enemies**: per `ai.targeting` among living party members (player +
    allies).  Default `last_attacker` falls back to the player.  In solo
    play the last attacker is always the player, so default behavior is
    identical to today; in party combat mobs naturally retaliate against
    whoever hit them last.
  - **Allies**: `ai.targeting` may override; default order: the player's
    most recent living target → own last attacker → lowest-HP living
    enemy.
- **NPC flee**: on its turn, if `flee_below_hp_pct` is set and current
  HP% is below it, the NPC leaves combat: removed from combatants and
  initiative order, entity state `fled: true` set (adventures can react
  to it, e.g. the existing `spider_fled` pattern), `action: "flee"` log
  entry.  If it was the last living enemy, combat ends (victory).
- **Ally death**: `alive: false`, removed from combatants/initiative/
  allies; a dead follower automatically stops following
  (`get_following_npc_ids` excludes `alive: false`).
- **Player flee**: unchanged mechanics; on success combat ends for the
  whole party — followers withdraw with the player (consistent with
  follower room-travel semantics).
- The player may not target same-side combatants (engine error).
  Attacking a follower still works exactly as today — as a combat-entry
  seed, not mid-combat.
- On-hit effects resolve only against the player (Phase 1 decision).

**Briefing / templates / display.**

- `CombatBriefing` combatant entries gain `side` (`"party"` / `"enemy"`);
  `assembler._build_combat_state` populates it from `combat.allies`.
- `ruling.j2` combat section: allies act autonomously under engine
  control; valid `combat` targets are enemy combatants only.
- `format_combat_prefix`: add the NPC-flee line; npc→npc attack/death
  lines already work (verified generic).
- `display.py` combat panel: group HP rows under "Party" and "Enemies".

**Optional stretch (only if cheap):** a `combat_action: "command"` action
(`target` = ally, `order` = attack-target / hold) stored as
`CombatState.ally_orders` and consulted by ally AI before defaults.  Uses
the existing Call 1; no new LLM calls.  Marked optional — the default AI
already provides reasonable ally behavior.

**Tests** (`tests/test_combat.py`, `tests/test_followers.py`).

- Allies auto-join; initiative order includes them.
- Ally kills the last enemy → combat ends immediately (victory) mid
  NPC-turn sequence.
- Enemy targeting rules: `last_attacker` (mob retaliates on the ally that
  hit it), `lowest_hp`, `random` (seeded `random.random`), explicit
  `"player"`.
- NPC flee at threshold; last-enemy flee ends combat; `fled` state set.
- Ally death: `alive: false`, removed everywhere, stops following.
- Player flee with allies ends combat; allies appear in the new room.
- Save/load round-trip mid-combat with allies.
- Solo-combat regression: no allies → behavior byte-identical to Phase 1.

**Docs.**  `schema/corpus.md` (`ai` block), `schema/hard-state.md`
(`CombatState.allies`, `last_attacker`), `doc/combat.md` (party combat
chapter; remove "NPC-vs-NPC combat" and "NPC-initiated fleeing" from the
limitations list; document the enemy-targeting default).

---

## Phase 3 — Richer player combat stats (independent sub-chunks)

Each sub-chunk is independently mergeable.  Suggested order:
3a → 3b → 3c → 3d → 3e (3c feeds Phase 4).

### 3a — Weapon properties (finesse, ranged)

- `EquipBlock` accepts extra key `properties: list[str]`; the 5e system
  recognizes `finesse` and `ranged`.
- `FiveESystem.compute_player_attack_bonus` /
  `compute_player_damage_expr`: finesse → use max(STR, DEX) modifier;
  ranged → DEX modifier.  Unarmed/legacy weapons unchanged (STR).
- No range/position mechanics (documented limitation).
- Tests; `doc/gear.md`, `schema/corpus.md` updates.

### 3b — Damage types, resistance, vulnerability, immunity

- Damage-type vocabulary (5e): acid, bludgeoning, cold, fire, force,
  lightning, necrotic, piercing, poison, radiant, slashing, thunder.
- `EquipBlock.damage_type: str` (extra, 5e-recognized); `CombatBlock`
  gains `dmg_type: str = ""`, `resistances`, `vulnerabilities`,
  `immunities` (`list[str]`).
- Resolution (inside `ResolutionSystem`, new `apply_damage_modifiers`
  hook): immunity → 0, resistance → half rounded down, vulnerability →
  double.  Applied to NPC targets of player attacks; player-side
  application is a no-op hook for now (player resistances are a future
  chunk).
- Log entries and combat prefix annotate `(resisted)` / `(vulnerable)` /
  `(immune)`.
- `validate_adventure.py` checks damage-type vocabulary.
- Tests; `schema/corpus.md`, `doc/combat.md` updates.

### 3c — Conditions: poisoned, stunned, prone

- Player: `PlayerState.conditions: dict[str, int]` (condition id →
  rounds remaining).  NPCs: same shape in
  `entity_states[id]["conditions"]`.  Combat-scoped: cleared when combat
  ends (documented simplification).
- Effects (per SRD 5.2.1, simplified; enforced inside the resolution
  system, which already supports advantage/disadvantage):
  - **poisoned** — disadvantage on own attack rolls and ability checks.
  - **stunned** — turn skipped; attack rolls against have advantage.
  - **prone** — disadvantage on own attack rolls; attack rolls against
    have advantage; automatically stands at the start of its turn.
- Processing: at the start of each combatant's turn, tick durations and
  drop expired conditions; stunned skips the action.
- Application path: combat-safe `Result` gains
  `apply_condition: {id, rounds}` (usable from `on_hit_effects` now and
  abilities in Phase 4); the `CombatBlock` on-hit validator allows it.
  Player ability checks made in combat pass disadvantage when poisoned.
- Tests; `schema/corpus.md`, `schema/hard-state.md`, `doc/combat.md`
  updates.

### 3d — Consumable items + `use_item` combat action

- `ConsumableBlock` on item entities: `heal: str` (dice expression),
  `cure_conditions: list[str] = []`, `destroy: bool = true`.
- `CombatAction.combat_action` extended to `"attack" | "use_item"`;
  `target` is an inventory item id and the player's action is consumed.
  Healing applies as positive `player_hp_delta`, clamped to `max_hp`.
  Out-of-combat use is deferred (authored interactions already cover it).
- Combat briefing gains `usable_items` (id, name, effect summary) so
  Call 1 can map "I drink the potion".
- `ruling.j2` / `prose.j2` updated; prefix line ("You use X: healed N.").
- Tests; `schema/corpus.md`, `schema/actions.md`, `doc/combat.md`
  updates.

### 3e — NPC attack definitions & multiattack

Not a flat "number of attacks": real monsters have distinct attack
options (bite/claw/claw with different stats), so attacks are defined
individually.

- `CombatBlock.attacks: list[NPCAttackDef]` — named attack options, each
  `{id, name?, atk, dmg, on_hit_effects?}`.  When `attacks` is absent the
  NPC has one implicit "basic attack" built from the block-level `atk` /
  `dmg` / `on_hit_effects` (existing blocks behave unchanged — the
  shorthand is kept deliberately, since simple mobs need no more).  When
  `attacks` is present, block-level `atk` becomes optional and
  block-level `on_hit_effects` is forbidden (validation error): each
  attack carries its own.
- `CombatBlock.multiattack: list[str]` — the ordered attack ids the NPC
  performs each turn; ids may repeat (`["bite", "claw", "claw"]`).
  Absent → a single attack per turn: the first entry of `attacks`, else
  the basic attack.
- Resolution: `_resolve_npc_turn` iterates the turn's attack sequence and
  passes the chosen attack definition (bonus, damage expr, on-hit
  effects) into `ResolutionSystem.resolve_npc_attack`, which no longer
  reads `CombatBlock.atk` / `.dmg` directly.  If the target dies
  mid-sequence the remaining attacks are lost (no target splitting this
  phase).  Attack selection beyond the fixed `multiattack` order (e.g.
  conditional choice) is left to Phase 4's `ai.ability_rules`.
- `CombatLogEntry` gains an optional `attack_id` so the combat prefix
  and prose can name the attack ("Spider bites you").
- Validation: `multiattack` ids must resolve to a defined attack; damage
  expressions parse; `attacks` and block-level `on_hit_effects` are
  mutually exclusive.
- Tests: sequence resolves each attack in order with its own bonus/dice;
  sequence stops on target death; per-attack on-hit effects fire;
  prefix names the attack.

---

## Phase 4 — Abilities in combat

**Goal.**  Named, limited-use abilities (spells, class features, monster
powers) usable by the player and by NPCs, reusing the attack/save
pipelines built above.

**Corpus.**

- Top-level `abilities: dict[str, Ability]` on `ModuleCorpus`:
  - `name`, `description`.
  - `target`: `"self" | "ally" | "enemy"`.
  - `uses_per_combat: int` (`-1` = unlimited, cantrip-style).
  - Exactly one effect:
    - `attack`: `{stat, proficient: bool, damage, damage_type?,
      on_hit?: CheckResolution}` — rolled like a weapon attack using the
      named ability score.
    - `save`: `{stat, dc, damage, damage_type?, half_on_success: bool,
      apply_condition_on_failure?: {id, rounds}}`.
    - `heal`: dice expression.
- `PlayerState.abilities: list[str]` — ids the player knows, set via
  character sheet / `default-player.json`.
- `CombatBlock.abilities: list[str]` — ids the NPC knows; per-ability AI
  hints in `ai.ability_rules`:
  `{ability_id: {cooldown_rounds: int, use_below_own_hp_pct?: int}}`.
- `CombatBlock.save_bonus: int = 0` — flat NPC save modifier against
  `save` abilities (NPCs have no ability scores; documented
  simplification).
- `CombatState` gains `ability_uses: dict[str, dict[str, int]]` and
  `npc_cooldowns: dict[str, dict[str, int]]` (both die with combat, which
  matches `uses_per_combat` semantics).

**Engine.**

- `CombatAction.combat_action` += `"use_ability"`; new optional
  `ability_id` field; `target` validated against the ability's
  `target` kind (self / party combatant / enemy combatant).
- Attack abilities reuse the attack pipeline (stat modifier + proficiency
  bonus if `proficient`, crit rules, resistance application).
- Save abilities reuse the save/CheckResolution pipeline (half damage on
  success, condition on failure).
- Heals clamp to max HP; uses decrement; exhausted uses → action rejected
  with an engine error.
- NPC AI: on its turn, evaluate known abilities in listed order — first
  one that is usable (uses left, cooldown expired, HP condition met) is
  used; otherwise basic attack.  Cooldowns tick at round end.  Ally NPCs
  with `heal` target the most-injured living party member (including
  self) and skip healing when nobody is hurt.
- Buff / temporary-modifier abilities are **deferred** (they need
  temp-effect tracking machinery); listed under non-goals.

**Briefing / templates.**

- Combat briefing gains `abilities` (id, name, description, target kind,
  uses remaining, plain-English effect summary) and exposes
  `combatants[].conditions`.
- `ruling.j2`: `use_ability` syntax and targeting rules; `prose.j2`:
  narrate ability outcomes; prefix lines for ability/save results.

**Tests.**  Attack ability hit/crit/miss; save ability with
half-on-success and condition-on-failure; heal self/ally with clamping;
uses exhaustion error; NPC cooldown cycling; NPC AI ability preference
and attack fallback; validation errors (unknown ability id, wrong target
side); Call 1 JSON parse round-trip for `use_ability`.

**Validation.**  `validate_adventure.py`: referenced ability ids exist,
exactly-one-effect shape, target vocabulary, cooldown/uses sanity.

**Docs.**  `schema/corpus.md` (`Ability`, `CombatBlock.abilities`,
`ai.ability_rules`, `save_bonus`), `schema/actions.md` (`use_ability`),
`schema/hard-state.md` (`ability_uses`), `doc/combat.md` (abilities
chapter), `doc/player-stats.md` (character-sheet `abilities` field).

---

## Cross-cutting concerns

- **Save compatibility.**  New state fields all default empty; old
  autosaves load without migration.  Mid-combat saves from older versions
  have `allies: []` — correct, since old saves can only be in solo
  combat.
- **Sample adventure.**  After Phase 2: give one `bag-of-holding`
  follower a combat block + `ai` hints to demo party combat.  After
  3b/3d: annotate spiders (poison damage type) and a healing potion
  (`ConsumableBlock`).  Small, additive diffs.
- **Module layout.**  No new Python modules are planned; if Phase 2
  makes `combat.py` unwieldy, the AI target/ability selection may move to
  `mgmai/engine/combat_ai.py` (decision deferred to implementation).
  Update `doc/intro.md`'s directory listing if so.
- **Testing conventions.**  Existing monkeypatching of `random.randint` /
  `random.random` continues to steer all rolls; each phase ends with the
  full `pytest` suite green.

## Explicit non-goals (future phases)

- Positioning, range, cover, tactical maps.
- Reactions, opportunity attacks, bonus actions.
- Death saving throws; unconscious-but-stable players/allies.
- Buff / temporary-modifier abilities; AoE abilities.
- Player-side damage resistances; full NPC ability scores.
- Rest, leveling, per-day ability uses (uses are per-combat only).
- Non-follower allies; ally defection when attacked mid-combat;
  multi-PC parties.
- LLM-chosen NPC actions (rejected per the design principles above).

## Execution checklist

- [x] Phase 1 — combat core generalization (refactor, behavior-preserving)
- [x] Phase 2 — allied NPCs + combat AI
- [ ] Phase 3a — weapon properties (finesse, ranged)
- [ ] Phase 3b — damage types / resistance / vulnerability / immunity
- [ ] Phase 3c — conditions (poisoned, stunned, prone)
- [ ] Phase 3d — consumables + `use_item` in combat
- [ ] Phase 3e — NPC attack definitions & multiattack
- [ ] Phase 4 — abilities in combat
