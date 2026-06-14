# My GM is AI (MGMAI) -- Coding plans

## Future Extensions

- **Combat phase**: the attack interaction will be revised to support iterative rounds, HP tracking, damage rolls, and opposed checks. The current flag-based branching is a phase-1 placeholder. See [Combat Implementation Plan](#combat-implementation-plan) below.

- **Semantic search / RAG**: once adventures grow beyond the hand-coded five-room scale, the deterministic ID lookup in the Context Assembler can be augmented with vector embeddings for entity descriptions and player queries.

- **Multi-NPC conversations**: currently we only handle conversing with one NPC at a time, this should be extended.

- **Character sheet improvements**: LLM-aided prompt for character sheet generation; save character sheets in .config/mgmai.

---

## Combat Implementation Plan

### Overview

Combat will be a **phase** in the game loop, analogous to dialogue mode: when active, the set of valid player actions narrows, and the engine runs a dedicated resolution pipeline. Like the existing stat system, the combat mechanics use 5e as the reference implementation but are described in corpus-agnostic terms so that other RPG systems can be plugged in later.

The minimum viable combat system supports:

1. **Initiative** — determines turn order at combat start.
2. **Attack rolls** — d20 + ability modifier + proficiency vs target AC. Natural 1 auto-misses, natural 20 auto-hits (crit).
3. **Damage** — damage dice + ability modifier on hit; double dice on crit.
4. **HP tracking** — player and NPCs have hit points; reaching 0 HP means death (or incapacitation).
5. **Flee** — the player (or NPC) may attempt to escape combat.
6. **Multi-round** — combat loops across rounds until one side is dead, all enemies flee, or the player flees.

Deliberately excluded for this phase: gear, movement/positioning, spellcasting, class features, conditions (poisoned, etc.), death saves, healing during combat, multi-attack, reactions/opportunity attacks, and NPC-vs-NPC combat. Enemies are stat blocks with one basic attack, and with no decision-making during combat.

---

### 1. Data Model Changes

#### 1a. Corpus: entity combat stat block

Add an optional `combat` field to the `Entity` model. Only NPC-type entities (and the player via character sheet) carry this block. If absent, the entity cannot participate in combat and any attack against it resolves through the existing encounter system instead.

```python
class CombatBlock(BaseModel):
    hp: int                    # maximum hit points
    ac: int                    # armour class
    atk: int                   # attack bonus (ability mod + proficiency)
    dmg: str = "1d6"           # e.g. "1d6+2", "2d4", "1d8+1"
    initiative_mod: int = 0    # DEX modifier for initiative
    flee_dc: int = 10          # DC for fleeing (usually DEX-based)
```

The `CombatBlock` is intentionally flat (no separate ability scores for NPCs) for minimalism. The `attack_bonus` and `initiative_mod` are pre-computed by the adventure author. For the player, these are derived from ability scores at combat-start time (see §1b).

Design note: this is simpler than giving every NPC full 5e ability scores, which would be a larger schema change. If full NPC stats are needed later, the `CombatBlock` can be extended or replaced without breaking the combat resolver.

#### 1b. Hard state: player combat data

Extend `PlayerState`:

```python
class PlayerState(BaseModel):
    location: str
    inventory: list[str] = Field(default_factory=list)
    level: int
    stats:  Optional[Dict[str, int]] = None
    hp:     Optional[int] = None
    max_hp: Optional[int] = None
    ac: int
    proficiency_bonus: int
```

Add a new top-level field to `HardGameState`:

```python
class CombatState(BaseModel):
    active: bool = False
    combatants: list[str] = Field(default_factory=list) # entity IDs + "player"
    initiative_order: list[str] = Field(default_factory=list)
    current_index: int = 0
    round_number: int = 0
    log: list[dict] = Field(default_factory=list) # per-round combat log
    flee_attempted: bool = False

class HardGameState(BaseModel):
    player: PlayerState
    ...[other fields]...
    turn_count: int = 0
    combat: Optional[CombatState] = None   # None when not in combat
```

NPC current HP is tracked in `entity_states[<npc_id>].current_hp` (mutable). We also store `entity_states[<npc_id>].alive` as a boolean; the combat resolver sets this to `False` when the NPC reaches 0 HP.

#### 1c. Character sheet extension

Character sheets based on the `5e` system gain `level`, `max_hp`, `ac`, and `proficiency_bonus` fields.  In principle, the latter three are derived stats (based on CON, DEX, level), but we'll let character sheets specify them directly; if omitted, we supply a default calculation based on an ordinary unarmed human (equippable inventory, spells, and class effects haven't been implemented).

```json
{
    "system": "5e",
    "player": {
        "level": 1,
        "stats": { "STR": 14, "DEX": 12, "CON": 13, "INT": 10, "WIS": 8, "CHA": 16 },
        "max_hp": 10,
        "ac": 13,
        "proficiency_bonus": 2
    }
}
```

### 1d. New Player Actions

We make the following two modifications to the PlayerAction design (which will require changes to the engine, schema, and the LLM ruling template `ruling.j2`).

First, when NOT in combat mode, we extend `InteractAction` to take `interaction_id: "attack"` as a trigger for combat entry.  This player action begins combat if the target NPC has a `CombatBlock` and the encounter rules don't produce an instant outcome (death/flee).  Note that the effect is only to *begin* combat; the player does not perform their initial combat action yet, no matter what they narrated---for example, even if the player says "I run him through with my sword", that doesn't actually happen yet.

For the `attack` interaction to validate, it must target a valid NPC and the following must be true:

1. The NPC is alive. If dead, return error.
2. If the NPC's `behavior` has encounter rules matching `"attack"`, evaluate them. If they produce an instant outcome (death/flee), return that outcome *without* entering combat.
3. If no instant outcome, initialise combat mode.  See Sec. 3a below.

Second, once we ARE in combat mode, one additional PlayerAction type is available for player combat actions (added as a discriminated union member to `PlayerActionType`):

```python
class CombatAction(_BaseAction):
    action_type: Literal["combat"]
    combat_action: Literal["attack"] # More action types later
    target: Optional[str] = None     # entity ID for "attack"; None for "flee"
```

This PlayerActionType is invalid outside combat mode.  For now, we support just one combat action:

- `combat_action: "attack"` + `target`: player attacks the named NPC.

In the future, there will be more options than `attack`: spellcasting, abilities, etc.

### 1e. EngineResult changes

Combat mode can be triggered by a player explicitly performing an attack interaction (as noted in 1d), or as a side-effect during the engine resolution phase.  The `encounter` mechanic (see corpus schema) will be enhanced to include triggering combat as a possible outcome.

Either way, the onset of combat mode will be noted explicitly by the `EngineResult`, in a new `combat_triggered` field (this flag is off while in the middle of combat; it's only for the start of combat).

The engine will also initialize the `CombatState`:

   - Set `active = True`.
   - Determine combatants: the player + enemies
     -- If the player attacked an NPC, that NPC becomes an enemy
	 -- The corpus can put a trigger on NPCs that add other NPCs
	    to the combatants list once the first NPC is added
	 -- Enginer-triggered combat will specify the enemy list
     -- We don't implement helping NPCs for now; non-hostile
	    NPCs sit the combat out.
   - Set `round_number = 1`, `current_index = 0`.
   - Set `log = []`.

Also, dialogue mode will be disabled.

Visual indicators for combat mode will also be shown (see below).

### 2. Engine: Combat Resolver

A new module `mgmai/engine/combat.py` handles all combat mechanics. The main entry point is:

```python
def resolve_combat_turn(
    action: CombatAction,
    hard: HardGameState,
    corpus: ModuleCorpus,
) -> dict:
    """Resolve one player combat turn + NPC turns. Returns a combat result dict."""
```

### 3. Combat rounds

Once in combat mode, the engine proceeds to manage the start of the combat round:

- Roll initiative for each combatant: `d20 + initiative_mod`. Player initiative uses DEX modifier from `player.stats`. NPC initiative uses `CombatBlock.initiative_mod`.
- Sort combatants by initiative roll (highest first). Ties broken by DEX then by coin flip.

During combat mode, our input-output loop spans the events between the player's turn in the current turn to the player's turn in the next turn. Due to initiative, this might not align with the start/end of the combat rounds.

#### 3a. First set of enemy turns

All enemies with higher initiative than the player act.  In the current implementation phase, NPC combatants only attack the player on their turn, so we will not hook up the LLM as "enemy AI".  Instead, the engine will mechanically make attack and damage rolls, and emit simple combat messages like "[Goblin 1 Attacks. Hit! 3 DMG]", which will be inserted into the narration.

1. Skip if NPC is dead or fled (for whatever reason).
2. **NPC attacks player**: `roll_d20() + npc.attack_bonus` vs player AC.
   - Player AC = from character sheet or default `10 + DEX_mod`.
   - Natural 1: auto-miss. Natural 20: auto-hit (crit).
3. **Damage roll**: parse `npc.damage` (e.g. `"1d6+2"` → roll 1d6, add 2). Apply to `hard.player.current_hp`.
4. Append combat log entry.
5. If `player.current_hp <= 0`: player dies. Set `game_over = {type: "lose", trigger: <npc_id>}`. Clear combat state. Combat ends.

**It is at this point that the engine hands over to LLM Call 2.** The LLM will be instructed to narrate: (i) the events from the last player action up to the point of the onset of combat, and (ii) the events of the first set of enemy turns, if any.  The aforementioned simple combat messages, if any, are inserted between the two chunks before displaying to the player.

#### 3b. Player's turn

The input prompt returns to the player when it's their turn.  They are free to issue whatever command, and the input is categorized into a PlayerAction by LLM Call 1.  Since we are now in combat mode, the `combat_action` PlayerAction type is now allowed.

In combat mode, the engine resolution for the `move` action is altered. Any attempt to move to a different room is treated as a flee action; see Fleeing, below.

If the player issues a `combat_action: "attack"` action, targeting an NPC, the engine resolution is as follows:

1. Validate: the target must be a combatant in `combat.combatants`, alive (`entity_states[<id>].current_hp > 0`), and present in the current room.
2. **Attack roll**: `roll_d20()` + player's attack bonus.
   - Player attack bonus = `compute_5e_modifier(stats["STR"]) + proficiency_bonus` for melee, or `compute_5e_modifier(stats["DEX"]) + proficiency_bonus` for ranged. For phase 1, all attacks use STR (melee).
   - Natural 1: auto-miss.
   - Natural 20: auto-hit (critical).
   - Compare total vs target's `CombatBlock.ac`.
3. **Damage roll**: if hit, roll damage using the player's weapon damage dice.
   - Player damage defaults to `1d6 + STR_mod` (unarmed / improvised weapon) or `1d8 + STR_mod` if a weapon is in inventory (adventure-defined). The exact weapon dice should be configurable via a corpus field or character sheet, but for phase 1 we can hardcode reasonable defaults.
   - Critical hit: double the number of damage dice (roll twice as many dice, add modifier once).
4. Apply damage: `entity_states[<npc_id>].current_hp -= damage`.
   - If reduced to 0 or below: set `entity_states[<npc_id>].alive = False`. Remove NPC from `combat.combatants`. Append combat-log entry for death.
5. Append a combat-log entry with: attacker, target, attack roll (raw + total), AC, hit/miss, damage roll details, remaining HP.

#### 3c. Narration and follow-up

If the last enemy was killed as a result of the player's action, combat mode is disabled, and the EngineResult is passed to LLM Call 2 to narrate the end of combat -- how the player strikes the last blow, etc.  We now return to the usual gameplay loop.

If there are still enemies active, all those with lower initiative than the player now act.  These function identically to section 3a.

The engine then proceeds to the next combat round:

- Advance `round_number` and reset `current_index` to 0
- Roll initiative
- Processes all the enemies going before the player

It is at this point that LLM Call 2 is invoked to narrate everything that's happened.  This establishes the combat loop.

#### 3d. Fleeing

If the player flees (by choosing a `move` action during their turn):

1. Roll a DEX stat check: `roll_d20() + DEX_mod` vs `npc.flee_dc`. If multiple enemies, use the highest `flee_dc`.
2. If successful, and the rest of the `move` action validates, clear the `combat` state and move the player to the specified room.
3. If failed: the player's turn is wasted (they tried to flee but were blocked). Play proceeds to NPC turns normally.

### 4. GMBriefing Extension

The Context Assembler is updated to:
1. Compute player combat stats from ability scores when combat starts (attack bonus, initiative mod, AC if not from character sheet).
2. Include `combat_state` in the GMBriefing when `hard.combat.active` is True.
3. Include NPC combat stat blocks in the `current_room.entities` descriptions when applicable, so the LLM knows NPC capabilities (this may be part of the broader entity briefing or a dedicated combat section).

### 5. Display

The console UI (`display.py`) shows combat status between turns:

```
┌─ Combat: Round 2 ──────────────────────────────────────┐
│ Initiative: Player → Spider → Goblin                    │
│                                                         │
│ Player    HP ████████░░ 10/12                           │
│ Spider    HP ██████████ 18/18                           │
│ Goblin    HP ████░░░░░░  5/10                           │
│                                                         │
│ It's your turn.                                         │
└─────────────────────────────────────────────────────────┘
```

Stat check formatting (`format_stat_check_prefix`) is extended or complemented by a `format_combat_prefix` that shows a compact summary of the last round's events (who attacked whom, hit/miss, damage).
