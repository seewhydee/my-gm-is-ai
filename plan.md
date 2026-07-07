# Plan: World-side containment with quantity tracking

## Problem statement

Commit `2b93aa3` converted player `inventory` from `list[str]` to `Dict[str, int]`,
enabling stackable items with quantities. Two gaps remain on the world side.

### Problem 1: `contains` lacks quantity support

`Room.contains` and `Entity.contains` are still `List[str]` — a flat list of entity IDs.
There is no way to express "this chest contains 50 gold coins." The player inventory
format already solved this with a dict; the world side hasn't caught up.

### Problem 2: `contains` is a static corpus field, not runtime world state

The corpus is read-only after load. Containment is currently a static declaration.
This creates concrete bugs:

- **No depletion tracking.** `available_pool` in the transfer resolver is a `set[str]`
  built from the static `room.contains`. There is **no quantity limit**: you can take
  1000 coins from a room that only declares 50.

- **Invisible stacks.** Once the player holds ANY of a stackable item, the filtering
  code (`eid in hard.player.inventory`) hides the entire item from room visibility —
  the remaining coins in the room vanish from both the GM briefing and the available pool.
  This filter currently appears in three places: `context/assembler.py:94`,
  `engine/utils.py:131-135` (`build_contains`), and `engine/engine.py:687`
  (`_build_room_after`).

- **Giving items makes them disappear.** Hard items given to a room or NPC are
  removed from player inventory but only surface as soft_items — they are never
  placed back into a mutable world-side container. They become narrative-only fluff.

### Root cause: static `contains`

The current design conflates two concerns:
1. Initial placement of entities (a corpus concern)
2. Runtime tracking of where entities are (a state concern)

By squashing both into the read-only corpus `contains`, the engine has no place to
persist mutations like "the player took 30 coins, 20 remain" or "the player gave the
sword to the goblin."

---

## Design decisions

### 1. Mixed-type `contains` is the *authoring* format only

Module authors should not be forced to write `{"goblin": 1, "chest": 1, "gold_coin": 50}`
for every entity. The corpus JSON accepts a list of either plain strings (count=1) or
single-key count-objects for stacked items:

```json
"contains": ["goblin", "chest", {"gold_coin": 50}]
```

The Python model normalises this at validation time. `Room.contains` and
`Entity.contains` keep their declared type `List[Union[str, Dict[str, int]]]` (so the
raw input round-trips and authors see what they wrote), but a
`@model_validator(mode="after")` builds a **private** `_contains_map: Dict[str, int]`
and exposes it via a read-only `.contains_map` property.

**Hard rule: no runtime code iterates the raw `contains` list.** Every corpus-side
read uses `.contains_map` (initial placement only); every runtime read uses the
runtime maps in `HardGameState` (see §2). The raw `contains` list is for JSON I/O
and corpus validation only. This is what makes the mixed-type list safe: a dict
element in the list would crash any `.get(dict)` call, so the rule is enforced by
auditing that *no* consumer touches `room.contains` / `entity.contains` directly.

### 2. Runtime containment in `HardGameState`, initialised from corpus

Two new top-level fields in `HardGameState`:

```python
# {room_id: {entity_id: count}}
room_contains: dict[str, dict[str, int]] = Field(default_factory=dict)

# {container_entity_id: {entity_id: count}}
entity_contains: dict[str, dict[str, int]] = Field(default_factory=dict)
```

At game start these are initialised from the corpus `Room.contains_map` /
`Entity.contains_map`. Thereafter **every consumer reads exclusively from the
runtime maps** — the corpus `contains` fields are never consulted again at runtime.
Mutations (taking, giving) flow through `HardStateChanges` → `apply_hard_changes`
(see §3), which writes to `room_contains` / `entity_contains`.

This makes `contains` in the corpus purely declarative: "here are the initial
conditions." The corpus schema docs will state this explicitly.

#### Initialisation rules (critical — this is what makes existing adventures work)

There is no `new_game()` method; the two real entry points are `StateManager.load_all`
(fresh adventure load) and `StateManager.load_save` (restore a save). A new private
helper `StateManager._init_contains_from_corpus()` rebuilds the maps from the corpus
`contains_map`. It is called as follows:

| Entry point | Behaviour |
|-------------|-----------|
| `load_all` | **Always rebuild** `room_contains` / `entity_contains` from the corpus. The shipped `hard-state.json` is the initial state; the corpus is the authoritative source of initial placement, so its `contains_map` wins. This means existing adventure `hard-state.json` files need **zero migration** — they simply don't carry these keys. |
| `load_save` | Inspect the **raw** save dict before pydantic defaults apply. If `"room_contains"` is present, trust the saved maps (a save written by the new engine always has them, including mutated counts). If absent (legacy save predating this feature), call `_init_contains_from_corpus()` once. Because the feature is new, no legacy save can have *mutated* containment, so backfill == initial state, which is correct. |
| `apply_char_sheet` | No change — char sheets only override player fields; containment is untouched. |

Because `load_all` always rebuilds, mutation code is free to delete keys when a count
reaches 0 (natural); `load_save` only backfills on *absence*, never on emptiness, so an
emptied room in a real save is preserved.

### 3. Mutations flow through `HardStateChanges` (the missing piece)

The codebase pattern is: resolvers build a `HardStateChanges`, the engine applies it
via `StateManager.apply_hard_changes`. Resolvers do not mutate `hard.*` directly
(the rare exceptions are `hard.game_over` and the follower-`following` flag). To move
containment mutations through the same pipe, `HardStateChanges` gains four fields:

```python
room_contains_added:   Dict[str, Dict[str, int]] = Field(default_factory=dict)  # {room_id: {eid: count}}
room_contains_removed: Dict[str, Dict[str, int]] = Field(default_factory=dict)
entity_contains_added:   Dict[str, Dict[str, int]] = Field(default_factory=dict)  # {container_eid: {eid: count}}
entity_contains_removed: Dict[str, Dict[str, int]] = Field(default_factory=dict)
```

- `merge()` sums counts for matching keys (like `inventory_added`).
- `has_changes()` returns True if any of the four is non-empty.
- `apply_hard_changes()` applies them with the validation in §4 and records the
  resulting state-change events alongside the existing item-acquired/lost events.

The transfer resolver records:
- **Take** of a hard item: `inventory_added[item]=count` plus
  `room_contains_removed[room_id][item]=count` *or*
  `entity_contains_removed[container_id][item]=count`, depending on where the item
  lives. A new helper `_locate_world_item(hard, room_id, item) -> ("room", room_id) |
  ("entity", container_id) | None` determines the source. Soft items record no
  containment delta (they are not in the runtime maps).
- **Give** of a hard item: `inventory_removed[item]=count` plus
  `room_contains_added[room_id][item]=count` (when `target_is_room`) or
  `entity_contains_added[target_id][item]=count` (when `target_is_entity`).

### 4. Non-stackable constraints (safety), enforced at three layers

The normalised `Dict[str, int]` form makes stacking universal. Safety invariants are
enforced at the point of change:

| Rule | Where enforced |
|------|----------------|
| Non-item entities (NPCs, features) → count must be 1 | Corpus validation (`validate_cross_references`) |
| Non-stackable item → count must be 1 in every location | Corpus validation (initial) **and** `apply_hard_changes` (runtime add) **and** transfer resolver pre-check |
| Stackable item → resulting count bounded by `max_stack` if set | `apply_hard_changes` (runtime add) |
| Self-referencing `entity_contains` (an entity whose `contains` includes itself) → forbidden | Corpus validation |
| Player entity must never appear as a contained key | Corpus validation |

`apply_hard_changes` validates each containment delta: the target room/container and
item entity must exist in the corpus; non-stackable items may not exceed count 1 in the
resulting location; stackable items respect `max_stack`. Failures raise `ValueError`
and abort the whole batch (matching the atomic style of the existing pre-validation).

These constraints are **minimalist**: they prevent nonsense while leaving authors free
to nest non-stackable entities arbitrarily (a chest containing a sword, a sword with no
stacking semantics, etc.).

### 5. Scope boundary: reactions do NOT spawn world items (yet)

The `Result` model only supports inventory mutation (`add_item` / `remove_item`); it
has no field for "spawn item N into room R." Adding world-side spawn/remove reactions
is **out of scope** for this change and is left for future work. The runtime maps are
mutated only by (a) initialisation from corpus and (b) take/give transfers. Any plan
prose implying otherwise is aspirational, not part of this change.

---

## Detailed consumer migration

Every code site that reads `room.contains` / `entity.contains` from the corpus must
switch to the runtime maps (or, for corpus-validation-only sites, to `.contains_map`).
Line numbers are accurate against the current `main`; they will drift during
implementation but are kept here as anchors. **This is the complete inventory** — it
was verified by grepping for `.contains` across `mgmai/`.

### Assembler + briefing

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `context/assembler.py` | 86 | `for eid in room.contains:` | `for eid in hard.room_contains.get(room_id, {}):` |
| `context/assembler.py` | 94 | `if entity.type=="item" and (eid in hard.player.inventory or eid in hard.player.equipped): continue` | **Fix invisible-stacks:** hide if `eid in equipped`; hide if `eid in inventory and not _is_stackable(eid, corpus)`; otherwise show with remaining count. Set `count=` on the `BriefingEntity` (see below). |
| `context/assembler.py` | 111-122 | `BriefingEntity(...)` no count | add `count=hard.room_contains.get(room_id, {}).get(eid, 1)` |
| `context/assembler.py` | 120 | `build_contains(entity, hard, corpus, entity_id=eid)` | unchanged signature (it reads runtime map internally) |
| `context/assembler.py` | 144 | `set(room.contains)` | `set(hard.room_contains.get(room_id, {}))` |
| `engine/utils.py` | 102-142 | `build_contains(entity, ...)` iterates `entity.contains` | iterate `hard.entity_contains.get(entity_id, {})` |
| `engine/utils.py` | 124 | `for cid in entity.contains:` | `for cid in hard.entity_contains.get(entity_id, {}):` |
| `engine/utils.py` | 131-135 | hide item if `cid in inventory or cid in equipped` | **Fix invisible-stacks** (same rule as assembler.py:94); set `count=` on each `BriefingContainsEntry` from `hard.entity_contains[entity_id][cid]` |
| `engine/utils.py` | 136-141 | `BriefingContainsEntry(...)` no count | add `count=...` |
| `models/briefing.py` | 34-39 | `BriefingContainsEntry` | add `count: int = 1` |
| `models/briefing.py` | 42-52 | `BriefingEntity` | add `count: int = 1` (so room-level stackable items show their remaining count) |
| `engine/engine.py` | 679 | `_build_room_after()` `for eid in room.contains:` | `for eid in hard.room_contains.get(room_id, {}):` |
| `engine/engine.py` | 687 | hide item if `eid in inventory or eid in equipped` | **Fix invisible-stacks** (same rule); set `count=` on the `BriefingEntity` |

Note: `_is_stackable` currently lives as a private in `engine/resolver.py`. Promote it
to `engine/utils.py` so the assembler and engine can import it.

### Transfer resolver (take / give)

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `engine/resolver.py` | 69-81 | `_merge_item_counts` | unchanged |
| `engine/resolver.py` | 84-94 | `_is_stackable` | unchanged (but see promotion note above) |
| `engine/resolver.py` | 277 | `for eid in room.contains:` (examine soft-item search) | `for eid in hard.room_contains.get(room_id, {}):` — **previously omitted; crashes on dict elements if not migrated** |
| `engine/resolver.py` | 287 | `for eid in room.contains:` (locate soft-item source) | `for eid in hard.room_contains.get(room_id, {}):` — **previously omitted; same crash** |
| `engine/resolver.py` | 486 | `target_npc not in room.contains` (talk target check) | `target_npc not in hard.room_contains.get(room_id, {})` — **previously omitted** |
| `engine/resolver.py` | 615 | `target_id in room.contains` | `target_id in hard.room_contains.get(room_id, {})` |
| `engine/resolver.py` | 667-708 | `available_pool: set[str]` from `room.contains` + `ent.contains` | `available_pool: dict[str, int]` from `hard.room_contains[room_id]` + `hard.entity_contains`; nested container contents counted; soft items added with count 1 |
| `engine/resolver.py` | 715-778 | take: `item in available_pool` (set membership) | take: `available_pool.get(item, 0) >= count`; on success record `inventory_added` + `room_contains_removed`/`entity_contains_removed` via `_locate_world_item` |
| `engine/resolver.py` | 637-665 | give: removes from inventory only | give: also record `room_contains_added` (target_is_room) or `entity_contains_added` (target_is_entity) |
| `engine/resolver.py` | 697,703 | `claimed_entities` from `ent.contains` | from `hard.entity_contains.get(eid, {})` |
| `engine/resolver.py` | 721,727 | closed-container check reads `ent.contains` | reads `hard.entity_contains.get(eid, {})` |
| `engine/resolver.py` | 785 | surfacing soft items iterates `room.contains` | iterates `hard.room_contains.get(room_id, {})` |
| `engine/resolver.py` | 1519-1526 | `_find_entity_in_room(entity_id, room, corpus)` checks `entity_id in room.contains` | **Change signature** to `_find_entity_in_room(entity_id, room_id, hard, corpus)`; checks `entity_id in hard.room_contains.get(room_id, {})` |
| `engine/resolver.py` | 1529-1539 | `_find_entity_in_room_followers` calls `_find_entity_in_room` | update call to new signature |

### Engine

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `engine/engine.py` | 610 | `for eid in room.contains:` (soft_item validation) | `for eid in hard.room_contains.get(room_id, {}):` |
| `engine/engine.py` | 648 | `ent_id not in room.contains` (contradiction check) | `ent_id not in hard.room_contains.get(room_id, {})` |
| `engine/engine.py` | 766,817 | will_reveal / attitude iterate `room.contains` for NPC ids | iterate `hard.room_contains.get(room_id, {})` |

### Event bus

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `engine/event_bus.py` | 79 | `set(room.contains)` | `set(hard.room_contains.get(room_id, {}))` |

### Dialogue

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `engine/dialogue.py` | 128 | `npc_id in new_room_data.contains` (room-change exit check) | `npc_id in hard.room_contains.get(new_room, {})` — **previously omitted** |

### State manager

| File | Line(s) | Current | Replacement |
|------|---------|---------|-------------|
| `state/manager.py` | 254 | `_check_ids(room.contains, self.corpus.entities, "entity")` | `_check_ids(room.contains_map.keys(), self.corpus.entities, "entity")` (corpus validation — uses `.contains_map`, not the raw list) |
| `state/manager.py` | 197-307 | `validate_cross_references` | add count-constraint checks from §4 (non-item count==1, non-stackable count==1, self-reference) over each room/entity `.contains_map` |
| `state/manager.py` | 87-113 | `load_all` | after loading, call `_init_contains_from_corpus()` (always rebuild) |
| `state/manager.py` | 427-459 | `load_save` | inspect raw `data["hard"]`; if `"room_contains"` absent, call `_init_contains_from_corpus()` |
| `state/manager.py` | 524-619 | `apply_hard_changes` | apply the four new containment-delta fields with §4 validation |
| `state/manager.py` | new | — | add `_init_contains_from_corpus()` helper |

### Models

| File | Change |
|------|--------|
| `models/corpus.py` | `Room.contains` → `List[Union[str, Dict[str, int]]]` + normalising `@model_validator(mode="after")` → private `_contains_map` + `.contains_map` property |
| `models/corpus.py` | `Entity.contains` → same |
| `models/hard_state.py` | Add `room_contains: dict[str, dict[str, int]]` and `entity_contains: dict[str, dict[str, int]]` (both `default_factory=dict`) |
| `models/briefing.py` | `BriefingContainsEntry` gains `count: int = 1` |
| `models/briefing.py` | `BriefingEntity` gains `count: int = 1` |
| `models/actions.py` | `HardStateChanges` gains the four containment-delta fields; `merge()` and `has_changes()` updated |

### Templates (cosmetic)

| File | Change |
|------|--------|
| `templates/ruling.j2` | Line ~124 references `rubbish_pile.contains = [{"id":"toenail_sword", ...}]` in an example string; update to include `count` now that `BriefingContainsEntry` carries it. Non-blocking. |

---

## Work items (implementation order)

### Phase A — Models

**A1.** `mgmai/models/corpus.py` — `Room.contains` and `Entity.contains`
Change declared type to `List[Union[str, Dict[str, int]]]`. Add
`@model_validator(mode="after")` that builds a private `_contains_map: dict[str, int]`
(summing counts if an id appears more than once) and exposes a read-only
`.contains_map` property. Keep the raw `contains` list as-is for JSON round-trip. Add
a docstring stating the hard rule: runtime code must use `.contains_map` or the
runtime maps, never the raw list.

**A2.** `mgmai/models/hard_state.py`
Add `room_contains` and `entity_contains` with `default_factory=dict`.

**A3.** `mgmai/models/briefing.py`
Add `count: int = 1` to **both** `BriefingContainsEntry` and `BriefingEntity`.

**A4.** `mgmai/models/actions.py`
Add the four containment-delta fields to `HardStateChanges`. Update `merge()` to sum
matching keys (nested dict sum). Update `has_changes()` to consider them.

### Phase B — State manager

**B1.** `mgmai/state/manager.py` — corpus validation
Migrate `_check_ids(room.contains, ...)` to `room.contains_map.keys()`. Add the §4
corpus-side checks over each room/entity `.contains_map`:
- Non-item entity with count > 1 → error.
- Non-stackable item with count > 1 → error.
- Self-referencing `entity_contains` cycle → error.
- Player entity appearing as a contained key → error.

**B2.** `mgmai/state/manager.py` — initialisation
Add `_init_contains_from_corpus()`: iterate all corpus rooms and entities, populate
`hard.room_contains` / `hard.entity_contains` from each `.contains_map`. Call it
unconditionally at the end of `load_all`. In `load_save`, inspect the raw save dict
and call it only when `"room_contains"` is absent.

**B3.** `mgmai/state/manager.py` — apply containment deltas
Extend `apply_hard_changes` to apply the four new `HardStateChanges` fields:
- `room_contains_added` / `entity_contains_added`: increment the target map,
  enforcing non-stackable ≤ 1 and `max_stack` on the resulting count.
- `room_contains_removed` / `entity_contains_removed`: decrement; delete the key when
  the count reaches 0 (safe because `load_save` only backfills on absence, and
  `load_all` always rebuilds).
- Pre-validate all deltas up front (entity/room existence, item type) and raise
  atomically, matching the existing style.

### Phase C — Consumer migration

**C1.** `mgmai/context/assembler.py` + `mgmai/engine/utils.py` + `mgmai/engine/engine.py`
Switch all `room.contains` / `entity.contains` reads to the runtime maps. `build_contains()`
reads from `hard.entity_contains` and includes counts in `BriefingContainsEntry`.
Room-level entities get `count` on `BriefingEntity` from `hard.room_contains`. Apply the
invisible-stacks fix at all three filter sites (assembler.py:94, utils.py:131-135,
engine.py:687): hide equipped items; hide inventory items only when non-stackable; show
partially-held stackable items with their remaining world count. Promote `_is_stackable`
to `engine/utils.py` and import it where needed.

**C2.** `mgmai/engine/resolver.py` — `resolve_transfer()`
- `available_pool` becomes `dict[str, int]` (hard items from runtime maps with counts;
  soft items with count 1).
- Take path: validate `count <= available_pool.get(item, 0)`; on success record
  `inventory_added` + the matching `*_contains_removed` delta via `_locate_world_item`.
- Give path: record `inventory_removed` + `room_contains_added` or `entity_contains_added`.
- Add `_locate_world_item(hard, room_id, item) -> ("room", room_id) | ("entity", container_id) | None`.
- Update `_find_entity_in_room` signature to `(entity_id, room_id, hard, corpus)`;
  update `_find_entity_in_room_followers` and its callers (`resolve_examine`,
  `resolve_interact`).
- Migrate the previously-omitted examine/talk sites (lines 277, 287, 486).

**C3.** `mgmai/engine/event_bus.py`
Build `entity_ids` from `hard.room_contains.get(room_id, {})`.

**C4.** `mgmai/engine/dialogue.py`
Migrate line 128 to `hard.room_contains.get(new_room, {})`.

### Phase D — Schema docs

**D1.** `schema/corpus.md`
- Document `contains` as accepting mixed strings and `{id: count}` objects.
- Clarify: `contains` describes initial placement only; runtime containment lives in
  hard state.
- Document the §4 non-stackable constraints.

**D2.** `schema/hard-state.md`
- Document `room_contains` and `entity_contains` in the top-level structure and add a
  dedicated section (initialisation rules from §2, mutation rules from §3, the
  delete-on-zero convention).
- Add the two new write operations to the "Engine write operations" table
  (`add_room_contains`, `remove_room_contains`, `add_entity_contains`,
  `remove_entity_contains`).

**D3.** `schema/actions.md`
- Update the transfer section: available pool now has quantities; taking decrements the
  runtime map; giving places items back into a mutable world-side container.

**D4.** `templates/ruling.j2`
- Update the `contains` example to include `count`.

### Phase E — Tests

**E1.** Corpus fixtures: the existing list format stays valid; add mixed-format fixtures
(`["goblin", {"gold_coin": 50}]`) and assert `.contains_map` normalises correctly.

**E2.** Transfer tests: take 50 gold coins from a room → verify 50 removed from
`hard.room_contains`; take 50 more → "not enough" error. Give 10 coins → verify
`hard.room_contains` (or `entity_contains`) incremented.

**E3.** Assembler/briefing tests: verify `BriefingEntity.count` and
`BriefingContainsEntry.count` carry the remaining world count; verify partial-stack
visibility (room has 50 coins, player holds 30, briefing shows 20 remaining in room);
verify a fully-depleted stackable item (0 remaining) is hidden.

**E4.** State manager tests:
- `load_all` rebuilds the maps from corpus (existing adventure `hard-state.json`
  without the keys loads cleanly and rooms are populated).
- `load_save` with a save that has the keys preserves mutated counts; `load_save`
  with a legacy save (no keys) backfills from corpus.
- `apply_hard_changes` rejects non-stackable > 1 and `max_stack` overflow on world
  containers.
- Save/load round-trip preserves mutated counts.

**E5.** Regression tests: examine a soft item in a room that also contains a stacked
item (covers the previously-crashing resolver.py:277/287 path); talk to an NPC in a
room with a stacked item (covers 486); room-change dialogue exit check (covers
dialogue.py:128).

---

## Open questions for review

- **Container nesting depth.** `entity_contains` is a flat map keyed by container id,
  so arbitrary nesting works in principle, but `build_contains` and `available_pool`
  only look one level deep (room → entity → contains). Deeper nesting remains
  unsupported as today. Acceptable? (Pre-existing limitation, not a regression.)
- **Giving to a non-container NPC.** Putting a given item into `entity_contains[npc]`
  makes it surface via `build_contains`. Is that the desired visibility, or should
  given-to-NPC items be hidden until the NPC is examined/killed? Current plan: surface
  them (matches "the goblin is now holding your sword").
