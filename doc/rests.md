# Rests

Rests recover expended resources — HP, spell slots, Hit Dice — and give
the player a place to do character-sheet bookkeeping (re-preparing
spells, spending Hit Dice).  The feature has two halves with two
different interfaces:

1. **The `rest` action** — recharge as a *world event*, resolved through
   the normal player → ruling-LLM → engine → prose-LLM loop.  The
   ruling LLM decides whether resting is fictionally possible; the
   engine applies the recharge deterministically; the prose LLM narrates
   it.
2. **Rest mode** — re-preparation as *bookkeeping*, a modal, LLM-free
   numbered-menu UI entered after a rest resolves.  No LLM is called and
   no turn is consumed inside rest mode.

---

## The `rest` Action

`RestAction` (`mgmai/models/actions.py`) carries one field, `kind:
"short" | "long"`.  It is dispatched like any other action
(`resolve_rest`, `mgmai/engine/resolver.py`), costs a turn, and is
**rejected during combat** — both by the engine backstop and by ruling
validation, mirroring the `talk` precedent; the ruling LLM is told to
rule an in-combat rest attempt as `wait` instead.

There is **no engine-enforced frequency limit** (the SRD's
one-long-rest-per-24h rule): `turn_count` is not a time unit, so
"you rested an hour ago" is left to the ruling LLM's fiction judgment.
Likewise, resting somewhere dangerous is refused at the ruling layer —
rest *interruption* (a mid-rest ambush with partial benefits) is not
modeled.

A successful rest emits a `rest.completed` event (context key `kind`)
after the recharge is applied, so corpus reactions observe post-rest
state — see [events](../schema/events.md#rests).

## Recharge Rules (5e, SRD 5.2.1)

What a rest *means* is decided by the active resolution system, not the
engine: `ResolutionSystem.on_short_rest` / `on_long_rest`
(`mgmai/engine/systems/base.py`, no-op defaults) return a
`RestRechargeResult` (`mgmai/models/actions.py`), which the resolver
applies deterministically.  `FiveESystem` implements the SRD rules:

| Effect | Short rest | Long rest |
|---|---|---|
| Player HP | — | restored to full |
| Spell slots | — | refilled to `max_spell_slots` |
| Hit Dice | spendable (rest mode) | all spent dice recovered |
| Follower allies | — | healed to full HP |
| Exhaustion | — | reduced by one level |
| Persistent magic | — | ends (see below) |

Application details:

- HP healing flows through `HardStateChanges.player_hp_delta` (so the
  prose LLM and state-change event derivation see it), with the healed
  amount also recorded in `player_heal_delta` — the directional
  component the narrative indicators use to show healing separately
  from damage; slot, hit-dice,
  status, and follower changes are applied directly to `hard`, mirroring
  `apply_status_effect` / `remove_status_effect` and NPC HP handling in
  combat.
- **Slot refill is per declared level**: each level in
  `max_spell_slots` is refilled to its ceiling; a level present in
  `spell_slots` but absent from `max_spell_slots` (a sheet omission the
  validator warns about) is left untouched — not recharged, not wiped.
- **Exhaustion** steps down one level: `exhaustion-3` → `exhaustion-2`,
  and `exhaustion-1` is removed entirely.
- **A long rest ends time-limited persistent magic**: every
  `persistent`-scope status on the player is cleared except
  `exhaustion-*`.  This covers Mage Armor (modeled as `persistent` +
  `until_cleared`) and rounds-duration buffs.  *Known limitation*: a
  future *permanent* persistent condition (a curse, say) would also be
  cleared — distinguishing permanent from time-limited needs a status
  flag (e.g. `expires_on_long_rest`) when such conditions are
  introduced.
- Follower allies (NPCs with `following: true`, see
  `get_following_npc_ids`) are restored to full HP; NPCs get no
  hit-dice tracking.

The rest is narrated by the prose LLM from the `EngineResult`; the
`message` field carries a factual summary of what was recovered
("Long rest: HP +8; spell slots recharged; exhaustion -1.").

## Character-Sheet Fields

Three `PlayerState` fields support rests (full details in
[hard state](../schema/hard-state.md)):

- **`max_spell_slots`** — the recharge ceiling, declared alongside
  `spell_slots`.  Without it, slots deplete with no recharge (the
  pre-rests behavior).
- **`hit_dice`** — `{ "die": "d8", "current": 3, "max": 3 }`; spent in
  rest mode, recovered on long rests.
- **`spellbook`** — every ability the character *knows*, for prepared
  casters.  `abilities` remains the castable/*prepared* subset that
  `CombatAction.ability_id`, briefings, and validation read (invariant:
  `abilities ⊆ spellbook`).  Empty for spontaneous casters and
  non-casters — `abilities` is the whole list and there is nothing to
  re-prepare.

## Rest Mode

After a successful rest — short or long — the game loop enters **rest
mode** (`mgmai/game/rest_mode.py`) before returning to normal play:

- On entry it **always displays a summary** of what the rest did plus a
  status line (HP, Hit Dice, slots), even when there is nothing to
  decide — the deliberate pause gives the rest narrative weight as a
  break in play.
- Options are a numbered menu (the same idiom as the CLI model picker):
  **Prepare spells** (shown only when the player has a `spellbook`),
  **Spend hit dice**, and **Done**, always last.  Sub-menus toggle by
  number and confirm with `0`/Enter; invalid input re-prompts.
- Mutations go through deterministic engine helpers
  (`spend_hit_die` / `set_prepared_spells`,
  `mgmai/engine/rest_helpers.py`) — synchronous validation, no LLM, no
  turn consumed, and the menu cannot be left in an invalid state.
  `spend_hit_die` rolls the die + CON modifier (minimum 1 HP, per the
  SRD), clamped to max HP; `set_prepared_spells` validates the whole
  list against the corpus and spellbook before mutating.
- Choosing *Done* exits back to the normal loop.  Bookkeeping is **not**
  narrated — re-preparing spells is out-of-fiction.

Rest mode is a single-step controller: each input line is one menu
step, and it never calls `input()`.  The session routes input through a
shared `_dispatch_input` helper (`mgmai/game/session.py`), so
`HeadlessSession.submit("3")` drives it one step at a time — tests and
non-terminal front-ends play through rests exactly as a human at a
terminal does.  (This plumbing also makes the slash commands reachable
under headless.)  Note that while rest mode is active, menu numbers are
the input language — slash commands resume after *Done*.

---

## Deferred Items

Deliberately not implemented:

- **Rest interruption / mid-rest ambushes** — refuse unsafe rests at the
  ruling layer; `rest.completed` leaves the hook for corpus reactions.
- **Rest frequency limits** — no engine clock; fiction-adjudicated.
- **Warlock pact magic** — short-rest slot recharge needs slot *kinds*
  (waits on classes).
- **Named per-rest resource pools** (Action Surge, Channel Divinity,
  Lay on Hands) — stay on `uses_per_combat` until a `resources`
  generalization lands.
- **Level-up choices, attunement, downtime activities** — future rest
  mode tenants.

> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
