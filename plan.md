# Plan: `entity.location` — engine-managed placement as a derived state field

## Background and motivation

Entities have several reserved boolean state fields that control engine
behaviour: `alive`, `fled`, `following`, `hidden`. Each makes the engine
treat the entity as "not really present" for some purpose.

Of these, `fled` is the most questionable. It means "this entity has left
the scene," but the entity **stays in `room_contains`** — it is a ghost in
the room, ignored by combat and reactions via two hard-coded checks
(`combat.py:243`, `event_bus.py:91`). This is a half-measure: the entity
is conceptually gone but structurally still there. Worse, there is no way
for a `Result` to actually move an entity between rooms; the containment
deltas `room_contains_added` / `room_contains_removed` /
`entity_contains_added` / `entity_contains_removed` exist on
`HardStateChanges` (`actions.py:212-215`) but are not exposed through
`Result`, and the runtime validator `_validate_contains_delta`
(`manager.py:1100`) rejects every non-`item` entity unconditionally — so
even an engine-internal delta cannot move an NPC or feature at runtime.

Meanwhile, `set_player_location` on `Result` (`corpus.py:182`) lets
authors move the player. There is no equivalent for any other entity.

This plan introduces `location` as a reserved, **engine-managed, derived**
entity state field. It applies to **any singleton entity** — NPCs,
features, and non-stackable items — not just NPCs. Authors set it through
the existing `set_entity_state` mechanism; the engine intercepts it and
applies a **direct placement** (set-semantics: remove from all current
containers, place in the target). The value is derived from the
containment maps at query time, so there is a single source of truth. This
subsumes `fled`, enables runtime entity movement for the first time, and
requires no new fields on `Result`.

## Design

### The `location` state field

`location` is a reserved string-or-null state field on entities. Unlike
`alive`, `fled`, `following`, `hidden`, and `current_hp` — which are
*declared* in an entity's `state_fields` (and merely receive engine-supplied
defaults via `RESERVED_STATE_FIELD_DEFAULTS` or special-casing in
`manager.py:290-295`) — `location` is **not declared and not stored** in
`entity_states`. It is always derived from `room_contains` and
`entity_contains`. This makes it unique among reserved fields: a pure
projection of containment, never a stored value.

The value uses a qualified prefix to distinguish container types:

| Value | Meaning |
|-------|---------|
| `"room:<room_id>"` | Entity is in the given room |
| `"entity:<entity_id>"` | Entity is inside the given container entity |
| `null` | Entity is not contained anywhere (outside the adventure) |

`null` is the "nowhere" sentinel, preferred over `""` because it aligns
with JSON-patch semantics: in `set_entity_state`, a field set to `null`
means "set to null," while an absent field means "don't change."

### Scope: singleton entities only

`location` models **"this entity is here"** — a set-semantics that assumes
one entity, one container. That holds for singleton entities: NPCs,
features, and non-stackable items (each present at count 1 in at most one
container).

It does **not** hold for stackable items, whose quantities may be split
across many containers. The count-delta mechanism (`room_contains_added`
etc.) is the correct model for stackable quantity moves ("take 3 of 10
coins," split/merge stacks, `max_stack` enforcement) and is retained
unchanged for that purpose. `location` rejects stackable items at
validation time; a future, separate API may expose stackable quantity
moves through `Result` (out of scope here).

Non-stackable items sit in an overlap: they are singletons (so `location`
covers them) but they are also `item`-typed, so the count-delta validator
(`manager.py:1113`) accepts them too. For non-stackable items, `location`
is the **preferred** author-facing path; the count-delta fields for
non-stackable items are legacy/engine-internal. The overlap is not left
ambiguous — a single change may not use both paths on the same entity (see
"Validation of placements").

This still covers the motivating use cases: an NPC leaving the scene, a
treasure chest (feature) appearing in a room, a unique quest item
relocating from a pedestal to a container, a goblin hiding inside a
barrel.

### Reading `location`

Conditions can test entity location:

```
entity:spider.location == "room:cellar"
entity:spider.location != null
```

The engine resolves `location` via a helper that derives the value from
containment at query time (no separate storage):

```python
def get_entity_location(entity_id, hard, corpus):
    # Following NPCs are dynamically injected wherever the player is; they
    # are not tracked in room_contains.  Synthesize their location so
    # conditions see them with the player.
    st = hard.entity_states.get(entity_id, {})
    if st.get("following") is True:
        return f"room:{hard.player.location}"
    for room_id, contents in hard.room_contains.items():
        if entity_id in contents:
            return f"room:{room_id}"
    for cont_id, contents in hard.entity_contains.items():
        if entity_id in contents:
            return f"entity:{cont_id}"
    return None
```

The `following` short-circuit is required because following NPCs live
**outside** `room_contains` at runtime (see "Interaction with `following`"
below); without it their `location` would read as `null` even though they
are visibly with the player.

### Setting `location`

Authors set location via the existing `set_entity_state` mechanism:

```json
"set_entity_state": { "spider": { "location": "room:tunnel" } }
```

Or to remove the entity from containment entirely:

```json
"set_entity_state": { "spider": { "location": null } }
```

Internally, `location` is **not** translated into the four count-delta
fields. Instead it is intercepted early in `apply_hard_changes` and
recorded on a new **direct-placement** field, `entity_placements`, with
set-semantics. The `location` key is stripped from the dict before the
`entity_states` merge (it is never stored there). The placement is then
applied by removing the entity from all current containers and placing it
in the target (count 1).

#### Why placement, not deltas

Routing `location` through `room_contains_added` / `_removed` would be
wrong for three reasons:

1. **Merge idempotency.** `HardStateChanges.merge` *sums* containment
   counts (`_merge_nested_counts`, `actions.py:267-278`). Two co-occurring
   reactions both placing `spider → room:B` would merge to
   `room_contains_added[B][spider] = 2` and a removal of 2, hitting
   `_validate_contains_delta`'s "only 1 present" guard (`manager.py:1127`)
   or leaving a count-2 ghost. `entity_placements` merges by
   **dict-overwrite** (last wins) — idempotent, which is the correct
   set-semantics.
2. **Set vs. count semantics.** `location` is declarative ("the entity is
   here"); deltas are imperative count arithmetic. The engine must
   discover the entity's current container to emit the right removal
   anyway, so the delta is a needless, error-prone indirection.
3. **The "one entity, one container" invariant is not globally enforced.**
   Nothing in `_validate_contains_map` (`manager.py:907`) or
   `_apply_contains_deltas` prevents an entity_id from appearing in
   multiple containers. Placement *enforces* the invariant by
   construction (remove from all, place in one); deltas inherit the
   divergence.

The count-delta fields are retained for stackable item operations, where
they are fit for purpose. Placement writes to the **same**
`room_contains` / `entity_contains` maps via a dedicated apply method, so
the maps remain the single source of truth and reads (already map-based)
stay consistent with writes.

### Initialisation from corpus

`_init_contains_from_corpus` (`manager.py:944`) already builds
`room_contains` and `entity_contains` from the corpus. `location` needs no
separate initialisation — it is derived from containment. The corpus
validator `_validate_contains_map` already permits any non-`player` entity
at count 1 in both room and entity containers (`manager.py:924`), so NPCs,
features, and items may all be pre-placed. `location` simply makes them
movable at runtime.

### Deprecation of `fled`

`fled: true` is replaced by `location: null` (or, more generally,
`location: "room:<dest>"` to flee *to* somewhere — a capability `fled`
never had). The two engine checks that currently test `fled` are removed,
because a `null`-location entity is already excluded by the presence
checks that derive from containment:

- `combat.py:243` — `st.get("fled") is True` in `resolve_combat_enemies`.
  With `location: null`, the entity is not in `room_contains` for the
  current room, so it is already excluded by the presence check at
  `combat.py:236-241`.
- `event_bus.py:91` — `entity_state.get("fled") is True` in
  `find_matching_reactions`. The entity is not in `entity_ids` (populated
  from `room_contains` at `event_bus.py:76-79`) when it has no location.

This is **more correct** than `fled`: `fled` left a ghost skipped only in
the player's current room, whereas `location: null` actually removes the
entity, so it is gone when the player later returns.

`fled` is removed from `RESERVED_STATE_FIELD_DEFAULTS` (`corpus.py:34`).
This is largely cosmetic — a declared `fled` without an explicit `initial`
still resolves to `False` via the boolean type-default (`manager.py:302`)
— but it produces a "no explicit initial" warning for adventures still
declaring `fled`, acting as a deprecation nudge, and it removes the field
from the documented reserved set.

Authors who previously wrote:

```json
"set_entity_state": { "spider": { "fled": true } }
```

now write:

```json
"set_entity_state": { "spider": { "location": null } }
```

and instead of `entity:spider.fled == true` they check
`entity:spider.location == null`.

> **Migration scope.** Many `fled` strings in the codebase are unrelated
> *flags* (`spider_fled`, `creature_fled`, `ambush_fled`) or narrative
> text, not the entity-state field. All deprecation edits must be scoped
> to the entity-state field `fled` only; flag and narrative references
> are left untouched.

### Interaction with other reserved fields

- **`alive`** — orthogonal. A dead entity has a location (its corpse is
  in the room). `alive: false` does not change containment.
- **`hidden`** — orthogonal. A hidden entity is in the room but
  invisible. `hidden: true` does not change containment; the engine
  omits hidden entities from scene descriptions but they remain in
  `room_contains`.
- **`following`** — interacts, and the interaction is defined to match
  the existing following architecture (see below).

#### Interaction with `following`

Following NPCs are **not** tracked in `room_contains`. They are
dynamically injected wherever the player is, via `get_following_npc_ids` /
`inject_following_npcs` (`utils.py:60-112`), consumed by display
(`engine.py:770`), combat (`combat.py:206`), reactions (`event_bus.py:80`),
and dialogue (`dialogue.py:132`). Consequently:

- **Read side:** `get_entity_location` synthesizes
  `room:<player.location>` for following NPCs (see the helper above).
  Without this, a following NPC's `location` would read as `null` (or as
  a stale `room:<origin>` if it was pre-placed in a room's `contains`).
- **Write side — setting `location`:** placing a following entity (to any
  value, including `null`) **clears `following`**. Pinning an entity to a
  location is incompatible with dynamic following; forcing `following`
  false ensures the derived read matches author intent (otherwise
  `location: null` would still read as `room:<player>` via the following
  short-circuit).
- **Write side — setting `following`:** no containment side-effect.
  Setting `following: true` does not move the entity; injection handles
  its presence, and any stale `room_contains` entry is harmless (display,
  combat, and reactions all union `follower_ids` with `room_contains` and
  deduplicate). It is corrected on the next explicit placement, whose
  remove-from-all step clears the stale entry.
- **Precedence:** if both `location` and `following: true` are set in the
  same change, `location` wins — the entity is placed and `following` is
  forced false.

This drops the original draft's "setting `following` on a null-location
NPC brings it to the player's room" rule: that would have placed the NPC
into `room_contains[player_room]`, conflicting with the injection
architecture, and is unnecessary since injection already makes the NPC
present.

### Containment model

The existing two-level containment model is unchanged:

- `room_contains: {room_id: {entity_id: count}}` — top-level room membership
- `entity_contains: {container_id: {entity_id: count}}` — nested containment

`location` maps to whichever level the entity is currently in. Placement
writes count 1 into the appropriate map and removes the entity from all
others. The count-delta mechanism continues to serve stackable item
quantity moves. The two apply paths write the same maps; within one
`apply_hard_changes`, deltas are applied first and placements last.

The two paths **overlap** for non-stackable items, which the count-delta
validator also accepts (`manager.py:1113`). Rather than leave the outcome
to apply-order and merely discourage it, a single `apply_hard_changes`
that targets the **same entity** via both `entity_placements` and any of
the four containment-delta fields is **rejected at validation time** (see
"Validation of placements"). This removes the undefined-conflict seam by
construction; there is never a "which path wins" question to reason about.

The qualified prefix (`"room:x"` / `"entity:y"`) is required when
*setting* location. When *reading* location, the engine resolves the
prefix automatically from the containment maps.

### Validation of placements

Placement validation mirrors `_validate_contains_map` (the corpus
validator), **not** `_validate_contains_delta` (the runtime delta
validator). This is what resolves the showstopper: `_validate_contains_delta`
rejects all non-items (`manager.py:1100`), which would block the primary
use case (moving NPCs/features). Placement has its own validator that
permits any non-`player` singleton in both room and entity containers,
matching what the corpus already allows:

- entity exists and is not the `player`;
- entity is not a stackable item (singleton restriction);
- target room or container entity exists;
- no self-containment (`entity:x` cannot contain `x`).

This also closes an existing inconsistency: the corpus permitted non-items
in entity containers (e.g. a goblin in a barrel) but the runtime delta
validator did not. Placement makes runtime behaviour match the corpus.

The singleton/existence/self-containment predicates shared with the corpus
validator (`_validate_contains_map`, `manager.py:907`) are factored into a
single helper (`_validate_singleton_target`) so the corpus and placement
validators cannot drift. `_validate_placements` and `_validate_contains_map`
both call it; only their count/quantity rules differ.

#### Cross-path conflict rejection

Because placement and count-deltas write the same maps and overlap for
non-stackable items, `apply_hard_changes` also rejects any change that
targets the **same entity** through both mechanisms in one call:

- for each `eid` in `entity_placements`, if `eid` appears in any of
  `room_contains_added` / `room_contains_removed` /
  `entity_contains_added` / `entity_contains_removed`, emit an error.

This is a validation error (raised alongside the others at
`manager.py:1300`), so the overlap can never resolve by apply-order. There
is exactly one path per entity per change.

## Qualms and caveats

### Layering: `set_entity_state` and `following` gain containment side effects

Today, applying `set_entity_state` is a pure dict merge into
`entity_states` (`manager.py:1333-1336`). After this change, the reserved
`location` key triggers containment mutations, and setting `location` on a
following entity also forces `following: false`. This is a layering
violation: entity state and containment are currently separate concerns in
`HardGameState`.

The mitigation is to intercept `location` (and the `following` override)
early in `apply_hard_changes`, before the declared-field validation loop
and before the dict merge, translating `location` into a placement entry
and stripping it from the merge dict. The interception is a small,
well-documented special case. Authors and future maintainers should be
aware that `set_entity_state` is no longer a pure merge for the reserved
`location` key.

### `following` read synthesis is a special case

`get_entity_location` special-cases following NPCs to synthesize
`room:<player.location>`. This is necessary because following NPCs live
outside containment, but it means `location` is not a pure containment
projection for them. The rule is simple and documented, but it must be
kept in sync if the following mechanism changes.

### `entity_contains` authoring is new ground

Currently `entity_contains` is populated only from the corpus at load time
and (internally) via count-deltas for items. `location: "entity:chest_1"`
is the first author-facing path to move an entity into another entity's
containment at runtime, and the first path to place non-items (NPCs,
features) into entity containers at runtime. The corpus validator already
permits this; placement validation mirrors it. Display gating (a
`container`-tagged entity whose `open` is not true hides its contents —
`utils.py:131-134`) is a display concern and is unaffected.

### Qualified prefix is verbose

`"room:cellar"` is more typing than `"cellar"`. The alternative — looking
up the ID in both `corpus.rooms` and `corpus.entities` — is ambiguous if
an ID exists in both namespaces. The prefix is the safe choice; authors
who find it verbose can use short room IDs.

### Save compatibility (required, not deferred)

A save file from a `fled`-era version may have `fled: true` in
`entity_states` while the entity is still in `room_contains`. Once the
`fled` checks are removed, such an entity would become a present ghost
with no check to skip it. Migration on load is therefore **required**: for
each entity with a `fled` key, if it is `true`, remove the entity from all
containment maps; then delete the `fled` key from `entity_states` in all
cases. This runs in `load_save` after the hard state is loaded.

## Implementation phases

### Phase A: Model and schema changes

**A1. `RESERVED_STATE_FIELD_DEFAULTS` (`corpus.py:32-38`)**

Remove `"fled": False`. Do not add a `location` entry — it is derived, not
stored.

**A2. `HardStateChanges.entity_placements` (`actions.py`)**

Add a new field with set-semantics:

```python
# Author-facing entity placements derived from set_entity_state "location".
# {entity_id: "room:<id>" | "entity:<id>" | None}.  Merged by dict-overwrite
# (last wins), unlike the count-summed containment deltas below.
entity_placements: Dict[str, Optional[str]] = Field(default_factory=dict)
```

- In `merge`: `self.entity_placements.update(other.entity_placements)`.
- In `has_changes`: add `or bool(self.entity_placements)`.

**A3. Schema documentation (`schema/corpus.md`, `schema/hard-state.md`)**

- Add `location` to the reserved state fields table, with type
  `string|null`, value derived from containment, the qualified syntax,
  and the singleton-only scope (NPCs, features, non-stackable items).
- Remove `fled` from the table.
- Document `null` as the "not contained anywhere" sentinel.
- Note that `location` is derived from `room_contains` /
  `entity_contains`, not stored in `entity_states`, and is the only
  reserved field that is undeclared.

**A4. Events documentation (`schema/events.md`)**

- `combat.ended` reason `"fled"` — note this is emitted when the player
  successfully flees combat (documented but not implemented; separate
  issue).
- Remove references to `fled` as an entity state field.

**A5. Scenario generation documentation (`schema/scenario-generation.md`)**

- Update examples that use `set_entity_state: {"spider": {"fled": true}}`
  to `{"spider": {"location": null}}` (and show `location: "room:..."`
  for flee-to-somewhere).
- Update condition examples from `entity:spider.fled == true` to
  `entity:spider.location == null`.

### Phase B: Engine changes

**B1. `location` interception in `apply_hard_changes`
(`state/manager.py:1231-1354`)**

Add a pre-processing step that runs **before** the declared-field
validation loop (`manager.py:1255-1262`). This ordering is essential:
`location` is a reserved, undeclared field, so the declared-field check
would otherwise reject it. The interception pops `location` out of the
change dict (so validation and the merge never see it) and records a
placement:

```python
for entity_id, entity_changes in changes.entity_state_changes.items():
    if "location" not in entity_changes:
        continue
    loc = entity_changes.pop("location")          # strip before merge
    changes.entity_placements[entity_id] = loc
    # Setting location (any value, incl. null) on a following entity
    # stops the follow, so the derived read matches author intent.
    cur = self.hard_state.entity_states.get(entity_id, {})
    if cur.get("following") is True or entity_changes.get("following") is True:
        entity_changes["following"] = False       # location wins
```

**B2. Placement validation (`state/manager.py`)**

Add `_validate_placements`, called in the pre-validation block alongside
the existing validators. Factor the singleton/existence/self-containment
predicates shared with `_validate_contains_map` into a helper
`_validate_singleton_target(eid, loc)` that both validators call; only the
count-vs-set rules stay path-specific. `_validate_placements` mirrors
`_validate_contains_map`:

```python
def _validate_placements(self, placements):
    errors = []
    for eid, loc in placements.items():
        ent = self.corpus.entities.get(eid)
        if ent is None:
            errors.append(f"No matching entity: {eid}"); continue
        if ent.type == "player":
            errors.append(f"Cannot set location on player entity '{eid}'"); continue
        if ent.type == "item" and "stackable" in ent.tags:
            errors.append(f"'location' is for singleton entities; "
                          f"'{eid}' is stackable"); continue
        if loc is None:
            continue                                # removal is always valid
        prefix, _, target = loc.partition(":")
        if prefix == "room":
            if target not in self.corpus.rooms:
                errors.append(f"No matching room: {target}")
        elif prefix == "entity":
            if target not in self.corpus.entities:
                errors.append(f"No matching entity: {target}")
            elif target == eid:
                errors.append(f"Entity '{eid}' cannot contain itself")
        else:
            errors.append(f"Invalid location value: {loc}")
    return errors
```

**B2a. Cross-path conflict rejection (`state/manager.py`)**

In the same pre-validation block, reject a change that targets the same
entity via both placement and any containment delta:

```python
delta_targets = set()
for m in (changes.room_contains_added, changes.room_contains_removed,
          changes.entity_contains_added, changes.entity_contains_removed):
    for entries in m.values():
        delta_targets.update(entries)
for eid in changes.entity_placements:
    if eid in delta_targets:
        errors.append(f"Entity '{eid}' is moved by both 'location' and a "
                      f"containment delta in the same change; use one path")
```

**B3. Placement application (`state/manager.py`)**

Add `_apply_placements`, called after `_apply_contains_deltas`
(`manager.py:1354`). Same-entity conflicts are now rejected in
pre-validation (B2a), so apply-order no longer resolves any conflict;
placements-last is retained only for deterministic, self-consistent
output:

```python
def _apply_placements(self, placements):
    hard = self.hard_state
    for eid, loc in placements.items():
        # Set-semantics: remove from all current containers first.
        for contents in hard.room_contains.values():
            contents.pop(eid, None)
        for contents in hard.entity_contains.values():
            contents.pop(eid, None)
        if loc is None:
            continue
        prefix, _, target = loc.partition(":")
        if prefix == "room":
            hard.room_contains.setdefault(target, {})[eid] = 1
        elif prefix == "entity":
            hard.entity_contains.setdefault(target, {})[eid] = 1
```

> A reverse index (`entity_id → container_id`) would make the
> remove-from-all step O(1) instead of scanning every container. This is
> a future optimisation; the scan is fine for current container counts.

**B4. Location derivation for conditions (`engine/conditions.py`,
`engine/utils.py`)**

Add `get_entity_location` (see "Reading `location`" above) to
`engine/utils.py` alongside `get_following_npc_ids`.

Wire it into **both** condition-evaluation paths for the `entity:` domain:

1. `evaluate_condition_string` (`conditions.py:102-116`). The `location`
   field must be special-cased **before** the `if field_val is None: return
   False` short-circuit at `conditions.py:114`, otherwise
   `entity:x.location == null` would always evaluate False. Mirror the
   existing `is_current` special-case at `conditions.py:126-127`. Handle
   `null` comparisons explicitly: `== null` is true iff the derived
   location is `None`; `!= null` is true iff it is not `None`; other
   values use the normal string `_compare`.
2. The explain/detail path (`conditions.py:341-348`) should use
   `get_entity_location` for the `location` field so detail strings are
   accurate.

**B5. `following` interaction**

Implemented within B1's interception (clearing `following` when `location`
is set) and B4's `get_entity_location` (synthesizing `room:<player>`
for following NPCs). No separate containment side-effect is needed when
setting `following: true`.

**B6. Remove `fled` checks**

- `combat.py:243` — remove `st.get("fled") is True` from the filter. The
  presence check at `combat.py:236-241` already excludes entities not in
  `room_contains`.
- `event_bus.py:88-92` — remove the `entity_state.get("fled") is True`
  guard.
- Search for any other `get("fled")` in `mgmai/` and remove engine uses.

**B7. Save migration (`state/manager.py`, `load_save`)**

After loading a hard state, scan `entity_states`:

```python
for eid, st in hard.entity_states.items():
    if "fled" not in st:
        continue
    if st.get("fled") is True:
        # Remove the ghost from all containment (no fled check will skip
        # it after this migration).
        for contents in hard.room_contains.values():
            contents.pop(eid, None)
        for contents in hard.entity_contains.values():
            contents.pop(eid, None)
    del st["fled"]
```

**B8. `_init_contains_from_corpus` — no change needed**

Containment is already initialised from the corpus. `location` is
derived, not stored.

### Phase C: Tests

**C1. Placement read/write**

- Set `location: "room:x"` via `set_entity_state` → entity appears in
  `room_contains[x]` at count 1, removed from its old container.
- Set `location: "entity:y"` → entity appears in `entity_contains[y]`.
- Set `location: null` → entity removed from all containment.
- Condition `entity:spider.location == "room:cellar"` resolves correctly.
- Condition `entity:spider.location == null` resolves True for a
  non-contained entity, and `!= null` resolves True for a contained one
  (verifies the None short-circuit fix).
- Placing a feature (appearing chest) and a non-stackable item works.
- Placing a stackable item is rejected.
- Placing into a non-existent room/entity is rejected.
- Self-containment (`entity:x` into `x`) is rejected.
- Merge idempotency: two changes placing the same entity to the same
  target merge to a single placement (not count 2).
- Cross-path conflict: a single change that moves the same entity via both
  `location` and a containment delta is rejected at validation time.
- The shared `_validate_singleton_target` helper accepts/rejects the same
  targets whether reached via the corpus or the placement validator.

**C2. `fled` replacement (entity-state field only)**

- Existing tests that set the entity-state `fled: true`
  (e.g. `test_state_manager.py:323`, `test_actions.py:449`) → update to
  `location: null`. (Do **not** touch `spider_fled` / `creature_fled` /
  `ambush_fled` flags or narrative text — verify each reference is the
  entity-state field before editing.)
- Combat eligibility: an entity with `location: null` is excluded from
  `resolve_combat_enemies`.
- Reaction matching: an entity with `location: null` has its reactions
  skipped (not in the room's entity set).

**C3. `following` interaction**

- `get_entity_location` returns `room:<player.location>` for a following
  NPC.
- Setting `location` on a following NPC clears `following` and places it.
- Setting `location: null` on a following NPC clears `following` and
  removes it from containment.
- Setting `following: true` on an entity with a stale `room_contains`
  entry does not raise; `get_entity_location` still reports
  `room:<player.location>`.
- Setting both `location` and `following: true` → `location` wins,
  `following` ends false.

**C4. Save migration**

- Load a save with `fled: true` and the entity in `room_contains` →
  entity is removed from containment; `fled` key is gone.
- Load a save with `fled: false` → `fled` key is gone; containment
  unchanged.

**C5. Deprecation**

- `fled` is no longer in `RESERVED_STATE_FIELD_DEFAULTS`.
- A corpus declaring `fled` without an explicit `initial` emits the "no
  explicit initial" warning (deprecation nudge) and resolves to `False`.

### Phase D: Documentation

**D1. `doc/npcs.md`** — update encounter examples to `location: null`;
document the `location` field, its qualified syntax, and singleton scope.

**D2. `doc/combat.md`** — update "fled" references to `location: null`;
document that entities outside containment are excluded from combat.

**D3. `doc/intro.md`** — update any entity-state `fled` references only.

**D4. `schema/scenario-generation.md`** — update all entity-state `fled`
examples.

## Files touched

| File | Phase | Nature of change |
|------|-------|------------------|
| `mgmai/models/corpus.py` | A1 | Remove `fled` from `RESERVED_STATE_FIELD_DEFAULTS` |
| `mgmai/models/actions.py` | A2 | Add `entity_placements` field; `merge` (dict-overwrite); `has_changes` |
| `mgmai/state/manager.py` | B1-B3, B7 | Intercept `location` before validation; `_validate_singleton_target` shared helper; `_validate_placements`; cross-path conflict rejection; `_apply_placements`; save migration in `load_save` |
| `mgmai/engine/utils.py` | B4 | Add `get_entity_location` |
| `mgmai/engine/conditions.py` | B4 | Wire `location` into both `entity:` eval paths; fix `null` short-circuit |
| `mgmai/engine/combat.py` | B6 | Remove `fled` check from `resolve_combat_enemies` |
| `mgmai/engine/event_bus.py` | B6 | Remove `fled` check from `find_matching_reactions` |
| `schema/corpus.md` | A3 | Document `location`, remove `fled` |
| `schema/hard-state.md` | A3 | Note `location` is derived from containment |
| `schema/events.md` | A4 | Update `fled` references |
| `schema/scenario-generation.md` | A5, D4 | Update examples |
| `doc/npcs.md` | D1 | Update examples |
| `doc/combat.md` | D2 | Update flee documentation |
| `doc/intro.md` | D3 | Update entity-state `fled` references only |
| `tests/test_state_manager.py` | C1, C2, C4, C5 | Placement read/write; fled→location; migration; deprecation |
| `tests/test_actions.py` | C1, C2 | `entity_placements` merge; fled→location |
| `tests/test_combat.py` | C2 | Location-based combat exclusion |
| `tests/test_conditions.py` | C1, C3 | Location condition eval (incl. `null`); following synthesis |
| `tests/test_event_bus.py` | C2 | Location-based reaction exclusion |
| `tests/test_resolver.py` | C2 | Update entity-state fled references only |
| `tests/test_hard_state.py` | C2 | Update entity-state fled references only |
| `tests/test_corpus.py` | C5 | Remove fled from reserved defaults |
| `tests/test_encounters.py` | C2 | Update entity-state fled references only |
| `tests/test_assembler.py` | C2 | Update entity-state fled references only |
| `tests/test_bag_of_holding_webs.py` | C2 | Update entity-state fled references only |
| `tests/test_soft_state.py` | C2 | Verify (flag references; likely no change) |
| `tests/helpers.py` | C2 | Update the declared `fled` state field + `set_entity_state` usages |
| `plan.md` | — | This document |

## Open questions / deferred

- **Stackable quantity moves via `Result`.** `location` is singleton-only.
  Moving N of a stackable item between containers at runtime still has no
  author-facing path (the count-deltas are engine-internal). A separate
  `Result` API for quantity moves is a natural follow-up.
- **`combat.ended` event emission.** The `combat.ended` event with
  `reason: "fled"` is documented but never emitted. Separate bug; out of
  scope here but should be tracked.
- **Reverse containment index.** `_apply_placements`'s remove-from-all
  step scans every container. A reverse index would make it O(1); defer
  until container counts motivate it.
