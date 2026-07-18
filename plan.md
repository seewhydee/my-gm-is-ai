## Soft state patches

### Should `proposed_soft_state_patches` be renamed?

It is only used for adding soft state notes to rooms or entities.
Since soft state also incorporates soft items (and other state), maybe
this should be just called `soft_state_notes`.

### Soft state patch format seems to be not great

Here's what the docs say:

```json
{
  "entity_id": null,
  "field": "room_note",
  "target_id": "axe_handle_lower",
  "old_value": null,
  "new_value": "The webs here are partially cleared.",
  "reason": "Player hacked through the webs with the toenail sword."
}
```

To consider: maybe each room/entity just carry ONE string, which is
replaced on each patch? (LLM can be instructed not to obliterate old
details that remain relevant.)

The `target_id` field seems to be useless: its only role is when the LLM
mistakenly fills in a wrong ID and gets rejected!

The `old_value` field is under-documented -- ruling.j2 does not have
it.

### Notes on player entity?

Placing notes on the player entity seems like a way to achieve
"global" soft state notes.  Should this technique be allowed?  If so,
it should be explicitly stated in the docs and/or LLM instructions,
not just left for the LLM to invent (or not).

### Entities not directly present allowed?

Entities contained in other entities are not normally considered
"present"; are soft state patches still allowed for them?  (Probably
they should be.)  In any case, docs should be clearer.
