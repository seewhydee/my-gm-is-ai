# Container Semantics — Implementation Plan

## Problem

The current container system forces each adventure corpus author to hand-roll
a fragile multi-step pattern:

1. Declare `contained_entities` on the container entity (corpus)
2. Declare `hidden` in `state_fields` on each contained item (corpus)
3. Initialize `hidden: true` on each contained item (hard-state)
4. Write an `on_examine` event or interaction that manually sets
   `hidden: false` on all contained items when the container is examined/opened
5. Optionally, declare `open`/`closed` state on the container itself, with an
   interaction that flips it

Each step must be coordinated with the others. A single mistake makes
items permanently invisible or visible at the wrong time. This is a
high-cognitive-load task for the generating LLM, and the result is
fragile.

Additionally, `contained_entities` is static corpus data, but container
contents are runtime-dynamic. If an NPC interaction or mechanic removes
an item from a container, the corpus still lists it as contained. The
engine's current workaround (filtering against player inventory) only
covers the case where the **player** has the item.

## Solution

Introduce a **`container` tag** and reserve the **`open` state field**.
When an entity has:

- `tags: ["container"]`
- Non-empty `contained_entities`
- `open` declared in `state_fields`

…the engine uses the container's `open` state to decide whether its
contents are visible and accessible.

- If `open` is `false` **or missing from hard state**, the container is
  treated as closed: its `contained_entities` and `soft_items` are hidden
  from briefings and cannot be transferred.
- If `open` is `true`, the contents are surfaced normally, **subject to
  each item's own `hidden` state**. This keeps `hidden` orthogonal: it can
  still be used for concealment independent of the container (darkness,
  burial, magic, etc.).

A container author now only needs:

- `tags: ["container"]`
- `open` declared in `state_fields`
- `open: false` initialized in hard-state
- an interaction that sets `open: true`, gated with
  `condition: { "require": "entity:<id>.open == false" }`

The engine exposes revealed items factually in `room_after` (via
`contained_entities` in the briefing); the LLM narrator is responsible
for prose.

### Why `open` and not `closed`

- Natural language: "the chest is `open: true`" reads normally.
  The double-negative `closed: false` is harder on humans and LLMs.
- Matches the existing convention already used in scenario-generation.md
  examples.
- Default `false` is correct: a container starts closed.

### Why a tag instead of field-name detection alone

Doors, windows, and other non-container entities may legitimately use
`open` as a state field. The `container` tag makes the engine's intent
explicit and prevents false positives.

### Orthogonality of `hidden`

`hidden` on a contained item is **not** managed by the container
mechanic. Opening a container reveals only the items that are not
individually `hidden`. This means:

- Authors no longer need `hidden` on items solely because they are in a
  container.
- Authors can still use `hidden` for other reasons (buried, invisible,
  darkened, etc.) even on items inside an open container.

## Changes

### 1. Engine — `build_contained_entities()` gate

**File:** `mgmai/engine/utils.py` (around line 109)

Add a check at the start of `build_contained_entities`:

- If the parent entity has `tags` containing `"container"` **and**
  its hard state has `open` not equal to `true` (i.e. `false`, `None`, or
  absent), return an empty list.
- Otherwise, proceed with existing logic (filter individual `hidden`,
  filter player inventory/equipped).

If the entity does NOT have the `container` tag, existing behavior is
unchanged (backward compatibility for piles of junk, corpses, etc. that
expose contents without an open/close mechanic).

If the entity HAS the `container` tag but does NOT have `open` declared
in `state_fields`, treat `open` as `true` (default-open; e.g., a shelf
or a corpse — contents always visible). This preserves the rule that
`container` + declared `open` is what enables closed-by-default behavior.

### 2. Engine — `resolve_transfer()` gate

**File:** `mgmai/engine/resolver.py` (around line 650)

Introduce a helper, e.g. `_container_is_open(entity_id, hard, corpus)`:

- Returns `True` if the entity is not a container, or if it is a
  container and its hard-state `open` is `true`.
- Returns `False` if it is a container and `open` is `false`, `None`, or
  absent.

Apply it in both `resolve_transfer` branches:

- **Entity target:** if `target_id` is a closed container and any
  `taken_items` are in its `contained_entities` or `soft_items`, return
  an error like `The <container> is closed.`
- **Room target:** when iterating `room.entities_present`, only add an
  entity's `contained_entities` and `soft_items` to `available_pool` if
  that entity is open (or not a container). If a requested `taken_item`
  belongs to a closed container in the room, return the same closed
  error.

### 3. Engine — no auto-generated reveal prose

**File:** none required

The engine does **not** generate custom narration when a container
opens. It simply exposes the now-visible `contained_entities` in the
`room_after` briefing. The LLM narrator receives the factual update and
can phrase it appropriately.

### 4. Corpus schema docs — reserved state fields and `container` tag

**File:** `schema/corpus.md` (Reserved state fields section)

Add `open` to the list of reserved state fields:

| Field | Meaning |
|-------|---------|
| `open` | For entities with `tags: ["container"]` and declared `state_fields.open`: whether the container is open and its `contained_entities` / `soft_items` are accessible. Defaults to closed (`false`) when declared but absent from hard state. |

Update the `tags` row in the entity table to note that the `"container"`
tag is recognized for `feature` entities (and is not limited to `item`).

### 5. Generation instructions — simplify §2D containers

**File:** `schema/scenario-generation.md` (lines 693–763)

Replace the current four-part hidden-item coordination pattern with:

- Set `tags: ["container"]` on the feature entity.
- Declare `open` in `state_fields`.
- Initialize `open: false` in `hard_state.entity_states`.
- List starting contents in `contained_entities` (and optional loose
  items in `soft_items`).
- Add an interaction that sets `open: true`, with a condition so it only
  works while closed:

```json
{
  "id": "open",
  "label": "Open",
  "description": "Open the chest.",
  "condition": { "require": "entity:chest.open == false" },
  "result": {
    "narrative": "You lift the lid of the chest.",
    "set_entity_state": { "chest": { "open": true } }
  }
}
```

Remove the example with `glowing_gem.hidden` and the manual
`set_entity_state` on contained items. Fix the existing typo that sets
`stone_altar.open` instead of `chest.open`.

Explain that:

- The engine automatically hides contents while `open` is `false`.
- The engine automatically surfaces contents when `open` is `true`,
  but respects any `hidden` state on individual items.
- Soft items declared directly on a closed container are treated as
  inside it and are also unavailable until opened.

### 6. Backward compatibility

- Entities with `contained_entities` but **without** the `container`
  tag work exactly as before (no engine behavior change).
- Existing adventures (e.g., `bag-of-holding`) continue to function with
  their hand-rolled `hidden` patterns. They can be migrated to the new
  pattern when convenient.
- The `hidden` state field remains supported for non-container
  concealment.

### 7. Future: runtime container inventory (out of scope for now)

A later change should track container contents at runtime (e.g., via an
engine-managed `_contents` field in entity state, initialized from
`contained_entities` and kept in sync by `transfer`), so the engine
knows what's actually in a container regardless of NPC actions or
narrative changes. This addresses the "removed another way" fragility
identified in the problem statement. Deferred as a separate project.

## Migration of existing adventure (bag-of-holding)

**Deferred.** The `bag-of-holding` adventure will be regenerated
separately. This plan leaves the existing corpus untouched for now.

## Validation file

**File:** `mgmai/models/corpus.py`

No schema changes needed. `tags` is already `List[str]`. `open` is
validated as a regular `state_fields` entry. The engine's runtime checks
on `tags` and `open` are soft conventions, not Pydantic constraints.

## Tests

- Unit: `build_contained_entities` returns empty when parent has
  container tag + `open: false`.
- Unit: `build_contained_entities` returns items when parent has
  container tag + `open: true`.
- Unit: `build_contained_entities` still filters individually `hidden`
  items inside an open container.
- Unit: `build_contained_entities` unchanged without container tag
  (backward compat).
- Unit: `resolve_transfer` rejects taking from closed container
  (entity target and room target).
- Unit: `resolve_transfer` allows taking from open container.
- Unit: `resolve_transfer` rejects soft items from closed container.
- Integration: opening a container makes contents visible in
  `room_after` briefing without manual `set_entity_state`.
- Integration: existing adventure corpus passes validation unchanged.
