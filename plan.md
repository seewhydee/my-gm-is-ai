# Soft State System — Revision Plan

This plan addresses (a) the shortcomings in the soft-state patch
system and (b) the disarray in the soft-state documentation.  Each
section records the decision and the concrete actions required.

Conventions for action items: file paths are repo-relative; line
numbers are current as of this writing and may drift during edits.

---

## 1. Rename `proposed_soft_state_patches` → `soft_state_patches`

**Decision.** Rename the `PlayerAction` field to `soft_state_patches`
(plural — it is an array).  Do **not** rename it to `proposed_notes`:
the field carries five patch types, only three of which are notes
(`room_note`, `entity_note`, `appearance_note_add`); the other two
(`soft_inventory_remove`, `set_improvised_weapon`) are not notes.  The
original rename motivation rested on a miscount.  Dropping the
`proposed_` prefix is pure brevity; the engine still validates every
patch, so "proposed" was implicit.

**Actions.**

- [ ] `mgmai/models/actions.py:30` — rename the field.
- [ ] `mgmai/engine/engine.py:384` — update the read site.
- [ ] `mgmai/templates/ruling.j2` — rename in the field table, all
      examples, and the "Critical Constraints" section.
- [ ] `schema/actions.md` — rename in the PlayerAction field table
      (§2) and every action example block.
- [ ] `schema/soft-state.md` — rename in the SoftStatePatch reference.
- [ ] `doc/soft.md`, `doc/intro.md:88` — update prose references.
- [ ] `tests/` — update fixtures across `test_actions.py`,
      `test_engine.py`, `test_loop.py`, `test_parser.py`,
      `test_soft_state.py` (all reference the old name).

---

## 2. Patch format simplification

**Decision.** Keep the **append-array** model for `room_notes` and
`entity_notes` (each patch appends one string; the LLM only emits the
new detail).  Three simplifications:

1. **Drop `old_value`** from `SoftStatePatch`.  It is stored on the
   model but never validated for any note patch (only `attitude_changes`
   uses `old_value`, and those are a separate LLM-Call-2 channel, not a
   `SoftStatePatch`).  It is dead weight and undocumented in
   `ruling.j2`.
2. **Drop `target_id`** from `room_note` patches.  Under the scope
   decision (§4), room notes always attach to the present room, so
   `target_id` is derivable from `hard.player.location` and is
   redundant.  `entity_note` keeps `entity_id` (several entities may be
   present).  `target_id` is removed from the model entirely — no
   remaining patch type uses it.
3. **Remove the last-5 cap.**  Soft notes are lightly used; the
   `[-5:]` slicing at briefing time is premature optimisation that also
   silently discards history.  Surface all notes, in insertion order.
   (Briefing-time dedup is not currently implemented despite the docs
   claiming it "can" dedup; drop that aspirational claim rather than
   implement it now.)

Resulting note patch shapes:

```json
{ "field": "room_note",
  "new_value": "The webs here are partially cleared.",
  "reason": "Player hacked through the webs with the iron sword." }

{ "field": "entity_note", "entity_id": "spider",
  "new_value": "The spider's left legs are covered in ichor.",
  "reason": "Player wounded the spider with the toenail sword." }
```

**Actions.**

- [ ] `mgmai/models/soft_state.py:40-81` — `SoftStatePatch`: remove
      `old_value` and `target_id` fields; update
      `check_field_consistency` so `room_note` no longer requires
      `target_id` (and rejects a stray one), `entity_note` still
      requires `entity_id`, and the other branch validators drop their
      `target_id` checks.
- [ ] `mgmai/engine/engine.py:601-659` (`_validate_soft_patches`) —
      `room_note`: use `hard.player.location` as the target; remove any
      `old_value`/`target_id` handling.
- [ ] `mgmai/state/manager.py:1503-1521` (`apply_soft_patches`) —
      `room_note` writes to `room_notes[hard.player.location]`; drop
      `target_id` reads.
- [ ] Remove the last-5 cap (drop `[-5:]`):
      `mgmai/context/assembler.py:110,186`,
      `mgmai/engine/utils.py:148`,
      `mgmai/engine/engine.py:723,780`.
- [ ] `mgmai/templates/ruling.j2` (§ "Soft State Patches") — drop the
      `target_id` row and any `old_value` mention; state that
      `room_note` attaches to the present room.
- [ ] `schema/soft-state.md` — rewrite the patch-format examples and
      the SoftStatePatch reference table (remove `old_value` and
      `target_id` columns/rows); update validation rules.
- [ ] `schema/actions.md` §3 — update the SoftStatePatch summary.
- [ ] `tests/test_soft_state.py`, `tests/test_actions.py`,
      `tests/test_engine.py` — update patch fixtures (drop
      `target_id`/`old_value`).
- [ ] `schema/actions.md:248` — "entity notes (up to 3 most recent)"
      → "entity notes" (cap removed; also fixes an old 3-vs-5
      inconsistency).

---

## 3. Player entity notes — officially supported

**Decision.** `entity_note` with `entity_id == "player"` is the
sanctioned mechanism for "global" soft-state notes that follow the
player.  The infrastructure already exists: `"player"` is a corpus
entity (`adventures/bag-of-holding/corpus.json:17`,
`type: "player"`), and the Context Assembler already surfaces
`soft.entity_notes["player"]` in the player-state briefing block
(`assembler.py:215`, tested at `test_assembler.py:520`).  The only gap
is that nothing tells the LLM it may do this, and the new presence
check (§4) must exempt the player entity, which is never in
`room_contains`.

**Actions.**

- [ ] `mgmai/engine/engine.py` `_validate_soft_patches` — when
      enforcing presence, accept an `entity_id` whose
      `corpus.entities[entity_id].type == "player"` regardless of room
      presence.
- [ ] `doc/soft.md` — document that an `entity_note` on the player
      entity records player-scoped/global observations.
- [ ] `mgmai/templates/ruling.j2` — instruct LLM Call 1 that
      `entity_note` with `entity_id: "player"` is available for
      cross-room observations worth remembering.
- [ ] `schema/soft-state.md` — note in the `entity_notes` section that
      the player entity is a valid target.

---

## 4. Note scope: present room + present entities + player

**Decision.** Notes may target:

- the **current room** (`room_note`, no `target_id`),
- any **entity present in the current room**, including entities nested
  inside containers in the room (contained entities are *not* "visible"
  in `entities_visible`, but the player can still affect them, e.g.
  scratching the outside of a closed chest), plus **following NPCs**,
- the **player entity** (see §3).

This matches what the LLM can actually observe and closes the
doc-vs-code gap: `doc/soft.md` currently *claims* present-only, but
`_validate_soft_patches` (`engine.py:613`) accepts any corpus
room/entity.  We tighten the engine to enforce the doc's intent
(extended to explicitly cover contained entities and the player),
rather than loosening the doc.

**Actions.**

- [ ] `mgmai/engine/engine.py` `_validate_soft_patches` —
      - `room_note`: target is `hard.player.location` (always valid).
      - `entity_note`: build the present-entity set =
        `set(hard.room_contains[current_room])`
        ∪ transitively-nested entities in containers present in the room
        (reuse the `entity_contains` walk pattern from
        `mgmai/engine/resolver.py:589-591`)
        ∪ `get_following_npc_ids(hard, corpus)` (see `event_bus.py:79-81`)
        ∪ {player entity, by `type == "player"`}.
        Reject `entity_id` not in this set.  Keep the existing
        `alive == false` rejection.
- [ ] Consider factoring a shared `present_entity_ids(hard, corpus)`
      helper (currently inlined in `event_bus.py`, `combat.py:311`,
      `resolver.py`) so the validator, assembler, and event bus share
      one definition.
- [ ] `doc/soft.md` — state the scope rule clearly (present room +
      present entities incl. contained + following NPCs + player).
- [ ] `schema/soft-state.md` — update `entity_notes` validation rules
      to state the presence requirement.
- [ ] Tests — add cases: (a) note on present entity accepted, (b) note
      on entity in another room rejected, (c) note on contained entity
      in present room accepted, (d) note on player entity accepted.

---

## 5. Documentation reorganization

The split: **`doc/soft.md`** is the *design overview* (what soft state
is, why it exists, how the pieces interact); **`schema/soft-state.md`**
is the *in-game representation* (the JSON fields, their shapes, and
validation rules).  Material has drifted across the boundary and some
is duplicated in a third place (`schema/actions.md`).

### 5.1 Role split (guiding principle)

- `doc/soft.md` keeps: rationale, the "two parts" overview, the Soft
  Items concept, corpus guidance for `soft_item_guidance`, the
  Interaction Flow narrative (with ASCII diagrams), Carried Soft Items,
  and a corrected Files Summary.
- `schema/soft-state.md` keeps: the top-level schema, every field's
  JSON shape and validation rules, the SoftStatePatch reference.
- `schema/actions.md` keeps: `SoftItemProposal` / `SoftItemAdjudication`
  formats (already in §4–5), the `attitude_changes` output format (§5).

### 5.2 Move schema detail out of `doc/soft.md`

- [ ] Remove the patch-format JSON example (`doc/soft.md:67-76`) — it
      duplicates `schema/soft-state.md`; replace with a one-line
      pointer.
- [ ] Trim the "Soft State" subsection (`doc/soft.md:103-153`): the
      `soft_inventory` / `soft_items_taken` / `soft_contents` JSON
      blocks duplicate `schema/soft-state.md`.  Keep a brief design
      statement ("soft inventory holds carried soft items; extraction
      history and current placement are tracked separately") and point
      to the schema for shapes.
- [ ] Remove the "Adjudication Model" tables (`doc/soft.md:293-332`):
      the `SoftItemProposal` and `SoftItemAdjudication` field tables are
      already in `schema/actions.md` §4–5.  Keep the surrounding
      narrative (what adjudication achieves) and link to the schema.

### 5.3 Remove misplaced hard-state material from `schema/soft-state.md`

- [ ] Delete the "NPC Attitude Tracking" section
      (`schema/soft-state.md:137-176`).  Attitude lives in
      `hard_state.entity_states` (documented in `schema/hard-state.md`
      under `entity_states`), and the design is covered in `doc/npcs.md`
      ("Attitude System").  The section also references a **non-existent
      `npc_revelations` field** (the real field is `player_knowledge`).
- [ ] Move the "Attitude changes (LLM Call 2)" validation-rules table
      (`schema/soft-state.md:661-673`) into `schema/hard-state.md` as a
      new "NPC Attitude" subsection under `entity_states` (attitude is
      hard state; the proposal *format* stays in `schema/actions.md` §5;
      the design stays in `doc/npcs.md`).

### 5.4 Fix broken cross-references

- [ ] `schema/soft-state.md:7` — `../docs/soft.md` → `../doc/soft.md`
      (the directory is `doc/`, not `docs/`).
- [ ] `doc/soft.md:23` — `actions.md` → `../schema/actions.md`.
- [ ] `README.md:84` — `doc/soft-items.md` → `doc/soft.md` (file was
      renamed/merged; the link is dead).
- [ ] `doc/soft.md:351` (Files Summary, last row) — currently reads
      `doc/soft-state.md | This document`.  Fix to
      `doc/soft.md | This document`, and ensure the
      `schema/soft-state.md` row references the correct path.

### 5.5 Remove the last-5 cap from the docs

(Cap removal is decided in §2; this covers the doc fallout.)

- [ ] `schema/soft-state.md:70` — drop "(up to 5 per room)".
- [ ] `schema/soft-state.md:94` — drop the "Context Assembler can
      deduplicate at briefing time" claim (not implemented; surface all
      notes in insertion order).
- [ ] `schema/soft-state.md:497-498` — drop "(last 5 notes per
      entity)".
- [ ] `schema/actions.md:248` — drop "(up to 3 most recent)".

---

## Open question (non-blocking)

- Whether to factor a shared `present_entity_ids(hard, corpus)` helper
  (§4) is a minor refactor judgment left to implementation; it is not
  required for correctness.
