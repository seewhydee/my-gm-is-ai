# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

- **Character sheet improvements**: LLM-aided prompt for character sheet generation; save character sheets in .config/mgmai.

## Combat & Stats Engine: Forward Plan

Driven by the updated `adventures/bag-of-holding/scenario.md` (which now
carries human-GM-style stat blocks for the spider, Korbar, and the player
defaults) and by a review of system-agnosticism.  This section records the
evaluation and the agreed course of action; **no code or schema is changed
until signed off.**

### Part A — Scenario-driven feature gaps

The scenario's new combat data, expressed as a human GM would:

- **Spider**: AC 14, HP 15, Bite +5 to hit, 1d4+3 piercing; *on hit, DC 11
  CON save or 1d8 poison (half on success)*.  Ability scores given
  (STR 14/DEX 16/CON 12/INT 7/WIS 11/CHA 4).
- **Korbar**: full Level-3 Fighter sheet (STR 15/DEX 10/CON 14/INT 10/WIS
  12/CHA 9, HP 29, AC 18, prof +2, saves STR/CON, unarmed damage 3).
- **Player defaults**: Level-4 Rogue (STR 10/DEX 13/CON 12/INT 11/WIS 10/CHA
  10, HP 27, AC 11, prof +2, saves DEX/INT).
- **Falling damage**: drop from Axe Head → lose 1d4 DEX, 1d4 CON, **3d6 HP**;
  from Axe Handle (Upper) → **2d6 HP**.

Mapping these onto the current engine (see `doc/combat.md`,
`mgmai/models/corpus.py:419`, `mgmai/engine/combat.py`):

| Scenario feature | Engine status | Decision |
|---|---|---|
| Spider AC/HP/atk/dmg/initiative | `CombatBlock` carries these as pre-computed values | **Use as-is.** Migrate the spider from one-shot `encounter_rules` to a `CombatBlock` at regeneration time. |
| On-hit **saving throw** (CON vs DC 11) | Not implemented anywhere | **Push forward.** Core new mechanic (see A1). |
| On-hit **secondary damage** (1d8 poison, half-on-save) | `CombatBlock.dmg` is a single expression | **Push forward** (A1). |
| Player **save proficiencies** (DEX, INT) | Not modelled | **Push forward** (A2). |
| **Out-of-combat HP damage** (3d6 / 2d6 falling) | `current_hp` is `None` until combat start (`combat.py:392`); `Result` has no HP field (`corpus.py:99`) | **Push forward** (A3). |
| Flat (non-dice) damage ("3") | `parse_damage_dice` regex requires `NdM` (`combat.py:49`) | **Push forward** (trivial, A4). |
| NPC full ability scores | Unused (atk/dmg/initiative are pre-computed) | **Leave out** for now. Only needed if NPCs must make saves; the spider's poison is a *player* save. Revisit if Korbar moves to HP combat. |
| Damage *types* (piercing/poison) | Ignored (HP is a single pool) | **Leave out** mechanically; carry the label for narration only. No resistance/vulnerability in scenario. |
| Conditions (poisoned status) | None | **Leave out.** Scenario poison is one-shot damage, not ongoing. |
| Korbar in HP combat | Currently handled by `behavior.encounter_rules` (death/flee) | **Leave on encounter rules.** She is not a real fight; her stat block stays narrative colour. Revisit later. |
| Healing, death saves, multi-attack, NPC-vs-NPC, NPC-initiated flee | Listed as Phase-1 limitations | **Leave out** (unchanged). |

**Push-forward work items (Part A):**

- **A1 — On-hit effects with saving throws.** Add an optional
  `on_hit_effects: list[OnHitEffect]` to `CombatBlock`.  An `OnHitEffect`
  declares `{ save: {stat, dc}, damage: <expr>, on_save: "half"|"none"|"full", type?: str }`.
  After a hit, the combat loop iterates effects; for each, it asks the
  active resolution system to resolve the save and compute damage (full on
  fail, half/none on success).  This realises the spider's poison bite and
  is the single highest-value gap.
- **A2 — Player saving-throw proficiencies.** Add an optional
  `save_proficiencies: list[str]` (e.g. `["DEX","INT"]`) to `PlayerState`.
  Save bonus = ability modifier (+ proficiency if listed).  sourced from
  the character sheet / scenario defaults.
- **A3 — Out-of-combat HP damage and HP initialisation.** (1) Initialise
  `current_hp`/`max_hp` at game start (not only in `enter_combat`), using
  the character sheet values (scenario defaults: HP 27). (2) Add a
  `player_damage` field to `Result` (a dice expression or int) that the
  resolver rolls and emits as `HardStateChanges.player_hp_delta`, so
  `on_traverse`/interaction results can deal HP damage that persists into
  later combat.  Wire the falling-drop `on_traverse` blocks to use it.
- **A4 — Flat damage expressions.** Extend `parse_damage_dice` to accept a
  bare integer (`"3"`) in addition to `NdM[+/-k]`.  Low-risk, also aids
  portability (GURPS damage is often flat).

### Part B — System-agnosticism evaluation

**Verdict: the abstraction exists in intent but is shallow and leaky.**
The project declares the goal (`doc/combat.md:3-5`,
`doc/player-stats.md:86-95`) and has a `StatsBlock.system` field plus a
`compute_modifier(value, system)` dispatch (`stat_checks.py:45`).  But the
seam stops there; 5e mechanics are inlined throughout and there is no
system object to swap.

Specific findings:

1. **No system object.** There is no `ResolutionSystem` protocol bundling
   the system-specific operations (modifier, check, initiative, attack,
   crit, AC, HP, saving throw).  Instead 5e logic is free functions plus
   inline `if res_system != "5e": return` guards that *fail closed* in 3
   places (`resolver.py:834`, `resolver.py:897`, `resolver.py:1052`,
   `encounters.py:351`).
2. **Triplicated check resolution.** The same d20+mod-vs-DC block (compute
   modifier, read advantage/disadvantage from `resolution_params["5e"]`,
   roll, compare, build roll dict) is copy-pasted across
   `_resolve_stat_check` (`resolver.py:1027`), `_resolve_stat_check_chain`
   (`resolver.py:810`), `_resolve_traversal_check` (`resolver.py:878`), and
   `_resolve_encounter_stat_check` (`encounters.py:330`).  Adding a system
   means editing all four.
3. **Combat engine is not abstracted at all.** `combat.py` hardcodes 5e
   rules and never consults `corpus.stats.system`: initiative = d20+DEX
   (`combat.py:292`); player attack = d20+STR+prof (`combat.py:504`);
   AC = 10+DEX (`combat.py:226,259`); max HP = 8+CON (`combat.py:268`);
   crits on nat 1/20 with doubled dice (`combat.py:336-338,507-508`).
   `StatsBlock.system` is effectively dead for combat.
4. **Terminology leakage.** `roll_d20`, `ac` (Armor Class),
   `proficiency_bonus`, and bare `STR`/`DEX`/`CON` keys are baked into
   formulas.  GURPS has no AC or proficiency; Pathfinder shares d20 but
   differs in crit/attack details.  `PlayerState` carries 5e-specific
   fields (`proficiency_bonus`, `ac`, `level`) with no system home.
5. **`CombatBlock` is the one bright spot.** Pre-computed `hp/ac/atk/dmg`
   values are *more* portable than derived ones — a Pathfinder or GURPS
   author can supply the same shape.  The portability is undermined only at
   the *resolution* layer (d20-vs-AC), which is exactly the seam to fix.

**Abstraction work items (Part B):**

- **B1 — Introduce a `ResolutionSystem` protocol** **[DONE]** (new module
  `mgmai/engine/systems/base.py`) defining the system-specific surface:
  `compute_modifier(stat)`, `roll_die(faces, adv, disadv)`,
  `roll_check(stat, stat_value, dc, flat_modifier, params) -> CheckResult`,
  `roll_initiative(modifier) -> int`, `is_critical(roll)`/`is_fumble(roll)`,
  `roll_damage(expr, critical)`, `base_ac(dex_value)`, `base_max_hp(con_value)`,
  `resolve_save(...) -> SaveResult`, plus `unarmed_damage`/
  `default_weapon_damage` class attrs.  The combat *loop* (initiative
  order, rounds, HP bookkeeping, death) stays generic; only die-rolling
  and hit/damage/save maths move into the system.
  > **Deviation from original wording:** instead of a monolithic
  > `resolve_attack(attacker, target, ctx)`, the *primitives* above were
  > extracted and the attack *orchestration* (log entries, HP deltas,
  > death checks) stays in the combat loop, which calls the primitives.
  > This satisfies the stated principle ("only maths moves into the
  > system") and is sufficient for the **d20 family** (5e, Pathfinder, d20
  > Modern): they share the attack-roll-vs-AC model and differ only in
  > crit thresholds, modifiers, and dice.  Systems with a *fundamentally
  > different* attack model (GURPS active defence, no AC) will need a
  > follow-up `resolve_attack` extraction — tracked as **B6** below.
- **B2 — Implement `FiveESystem`** **[DONE]** by relocating the existing
  5e logic out of `combat.py`, `resolver.py`, `encounters.py`, and
  `stat_checks.py` into `mgmai/engine/systems/five_e.py`.  Pure move, no
  behaviour change; all 921 pre-existing tests pass unchanged.
- **B3 — Registry + single source.** **[DONE]** `get_system(name)` /
  `get_system_for_corpus(corpus)` (default `"5e"`) in
  `mgmai/engine/systems/__init__.py`, with `register_system(name, cls)`
  as the extension hook.  Every `if res_system != "5e"` guard and every
  direct `compute_5e_modifier`/`roll_d20` engine call site is gone; the
  four-way check-resolution triplication is collapsed to
  `system.roll_check`.  `stat_checks.py` retains `roll_d20` /
  `compute_5e_modifier` / `compute_modifier` as thin backward-compat
  shims (still used by `assembler.py`, `display.py`, and tests).
- **B4 — Generalise `PlayerState` combat fields.** [PENDING] Keep
  `proficiency_bonus`/`ac`/`level` as optional generic slots but document
  that their *interpretation* belongs to the active system; add
  `save_proficiencies` (A2).  Future systems may ignore or reinterpret
  them without surgery to the loop.
- **B5 — Schema door-crack.** [PENDING, now trivial] Relax
  `StatsBlock.system` validation (`corpus.py:437-442`) from a hard
  `{"5e"}` allow-list to "registered system or warn".  With the registry
  in place this is a one-line change plus a registered class.
- **B6 — (New) `resolve_attack` extraction.** [DEFERRED] Only needed if a
  target system's attack model is not roll-vs-AC (e.g. GURPS active
  defence).  Not required for any d20-family system or for the scenario
  work in Part A.

### Sequencing (recommended)

1. **B1–B3 first** (pure refactor): introduce the system object, move 5e
   logic behind it, de-duplicate check resolution.  No behaviour change;
   de-risks everything that follows and delivers the "hooks" the project
   wants before more 5e features accrete.  **— DONE.**
2. **A2 + A4** (small, isolated): save proficiencies on `PlayerState`;
   flat-damage parser (`parse_damage_dice` now lives in
   `mgmai/engine/systems/dice.py`).
3. **A1** (on-hit saves): built *on top of* the new system's
   `resolve_save` (already implemented on `FiveESystem`, so no further
   abstraction work is needed — just wire it into the combat loop after a
   hit), exercising the abstraction with the spider's poison.
4. **A3** (out-of-combat HP): independent of combat loop; can land in
   parallel with A1.
5. Regenerate `bag-of-holding` JSON from `scenario.md` (spider →
   `CombatBlock` + `on_hit_effects`; falling `on_traverse` →
   `player_damage`) once the engine supports it.

After step 1, adding any **d20-family** system (Pathfinder, d20 Modern)
is "implement a `ResolutionSystem` subclass + `register_system`" — no
surgery to the combat loop or resolvers.  Non-d20 systems (GURPS) need
B6 first.

### Implementation notes & amendments (B1-B3 complete)

- **Delivered:** new package `mgmai/engine/systems/` (`base.py`,
  `five_e.py`, `dice.py`, `__init__.py` registry); `combat.py`,
  `resolver.py`, `encounters.py`, `stat_checks.py` rewired to call the
  active system; `doc/combat.md`, `doc/player-stats.md`,
  `doc/intro.md` updated; new test module `tests/test_systems.py`
  (37 tests covering the registry, `FiveESystem` maths, `CheckResult`/
  `SaveResult` shapes, and the `register_system` extension hook).
  Full suite: 958 passed.
- **`resolve_save` hook is live.** `FiveESystem.resolve_save` is
  implemented (d20 + stat mod + proficiency-if-proficient vs DC, with
  adv/disadv) but not yet invoked by the combat loop.  A1 needs only the
  `on_hit_effects` data model + a loop call — no new abstraction work.
- **Test-anchor detail.** Tests monkeypatch
  `mgmai.engine.stat_checks.random.randint`; because `random` is a shared
  module, that patch steers the system's dice too.  `stat_checks.py`
  therefore retains `import random` (marked `# noqa: F401`) as an anchor.
  Do not delete it.  All dice rolling in `five_e.py` deliberately uses the
  shared `random` module rather than a private RNG instance.
- **Optional cleanup (not required):** migrate `assembler.py` and
  `display.py` from `compute_modifier(v, stats_block.system)` to
  `get_system_for_corpus(corpus).compute_modifier(v)`, and eventually
  retire the `stat_checks` shims once all callers (incl. tests) move.
  Pure tidiness; no behaviour change.
