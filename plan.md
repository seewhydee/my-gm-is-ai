# 5e Implementation Status & SRD Data Pack Plan

This file tracks (a) which parts of D&D 5e (per the CC-BY SRD 5.2.1 in
`temp/`) are implemented, and (b) the design for bundling chunky SRD
content (spells, gear, monsters, conditions) with the engine so that
adventure and character-sheet authors don't redefine it per-corpus.

The previous plan (first-class status effects) is complete; see git
history for the archived text.

---

## Part 1 — 5e implementation checklist

### Implemented

- [x] Ability scores (six, free-form keys on `PlayerState.stats`,
      default 10) and modifiers `(score-10)//2` —
      `mgmai/engine/systems/five_e.py:123`
- [x] Proficiency bonus (`PlayerState.proficiency_bonus`, default 2)
- [x] All 18 SRD skills → governing abilities, `SKILL_ABILITIES`
      (`five_e.py:64-83`); proficiency via `skill_proficiencies`
- [x] Ability checks (d20 + mod + flat modifier vs DC, success on `>=`)
- [x] Saving throws (as `StatCheck` with `save: true`; proficiency via
      `save_proficiencies`); NPC flat saves via `save_bonus`
- [x] Attack rolls (player: d20 + ability mod + proficiency +
      `hit_bonus`; NPC: precomputed `CombatBlock.atk` /
      `NPCAttackDef.atk`)
- [x] Advantage/disadvantage (boolean OR; sources: authored check
      extras, status-effect `system_effects`)
- [x] Damage rolls (`NdM±k` and flat, `half(...)` wrapper), critical
      hits (nat 20 auto-hit, doubled dice) and fumbles
- [x] All 12 SRD damage types; resistance/immunity/vulnerability for
      NPC targets
- [x] Armor class (player: explicit / `10 + DEX` base, `ac_override` +
      `ac_bonus` from gear; NPC: flat `CombatBlock.ac`)
- [x] Hit points and healing (consumables, heal abilities,
      `Result.player_heal`), clamped to max HP
- [x] Initiative (d20 + DEX mod / `initiative_mod`, tie-breaks)
- [x] Fleeing (player DEX check vs max enemy `flee_dc`; NPC flee via
      `ai.flee_below_hp_pct`)
- [x] Weapon properties: `finesse`, `ranged` (affect ability score
      only — no range semantics)
- [x] Multiattack (NPC named attacks sequenced per turn)
- [x] First-class status effects: corpus-definable, three built-ins
      (`poisoned`, `stunned`, `prone`), combat/persistent scopes,
      durations, ticking, `skip_turn`, query domain, events
- [x] Corpus `abilities` block (attack/save/heal with ability scores,
      DCs, damage types, `uses_per_combat`) — spell-*like*, usable by
      player and NPCs
- [x] Combat loop: initiative order, multi-enemy encounters, party
      combat (follower allies), deterministic NPC AI (targeting,
      ability rules, healer logic), death of NPCs
- [x] Equipment: `EquipBlock` (damage, hit bonus, AC override/bonus,
      stat effects), equip/unequip with slot conflicts, consumables
      (`heal`, `cure_status_effects`), improvised weapons

### Partially implemented (known gaps)

- [~] **Player level** — `PlayerState.level` exists but is inert:
      proficiency bonus and max HP are not derived from it (HP default
      bakes in "level 1, d8 hit die"; proficiency defaults to 2)
- [~] **Weapon properties** — only `finesse`/`ranged`; no
      versatile/two-handed damage dice, thrown, ammunition, loading,
      light. `two_handed` is only an equip-conflict convention
- [~] **Damage mitigation** — NPCs only; player targets have none
      (`five_e.py:94-97`)
- [~] **Player 0 HP** — instant death via `player.died` event; no
      unconsciousness, death saving throws, or stabilization
- [~] **Conditions** — 3 of ~15 SRD conditions built in; the
      machinery supports the rest, data and a few `system_effects`
      keys are missing
- [~] **Checks** — single-roll vs DC only; no passive scores,
      contested checks, group checks; NPCs have no ability scores and
      never make checks

### Not implemented

- [ ] **Spellcasting** — no spell slots, spell levels, spell lists,
      casting ability, components, concentration, spell attack/save DC
      derivation (8 + prof + mod). `uses_per_combat` is the only
      resource model
- [ ] **Rests** — no short/long rest; no hit dice; per-rest ability
      recharge
- [ ] **Character creation / classes / species** — no class field, no
      class features, no XP/leveling, no per-level HP derivation
- [ ] **Action economy** — one action per turn; no bonus actions,
      reactions, opportunity attacks, movement-vs-action split,
      Dodge/Disengage/Dash/Ready
- [ ] **Positioning** — no range, reach, cover, or grid; no
      ranged-in-melee disadvantage or prone-at-range rules
- [ ] **Condition immunities** (separate from damage immunities)
- [ ] **Entity-targeted tick effects** for status effects (player-only
      today)
- [ ] **Shops/currency** — stackable `coins` work in conditions, but
      no buy/sell action

### Recommended next work (lowest-hanging fruit first)

1. **SRD data pack infrastructure** (Part 2) — prerequisite for most
   of the below; small, self-contained.
2. **Full SRD condition list as built-in defaults** — pure data plus a
   handful of new `system_effects` keys (e.g. `advantage_on_attack`
   for invisible, `auto_fail_str_dex_saves` for stunned/paralyzed).
   Builds directly on the just-completed status-effect rework.
3. **Standard SRD gear catalog** (weapons/armor with proper
   properties) — data-only once the pack exists; immediately removes
   the biggest per-adventure duplication.
4. **Weapon properties round 2** — versatile/two-handed damage dice,
   thrown + ammunition, weapon proficiency gating (currently every
   attack gets the proficiency bonus).
5. **Player 0 HP: unconsciousness + death saves** — medium engine
   work, high rules-fidelity payoff; also unlocks player-side
   damage mitigation as a natural companion.
6. **Short/long rests** — per-rest recharge for abilities, hit dice,
   spell-slot recovery hook. Medium.
7. **Spellcasting proper** — slots by level, spell attack/save DC
   derivation, concentration. The big one; do only after 1–4.

### Housekeeping

- [x] Stale docs fixed: `README.md` intro (combat/inventory exist),
      `schema/actions.md` (combat action documented; combat no longer
      described as a future phase), `doc/intro.md` (action list
      updated to all ten types), `doc/combat.md` (saving throws no
      longer "(in future)"; limitations section current).
      `pyproject.toml` gained the `package-data` config needed to ship
      data packs in wheels.
- [ ] `doc/npcs.md:87` — `on_meeting` field is unused mechanically;
      either wire it up or drop it.

---

## Part 2 — SRD data pack design

### Problem

Chunky 5e content is currently either hardcoded in Python
(`SKILL_ABILITIES`, `DAMAGE_TYPES`, `DEFAULT_STATUS_EFFECTS`,
unarmed/legacy damage dice) or must be re-authored inline in every
corpus and character sheet (weapons, armor, potions, any spell-like
ability, any condition beyond the three built-ins, the six ability
score names in the `stats` block). With one adventure this is merely
untidy; with N adventures it's per-author duplication of licensed SRD
text and an invitation to inconsistency. There is no include/import
mechanism — the loader reads exactly one `corpus.json` per adventure
(`mgmai/state/manager.py:108`).

### Design: engine-bundled data packs, overlaid by the corpus

Generalize the existing `effective_status_effects()` pattern
(`mgmai/models/corpus.py:942-948`):

```
effective = {**ENGINE_DEFAULTS, **corpus_entries}   # corpus entry replaces default wholesale, by ID
```

1. **Data lives in JSON, shipped with the package.**
   New directory `mgmai/data/srd_5e/` (or `mgmai/systems/five_e/data/`)
   holding one JSON file per content kind: `conditions.json`,
   `gear.json`, `spells.json`, `monsters.json`, plus a `NOTICE`
   carrying the SRD 5.2.1 CC-BY-4.0 attribution (the README already
   attributes; the pack needs it next to the data). Load lazily via
   `importlib.resources`, keyed by system ID (`"5e"`). Requires
   `[tool.setuptools.package-data]` in `pyproject.toml` — currently
   absent, so JSON wouldn't ship in wheels without it.
   Rationale for JSON over Python literals: authors and LLM
   assistants can read/validate the pack with the same pydantic models
   as corpus files; a future non-5e system ships its own pack without
   touching 5e code.

2. **Data models are the existing corpus models.** A pack entry for a
   condition is a `StatusEffectDef`; for gear, an `Entity`-shaped
   template (or a slimmer `GearDef` sharing `EquipBlock`/
   `ConsumableBlock`); for spells, the future `Spell` model. No
   parallel schema. The pack is validated at import time by parsing
   into those models, and covered by a test that the shipped pack
   parses cleanly.

3. **Resolution is layered, defaults → corpus, by ID.** Extend
   `ModuleCorpus` with accessors mirroring `effective_status_effects()`:
   `effective_gear()`, `effective_spells()`, … each returning
   `{**pack_defaults, **corpus_block}`. A corpus entry with the same
   ID **replaces** the pack entry wholesale (no field merge — the
   established, documented semantics). Engine and system code always
   go through the accessor.

4. **Character sheets reference pack IDs; they don't restate them.**
   A player JSON lists `"abilities": ["fire-bolt"]` or
   `"inventory": {"longsword": 1}`; the loader resolves IDs against
   the effective maps. Unknown IDs remain load-time validation
   errors, exactly like unknown corpus IDs today.

5. **What goes in the pack, phased:**

   - **Phase A — infrastructure + conditions.** Loader, package-data
     config, `effective_*` accessor pattern; move
     `DEFAULT_STATUS_EFFECTS` out of `corpus.py` into
     `conditions.json` expanded to the full SRD condition list
     (blinded, charmed, deafened, frightened, grappled, incapacitated,
     invisible, paralyzed, petrified, poisoned, prone, restrained,
     stunned, unconscious + exhaustion levels), adding whatever
     `system_effects` keys their mechanics need. Also move the six
     ability-score names, `SKILL_ABILITIES`, and `DAMAGE_TYPES` into
     the pack (or keep in code — they're tiny and load-bearing; the
     pack is for *chunky* content).
   - **Phase B — gear catalog.** SRD weapons (with damage dice,
     damage type, properties), armor (ac_override/ac_bonus model),
     and standard consumables (e.g. Potion of Healing `2d4+2`). Needs
     the "gear template → entity instantiation" step in the loader:
     referencing `longsword` in a room or sheet mints an item entity
     from the template.
   - **Phase C — spells.** Only after spellcasting engine support
     (slots, DC derivation) lands. Spell entries extend the existing
     `Ability` shape with `spell_level`, `concentration`, etc. —
     SRD spell *names* and short mechanical summaries only; full
     prose descriptions are large and mostly irrelevant to the
     engine, which needs mechanical parameters plus a one-line
     flavor blurb for the GM briefing.
   - **Phase D — monsters (optional).** SRD stat blocks as
     `CombatBlock` templates. Lower value: encounters are usually
     adventure-specific, but common mobs (goblin, skeleton, wolf)
     would speed authoring.

6. **Deliberate non-goals.**
   - No include/import syntax in `corpus.json` — the overlay makes it
     unnecessary and keeps the single-file corpus contract.
   - No field-level merging of pack and corpus entries.
   - No runtime fetching of SRD content; the pack is versioned with
     the engine.

7. **Validator integration.** `scripts/validate_adventure.py` gains a
   check that gear/spell/condition references resolve against the
   *effective* maps (pack ∪ corpus), and warns when a corpus
   redefines a pack ID (legal, but worth surfacing).

### Why this fits the project

- The overlay pattern, wholesale-replace semantics, and
  accessor-on-`ModuleCorpus` shape are already proven by
  `effective_status_effects()` and the reserved-state-field defaults
  (`corpus.py:32-77`).
- System-agnostic engine + per-system pack mirrors the existing
  `ResolutionSystem` registry (`mgmai/engine/systems/__init__.py`):
  `register_system` for mechanics, pack directory for data.
- CC-BY-4.0 explicitly permits redistribution of SRD content with
  attribution, so shipping the pack in the repo is fine; keep the
  attribution next to the data.
