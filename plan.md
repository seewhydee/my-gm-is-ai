# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

- **Character sheet improvements**: LLM-aided prompt for character sheet generation; save character sheets in .config/mgmai.

- **Events and combat**: `combat.started` is emitted only when a reaction-triggered encounter resolves to combat.  `combat.ended` is not yet emitted.  Hook them up after iterating on combat a bit more.  Related: `check.passed`/`check.failed` events are not emitted from `_resolve_encounter_stat_check` in `encounters.py`.  Encounter checks have their own outcome tracking; this can be added if reaction-based encounter check triggers become important.
