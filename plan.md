# Plan: Quantity-aware inventory with real stacking

## Problem statement

Entity IDs in the corpus are **dict keys** — unique by definition. For NPCs
and rooms this maps cleanly; items do not. Items are a **confused hybrid**:
their IDs serve as both type definitions (the corpus `entities` entry) and
instance references (entries in player `inventory` / `equipped` / room
`contains`). This creates concrete gaps:

1. **No duplicate prevention.** `inventory_added` (`manager.py:514`) is a
   bare `list.append()` with no tag check or dedup. A sword can appear
   twice in inventory — meaningless for a unique artifact.
2. **Removal is ambiguous.** `list.remove()` (`manager.py:519`) deletes
   only the first occurrence. Given two potions and one `remove_item`,
   the engine can't know which was "the one used."
3. **No counting.** The `inventory` domain condition (`conditions.py:80`)
   is a binary `key in list` — you can't write `inventory:potion >= 3`.
4. **No per-instance state.** Two swords share a single
   `entity_states["sword"]` entry — you can't have one rusty and one sharp.
5. **Equipped *does* guard against duplicates** (`manager.py:523`) but
   inventory does not — an inconsistent split.
6. **The `stackable` tag is documented but unimplemented.** `hard-state.md`
   claims "Duplicates are allowed only if the module explicitly supports it
   (tag: `stackable`)." The tag does not exist anywhere in the code.
7. **Room `contains` duplicates are silently collapsed.** The transfer
   resolver builds `available_pool` as a `set[str]` (`resolver.py:624`) —
   if the corpus defines two potions in a room, the player can only pick
   up one.

### Why the original "stackable = discrete duplicates" plan is insufficient

The earlier draft proposed `stackable` as a tag permitting duplicate list
entries, with quantity tracking deferred. That deferral does not hold:

- **Money is unrepresentable.** "50 coins + 30 coins = 80 coins" cannot be
  modelled. The `list[str]` representation permits discrete duplicates
  (3 separate `potion` entries) but not fungible quantity, and `list.remove()`
  is silently lossy for fungibles.
- **The deferral is not independent of the representation.** Committing to
  `list[str]` with duplicates is *exactly* what blocks counting and money
  later. Shipping `stackable` as discrete-dupes locks in a representation
  the deferred features require us to undo.
- **The name `stackable` promises quantity semantics it doesn't deliver.**
  In RPG convention "stackable" means quantity aggregation (a stack of 80
  gold); using it for "discrete dupes allowed" misleads module authors.

### Design decision: model quantity now

Migrate `player.inventory` from `list[str]` to `Dict[str, int]`
(item_id → count), implement real stacking with counts, and make
`stackable` mean what it says. This resolves gaps 1–3, 6, and 7 in one
coherent design. Per-instance state (gap 4) remains out of scope.

| Item type                | Tagged?       | Count?            | Behavior                                       |
|--------------------------|---------------|-------------------|------------------------------------------------|
| Unique (sword, artifact) | No `stackable`| Always 1          | Adding when present raises; count never > 1    |
| Consumable (potion, coin)| `stackable`   | 1..`max_stack`    | Adds increment; removes decrement; countable   |

### Confirmed design choices

- **Representation:** `player.inventory: Dict[str, int]`. Old saves are
  **not** supported — fixtures and the sample adventure are migrated to
  dict form. Python dicts support `in` and key iteration, so the ~16
  read sites (`eid in hard.player.inventory`, `for item_id in ...`,
  `list(...)`) keep working unchanged; only the two mutation sites and
  serialization change.
- **`stackable` tag + optional `max_stack` field.** `stackable` is a tag
  on item entities (consistent with the existing `container` tag). `max_stack`
  is an optional `Entity` field (default unlimited), gated to `type=="item"`.
- **Quantity in results:** `Result.add_item`/`remove_item` stay as
  `List[str]` (each entry +1; repeats allowed for stackables); add
  `add_item_count`/`remove_item_count: Dict[str,int]` for bulk grants
  (`{"coins": 30}`). Backward compatible.
- **Quantity in transfers:** `TransferAction` gains `given_counts`/
  `taken_counts: Dict[str,int]` alongside the existing lists, so the LLM
  can express "take 300 coins" without repeating an ID 300 times.
- **Conditions:** `inventory:coins >= 30` works (operator on `inventory`
  domain).
- **Deltas:** `HardStateChanges.inventory_added`/`_removed` →
  `Dict[str,int]` (item→count).
- **Equip-one-from-stack:** equipping a stackable item decrements the
  stack by 1; unequipping increments. Equipped stays `list[str]` (unique).
- **Remove shortfall:** hard `ValueError` in `apply_hard_changes`
  (deterministic path); resolver path silently skips + debug-logs
  (fuzzy LLM output). Mirrors the add-dedup split.

### What this does NOT address (out of scope)

- **Room-side stackable depletion.** The engine does not track how many of
  a stackable item remain in a room; `available_pool` is a presence set
  rebuilt each turn from the corpus, never depleted. Bulk room money must
  be modelled as a granting entity (e.g. `coin_pile`) whose take
  interaction uses `add_item_count: {"coins": 300}` gated by a flag, so it
  fires once. Direct `taken_counts` from a room is best-effort and trusts
  the LLM. Documented in `actions.md`.
- **Per-instance state.** Two distinct magic swords must still be defined
  as separate corpus entities (`flame_blade`, `frost_blade`).
- **Soft inventory quantities.** `soft_inventory` stays `list[str]`.

---

## Work items

### Phase 1 — Models

**1. `mgmai/models/hard_state.py:23-33` — `PlayerState.inventory`**
Change `inventory: list[str]` → `Dict[str, int] = Field(default_factory=dict)`.

**2. `mgmai/models/corpus.py:415-455` — `Entity` fields**
Add `max_stack: Optional[int] = None`. Gate to `type=="item"` in
`check_type_specific_fields` (`:433`): raise if `max_stack` set on a
non-item, and if set, `max_stack` must be ≥ 1.

**3. `mgmai/models/corpus.py:126-151` — `Result` fields**
Add `add_item_count: Optional[Dict[str, int]] = None` and
`remove_item_count: Optional[Dict[str, int]] = None`.

**4. `mgmai/models/actions.py:62-76` — `TransferAction` fields**
Add `given_counts: Optional[Dict[str, int]] = None` and
`taken_counts: Optional[Dict[str, int]] = None`. Update
`check_non_empty_transfer` to treat a non-empty count dict as satisfying
the non-empty requirement. Validate counts are ≥ 1.

**5. `mgmai/models/actions.py:176-253` — `HardStateChanges`**
Change `inventory_added`/`inventory_removed` from `List[str]` to
`Dict[str, int]`. Update `merge()` (`:196-236`) to sum counts. Update
`has_changes()` (`:238-253`) to check `bool(dict)`. Keep
`inventory_added_sources`/`inventory_removed_reasons` keyed by item_id
(one source per distinct item).

**6. `mgmai/models/briefing.py:92-102` — `PlayerStateBriefing.hard_inventory`**
Change type to `Dict[str, int]`.

### Phase 2 — State manager

**7. `mgmai/state/manager.py:514-519` — `apply_hard_changes` inventory mutation**
Replace `append`/`remove` with increment/decrement:
- **Add** (per item, count `n` from the delta):
  - Look up entity in `self.corpus.entities`.
  - Unknown item (not in corpus) → treat as non-stackable unique.
  - Non-stackable + already present (`n` ≥ 1 while key exists) → `ValueError`.
  - Non-stackable + `n > 1` → `ValueError`.
  - Stackable → `inventory[key] += n`; if `max_stack` set and
    `inventory[key] > max_stack` → `ValueError`.
- **Remove** (per item, count `n`):
  - `current = inventory.get(key, 0)`. If `n > current` → `ValueError`
    (shortfall).
  - `inventory[key] -= n`; if `<= 0`, `del inventory[key]`.

**8. `mgmai/state/manager.py:251` — cross-ref validation**
Verify `_check_ids` iterates the collection generically; if it indexes,
adjust to iterate `inventory.keys()`.

**9. `mgmai/state/manager.py:142-191` — `_apply_char_sheet_data`**
Char-sheet `inventory` override must now be a dict. Document; the existing
`model_fields` setattr path will reject a list via pydantic.

### Phase 3 — Resolver

**10. `mgmai/engine/resolver.py:595-622` — transfer give**
Merge `given_items` (list, each +1) + `given_counts` (dict) into a combined
per-item count. For each `(item, n)`:
- If in `hard.player.inventory`: validate `inventory[item] >= n`; on
  shortfall → `result.success = False, error = "not enough"`. Record
  `inventory_removed[item] += n`.
- Non-stackable with `n > 1` is automatically a shortfall (count capped at
  1 by the manager dedup invariant) — surface the same error.
- Soft-item branch (`elif item in soft.soft_inventory`) stays list-only
  (soft items have no counts); `n > 1` on a soft item → error.

**11. `mgmai/engine/resolver.py:672-744` — transfer take**
Merge `taken_items` + `taken_counts` into a combined per-item count. For
each `(item, n)`:
- Gate on `item in available_pool` (presence only — room depletion is out
  of scope).
- If item is non-stackable and `n > 1` → `result.success = False` (only
  one exists).
- `take_check` (`:697-727`) runs once per distinct item ID regardless of
  count.
- On pass: `inventory_added[item] += n`.

**12. `mgmai/engine/resolver.py:1196-1203` — `_apply_result`**
Merge `add_item` (each +1) + `add_item_count` into `inventory_added` dict;
same for `remove_item`/`remove_item_count`. Silently skip + debug-log:
- Non-stackable duplicate adds (item already in inventory).
- Remove shortfalls (insufficient count).
This is the fuzzy-LLM-output path; a hard error would be too severe.

**13. `mgmai/engine/resolver.py:1720-1763` — equip / unequip**
- **Equip:** validate at least 1 in inventory. Decrement inventory by 1
  (delete key at 0). Append to `equipped`. Works for both unique and
  stackable (equip-one-from-stack). Equipped's existing duplicate guard
  (`manager.py:523`) stays.
- **Unequip:** remove from `equipped`, increment inventory by 1.

**14. `mgmai/engine/resolver.py:624-665` — `available_pool` (no code change)**
Document that room-side stackable quantity is not depleted. No behavioural
change for v1.

### Phase 4 — Conditions

**15. `mgmai/engine/conditions.py:77-80` — `inventory` domain**
Allow operator. When present: `count = hard_state.player.inventory.get(key, 0)`;
`return _compare(count, op, value)`. Without operator: `return count > 0`.

**16. `mgmai/engine/conditions.py:314-316` — `get_condition_detail`**
Mirror the count-aware branch for the inventory domain.

**17. `tag:` / `equipped:` domains (`conditions.py:82-95, 149-160`)**
Unchanged — iterate keys (works with dict). Stay presence-only.

### Phase 5 — Engine, briefing, CLI, templates

**18. `mgmai/engine/engine.py:944-958` — event derivation**
Emit one `item.acquired`/`item.lost` event per distinct item with a `count`
field (read from the dict delta), instead of N events for N stacked.

**19. Membership checks** — `engine.py:687`, `assembler.py:94`,
`engine/utils.py:132`: `eid in hard.player.inventory` works unchanged with
a dict.

**20. `mgmai/context/assembler.py:221` — briefing build**
`hard_inventory=dict(hard.player.inventory)`.

**21. `mgmai/game/commands.py:395-402` — `/inv` rendering**
Render `name (xN)` when count > 1.

**22. `mgmai/engine/systems/five_e.py:208` — weapon tag scan**
Iterates keys; works unchanged.

**23. `mgmai/logging.py:88` — state snapshot**
Now a dict; works unchanged.

**24. Template renderer** — locate the template consuming `hard_inventory`
and update it to render counts (`xN` when count > 1).

### Phase 6 — Schema docs

**25. `schema/hard-state.md:42,51,63-72,394`**
Change `inventory` type to `object` (item_id → count). Rewrite add/remove
rules: stackable increments, non-stackable raises on duplicate, `max_stack`
cap, remove shortfall raises. Update example to `"inventory": {}`.

**26. `schema/corpus.md:201-214` — Result**
Document `add_item_count`/`remove_item_count`. Note `add_item` repeats are
allowed for stackables (each +1).

**27. `schema/corpus.md:879-918` — Entity**
Add `stackable` tag and `max_stack` field to the entity docs.

**28. `schema/corpus.md:81-116` — condition strings**
`inventory` domain now supports operators (`inventory:coins >= 30`).

**29. `schema/actions.md`**
- Update `TransferAction` (`:418-427`): document `given_counts`/
  `taken_counts`; non-stackable items reject count > 1.
- Update `hard_inventory`/`inventory_added`/`inventory_removed` (`:118-119,
  648-649, 711`) to dict form.
- Document the room-side depletion limitation for `taken_counts`.

**30. `schema/events.md:60-61`**
Add `count` to `item.acquired`/`item.lost` payloads.

### Phase 7 — Tests

**31. Migrate list-form inventory fixtures to dict form:**
`tests/fixtures/hard-state.json`, `tests/fixtures/mini_adventure/hard-state.json`,
the sample adventure's `hard-state.json`, `autosave.json` (if retained),
and shared fixtures in `tests/helpers.py`.

**32. `tests/test_conditions.py:180`**
Rewrite `test_inventory_with_operator_raises` → count-operator tests; add
`inventory:coins >= 30` true/false cases and presence (`count > 0`).

**33. `tests/test_state_manager.py:225,229,235,659,698`**
Update for dict inventory. Add: quantity add/remove, non-stackable dedup
raises, `max_stack` cap raises, remove-shortfall raises.

**34. `tests/test_actions.py:92`**
Update `test_transfer`; add `given_counts`/`taken_counts` validation cases
(non-empty check, count ≥ 1).

**35. `tests/test_resolver.py`**
Update give/take/equip for dict deltas. Add: take 300 coins (stackable,
increments by 300), give 300 coins (validates sufficient, shortfall
fails), take 2 of a non-stackable sword (rejected), non-stackable
duplicate add skipped, remove-shortfall skipped, equip-one-from-stack.

**36. `tests/test_event_bus.py:520`**
Update provenance test for the `count` field on `item.acquired`/`item.lost`.

**37. `tests/test_equip_gear.py`**
Add equip-one-from-stack; verify non-stackable equip unchanged.

**38. `tests/test_assembler.py:478`, `tests/test_commands.py:223`**
Dict briefing; `/inv` `xN` rendering.

**39. New money-scenario test**
- Start: `inventory = {"coins": 50}`.
- Grant 30 via `add_item_count` → 80.
- `inventory:coins >= 30` true; `>= 51` false; `>= 80` true.
- Pick up 300 via `taken_counts` in one transfer → 380.
- Spend 30 via `remove_item_count` → 350.
- Spend 1000 → manager raises (shortfall); resolver path skips + logs.
- `max_stack` cap: add past cap raises.

---

## Rollback risk

Non-zero (unlike the original discrete-dupes plan). The sample adventure's
`hard-state.json` and all inventory fixtures must be migrated to dict form,
and ~7 test files need updates. No behaviour change for unique items
(count stays 1). The migration is mechanical because `in`/iteration are
dict-compatible.

## Implementation order

1. Phases 1–2 (models + manager) — establish the new representation and
   mutation semantics.
2. Phase 3 (resolver) — feed quantities through transfers, results, equip.
3. Phase 4 (conditions) — enable `inventory:id >= N`.
4. Phase 5 (engine/briefing/CLI/templates) — surface counts to LLM and
   player.
5. Phase 6 (docs) — update all schema references.
6. Phase 7 (tests) — migrate fixtures, rewrite the operator test, add the
   money scenario.

Run `pytest` and the lint/typecheck commands after each phase.
