# Spellcasting

MGMAI models spells as **abilities with spell metadata** — there is no
separate spell model or `cast_spell` action.  A spell is an `Ability`
(`mgmai/models/corpus.py:628-664`) with `spell_level` set, cast through
the same `use_ability` combat action as class features and monster
powers.  The engine ships an SRD spell pack
(`mgmai/data/srd_5e/spells.json`) — currently 42 spells (12 cantrips,
30 leveled; the full catalog is listed in `schema/srd-5e-pack.md`) —
whose entries are minted into the corpus at load time unless the corpus
defines the same ID (corpus wins wholesale, same semantics as
gear; see `ModuleCorpus.effective_spells`, `mgmai/models/corpus.py:1013`).

---

## Quickstart

To make the player a caster, add three things to the player sheet
(`default-player.json` / `--char-sheet`):

```json
{
  "spellcasting_ability": "INT",
  "spell_slots": { "1": 2 },
  "max_spell_slots": { "1": 2 },
  "abilities": ["fire_bolt", "mage_armor", "magic_missile"]
}
```

The spells themselves come from the SRD data pack — no corpus entries
needed.  `spell_slots` maps spell level → slots remaining; note that
JSON object keys are strings (`{"1": 2}`), which pydantic coerces back
to `int` on load (see `schema/hard-state.md`).  `max_spell_slots` is
the recharge ceiling a long rest refills to — without it, slots
deplete with no recharge.  For a *prepared* caster, also declare
`spellbook` (the known superset of `abilities`) so spells can be
re-prepared in rest mode; see [rests](rests.md).

---

## Spell Slots

`PlayerState.spell_slots` (`mgmai/models/hard_state.py:70-75`) is a
cross-combat resource pool: casting a leveled spell (`spell_level >= 1`)
consumes one slot of exactly the spell's own level
(`mgmai/engine/combat.py:1714,1760`); cantrips (`spell_level == 0`)
cost nothing.  A cast with no slot remaining is rejected up front, both
in validation and at resolution.  Spells ignore `uses_per_combat` — the
slot pool replaces the per-combat use counter.

**Slots recharge on a long rest.**  A `rest` action with
`kind: "long"` refills `spell_slots` to `PlayerState.max_spell_slots`
(the recharge ceiling declared on the character sheet); a short rest
does not recharge slots.  When a character sheet omits
`max_spell_slots` for a level, that level is not recharged (usually a
sheet omission).  See [rests](rests.md).

## Save DCs and Attack Bonuses

For player casters, spell save DCs and attack bonuses are **derived**
from the character sheet, not authored per spell
(`FiveESystem.compute_spell_save_dc` /
`compute_spell_attack_bonus`, `mgmai/engine/systems/five_e.py:929-940`;
default no-op methods on `ResolutionSystem`,
`mgmai/engine/systems/base.py:451-460`):

- **Save DC** = `8 + proficiency_bonus + spellcasting_ability modifier`
- **Spell attack bonus** = `spellcasting_ability modifier + proficiency_bonus`

Healing spells also add the casting modifier to the dice (Cure Wounds
heals `2d8 + mod`).  NPC casters use the authored values instead: the
`save.dc` / `attack.stat` written on the ability.  The authored `save.dc`
on a pack spell is therefore the NPC-caster value and a display fallback.

## Effect Kinds

Spells use the same six effect shapes as any ability (see
`schema/corpus.md` — *Abilities*): `attack` (Fire Bolt), `save`
(Sacred Flame, Sleep), `heal` (Cure Wounds, Healing Word), `auto_damage`
(Magic Missile — no attack roll, no save), `on_cast` (Mage Armor —
applies a status effect to the target), and `cure_status` (Lesser
Restoration — ends status conditions on the target, with an optional
`then_apply` follow-up status as on Protection from Poison).

Attack effects may carry an `apply_status_effect_on_hit` rider (Ray of
Sickness' poisoned, Chill Touch's no-healing via the `no_healing`
system-effect key, Guiding Bolt's advantage mark); save effects carry
the long-standing `apply_status_effect_on_failure` twin.

Mage Armor's `on_cast` applies a persistent `mage_armor` status carrying
`system_effects: {"5e": {"ac_base": 13}}`; `compute_player_ac`
(`mgmai/engine/systems/five_e.py:827`, hook at :858-870) then uses
`13 + DEX mod` as the base AC, replacing the unarmored base or any armor
`ac_override`, while `ac_bonus` items (e.g. a shield) still stack.

## Area Effects

A `save` effect may carry an `area` block — `{"shape": "cone",
"size_ft": 15, "emanates_from_caster": true}` — as on Burning Hands,
Thunderwave, Web, and the other area spells in the pack.  TotM combat
has no grid, so area targeting resolves against the engagement graph
(`_area_save_targets`, `mgmai/engine/combat.py`):

- Shapes **emanating from the caster** (cones, self-centered cubes)
  hit every living combatant **engaged with the caster**.
- **Point-target** shapes (spheres, squares, remote cubes) hit the
  target plus every living combatant **engaged with the target**.

Friendly fire applies in both cases — an ally swarmed by the same
enemies is caught in your Burning Hands.  Each caught combatant saves
separately and gets its own `ability_save` combat-log entry (and its
own damage roll).  `shape`/`size_ft` document the true SRD area for
briefings and any future richer targeting model.

## Concentration

A spell with `concentration: true` engages the caster's concentration
when cast in combat (`mgmai/engine/combat.py:998-1015`):

- `CombatState.concentration` (`mgmai/models/combat.py:85`) maps
  caster id → spell id; it is combat-scoped and dies with the combat.
  The caster also carries a `concentrating` status for briefing
  visibility.
- **One at a time**: casting a second concentration spell drops the
  first.
- **Break on damage**: after any damage applied through
  `_apply_damage_to_target` (`mgmai/engine/combat.py:1101`) — the single
  damage path used by weapon attacks, abilities, and opportunity attacks
  — the caster makes a Constitution save, DC `max(10, damage // 2)`
  capped at 30 (`_check_concentration`, `combat.py:1036`).  Players make
  a full CON save; NPCs use their flat combat-block `save_bonus`.  On
  failure, concentration ends.
- **Break on incapacitation or death**: dropping to 0 HP or gaining a
  turn-skipping status ends concentration outright
  (`_end_concentration_if_incapacitated`, `combat.py:1019`).

When concentration ends (`_end_concentration`, `combat.py:957`), the
spell's `sustained_status_effects` are removed from **every** combatant,
unconditionally — status effects don't track their source spell, so if
two sources grant the same status (e.g. two casters' Sleep), one break
clears both.  A known simplification; proper source tracking is a
status-effect model refactor.

**Known gap**: NPC on-hit *secondary* damage (the extra damage rider on
`_resolve_npc_on_hits`, resolved outside the single damage path) does
not trigger a concentration save.

## Out-of-Combat Casting

Outside combat, `use_ability` is a top-level action resolved by
`resolve_out_of_combat_ability` (`mgmai/engine/combat.py:1819`, routed
from `mgmai/engine/resolver.py` via `_resolve_use_ability`):

- **Self/ally heal, on-cast, and cure-status** abilities resolve
  directly — Cure Wounds between fights, Mage Armor before a fight,
  Lesser Restoration on a poisoned ally, etc.
- **Enemy-targeted abilities** start combat automatically, mirroring
  `interact`/`attack`: the engine calls `enter_combat`, pulling in the
  target's `combat_group`, and the spell is available on the player's
  first combat turn.
- **Concentration spells** and **attack/save/auto_damage** effects still
  require a live `CombatState` and are rejected out of combat.
- **Slots** are consumed as normal (the pool lives on `PlayerState`,
  not on `CombatState`).  `uses_per_combat` abilities are unlimited out
  of combat — the counter is combat-scoped; per-day recharge is deferred
  to rests.

The LLM sees the player's abilities, slot pool, and active status
effects out of combat via `PlayerStateBriefing`, and the merged
`_validate_use_ability` validator gates illegal casts up front (see
`mgmai/templates/ruling.j2`).

## Bonus-Action Casting

A spell with `casting_time: "bonus_action"` is cast as a **bonus
action** (`resolve_combat_turn`, `mgmai/engine/combat.py`): the cast
resolves but does not end the player's turn — the player still takes
their normal action that round.  Bonus actions live on the shared
per-turn budget:

- `CombatState.player_budget.bonus_action_used` — one bonus action per
  turn; a second is rejected.  A bonus action may be taken before *or*
  after the main action (SRD-faithful ordering).
- `CombatState.player_budget.slot_cast_this_turn` — one **leveled** spell
  per turn, in either order: after a bonus-action leveled spell, the main
  action can only be a cantrip or a non-spell action (and vice versa).
- `CombatState.turn_continuation` — the follow-up main-action call skips
  start-of-turn processing so status effects tick exactly once per round;
  both the bonus-action cast and the main action appear in the combat
  log, and a bonus-action cast that ends combat still runs the
  combat-end epilogue.

At the engine layer, only the segment that actually *ends* the turn
reports `costs_turn=True`, so the persistent-status tick, `turn.end`, and
the `turn_count` bump happen exactly once per player turn even when it
spans two engine calls.

`casting_time: "reaction"` (e.g. Shield) remains data-only — reactions
are capped at one per combatant per round (opportunity attacks only) but
reaction *spells* are not castable yet.

---

## Deferred Items

Deliberately not implemented:

- **Upcasting** — a spell consumes exactly its own level; no
  higher-level slot selection or scaling.
- **Cantrip scaling** — cantrips use base dice at all levels
  (`PlayerState.level` is inert).
- **Reaction spells** — `casting_time: "reaction"` is data-only; the
  reaction economy caps opportunity attacks at one per combatant per
  round, but Shield/Counterspell-style casts are deferred (Phase 3).
- **Ritual casting** — the `ritual` flag is data-only.
- **NPC caster blocks** — NPC casters use authored DC/attack values and
  the flat `save_bonus` for concentration checks.
- **Source-tracking for sustained effects** — see the over-removal
  caveat under *Concentration*.
- **Warlock pact magic** — short-rest slot recharge; the slot pool does
  not distinguish slot *kinds* yet (waits on classes).
