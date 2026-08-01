# GMBriefing Schema

The **GMBriefing** is a JSON snapshot of the game world *before* the
player's action this turn.  Each turn, the Context Assembler
(`mgmai/context/assembler.py`) builds it from the Module Corpus, Hard
State, and Soft State, and passes it to:

- **LLM Call 1 (Ruling)** — together with the verbatim player input, to
  interpret intent and produce a `PlayerAction` (see
  [actions.md](actions.md)).
- **LLM Call 2 (Prose)** — the same briefing, for world context when
  narrating the outcome.

The engine never consumes the GMBriefing; it is purely a prompt
structure.  The LLM-facing reference (a condensed version of this
document) lives in `mgmai/templates/briefing_reference.j2` — keep the
two in sync when changing either.

## Serialization Conventions

1. **Empty fields are omitted.**  The briefing is serialized with
   `compact_dump()`: keys whose values are `null`, `""`, `[]`, or `{}`
   are dropped recursively.  A missing field always means "none", never
   "unknown".  Falsy scalars that carry meaning (`0`, `false`) are kept
   (e.g. `"modifier": 0`, `"impeded": false`).
2. **The room `id` is never serialized.**  `current_room.id` is an
   engine-internal identifier and is excluded from the briefing on
   purpose: surfacing it invites the ruling LLM to copy it as an action
   `target` instead of using the reserved `"current_room"` sentinel.

## Top Level

| Field | Meaning |
|-------|---------|
| `adventure_title` | Adventure title from the corpus. |
| `setting`, `tone` | One or two sentences each from the corpus `adventure.atmosphere` block: the world, and the narrative tone to match. |
| `turn` | Current turn number (hard state `turn_count`). |
| `current_room` | The room the player is in — table below. |
| `player_state` | The player's status — table below. |
| `player_knowledge_topics` | Facts the player has learned: `{topic_id, description}` entries. Established facts — never contradict or re-reveal them. |
| `recent_history` | Last few turns: `{turn, summary, location_after}` entries — structured summaries, not verbatim. |
| `dialogue_context` | Present only while a conversation is active — table below. |
| `revealed_hints` | Hint strings the player has learned or observed (from examinations or interactions). Established facts. |
| `player_input` | The player's verbatim input this turn. |
| `combat_state` | Present only while combat is active — table below. |

## `current_room`

| Field | Meaning |
|-------|---------|
| `name`, `description` | Room display name and prose description. |
| `entities_visible` | Non-concealed entities present (NPCs, items, features) — table below. |
| `exits_available` | Visible exits: `{id, direction}` entries. |
| `interactions_available` | The room's *own* interactions: `{id, description}` entries (entity interactions are listed on each entity). Condition-gated ones are filtered out unless their condition currently holds. |
| `room_notes` | Narrative ("soft") notes accumulated about the room. |
| `soft_item_guidance` | GM-only hint about which ambient soft items fit here. |
| `soft_items_taken` | Soft items taken from here, each `"name (taken N)"`; every count is a completed extraction. |
| `soft_items_present` | Soft items the player placed here, each `"name xN"` — they verifiably exist. |

Soft items are mundane ambient objects with generic names ("rock",
"stick") and no entity IDs, unlike "hard" item entities, which have IDs
and narrative significance.

To target the current room itself in a player action (`examine`,
`interact`, `transfer`), use the reserved sentinel `"current_room"`.

## `current_room.entities_visible[]`

| Field | Meaning |
|-------|---------|
| `id` | snake_case identifier for an entity. |
| `name` | Display label. |
| `type` | `npc`, `item`, or `feature` (a fixed object that can't be picked up). |
| `description` | Prose description of the entity. |
| `count` | Stack size for stackable items (usually 1). |
| `state` | Mutable hard-state fields, e.g. `attitude` for NPCs, `open` for containers. |
| `entity_notes` | Narrative ("soft") notes about the entity. |
| `interactions_available` | The entity's own usable interactions: `{id, description}` entries, condition-gated ones filtered; empty for dead entities. |
| `contains` | Items nested inside (container contents): `{id, name, type, description, count}` entries. Not listed separately in `entities_visible` — reachable only via this parent entity. Hidden items and items the player carries (non-stackable) are filtered out; a `container`-tagged entity whose `open` state field is not `true` shows no contents. |
| `dialogue_paths` | NPCs only: map of dialogue-path ID → natural-language description of the path, so LLM Call 1 can match player intent to the correct path. |
| `can_fight` | Present and `true` on entities with a combat block; they include an `attack` interaction in `interactions_available`. Omitted on non-combatants. |
| `soft_item_guidance`, `soft_items_taken`, `soft_items_present` | As for the room, but for soft items contained in this entity. |

## `player_state`

| Field | Meaning |
|-------|---------|
| `hard_inventory` | Item ID → count, e.g. `{"coins": 80}`. |
| `soft_inventory` | Soft item names the player carries. |
| `equipped_items` | `{id, name, description, equip_tags, effects_summary}` entries. |
| `active_flags` | Adventure flags currently true (false flags are omitted). |
| `entity_notes` | Narrative notes about the player. |
| `player_stats` | Effective (gear-adjusted) stats, e.g. `"STR": {value, modifier}`. Present when the corpus defines stats. |
| `combat_stats` | When HP is tracked: `current_hp`, `max_hp`, `ac` (gear-effective), `proficiency_bonus`, `skill_proficiencies`, `weapon_proficiencies` (each a bare string or `{category, properties}`). |
| `abilities` | Available/prepared abilities and spells: `{id, name, description, target, uses_remaining, effect, effect_kind}` entries; `uses_remaining: null` means unlimited. Spells add `spell_level`, `slot_level`, `concentration`, `casting_time`, and a derived `save_dc` for save spells. Omitted during combat — use `combat_state.abilities`. |
| `spell_slots` | Spell level → slots remaining (cantrips cost no slot). Omitted during combat — use `combat_state.spell_slots`. |
| `status_effects` | Status effects active on the player: `{id, rounds, description?}` entries (`description` included when the effect definition has one). |
| `improvised_weapon` | Improvised weapon currently wielded, if any: `{keyword, damage_expr, hit_bonus, damage_type, description, clears_after_turn, source_item?}`. |
| `usable_items` | Inventory items with a usable interaction (e.g. a potion's `drink`): `{id, name, interactions}` entries, each interaction being `{id, description}`. Omitted during combat — use `combat_state.usable_items`. |

## `dialogue_context` (present only during conversation)

| Field | Meaning |
|-------|---------|
| `active_npc` | The NPC being talked to: `id`, `name`, `attitude`, `dialogue`. |
| `active_npc.dialogue` | The NPC's full portrayal guidance: `guidelines` (how the NPC speaks and behaves), `attitude_limits` (`min`, `max`, `step_per_turn`), `will_reveal` (topics the NPC may reveal, with their conditions), `dialogue_paths`. |
| `recent_exchanges` | Recent verbatim back-and-forth: `{player, npc}` entries. Adjacent player→NPC log entries are paired into one exchange; unpaired entries stand alone. Capped at the 5 most recent exchanges. |
| `topics_discussed`, `revealed_topics` | Topic IDs already covered in conversation / already revealed by this NPC. |

## `combat_state` (present only during combat)

| Field | Meaning |
|-------|---------|
| `round_number`, `initiative_order`, `current_actor` | Turn order state. |
| `combatants` | Entries with `id`, `name`, `side`, `current_hp`, `max_hp`, `status_effects`, `engaged_with`, `impeded`, `impede_used`. `side` is `"party"` (the player and their allies) or `"enemy"` (hostiles); `engaged_with` lists combatants currently within melee reach; `impeded` means a pending obstacle delay will consume that combatant's next turn; `impede_used` means it has already been impeded this combat. |
| `abilities`, `spell_slots`, `usable_items` | Same shapes as in `player_state`, but `abilities[].uses_remaining` tracks per-combat remaining uses. During combat these are the authoritative copies. |

## Worked Example

Non-combat turn, mid-dialogue.  Empty fields omitted per the
serialization conventions (note the missing `current_room.id`):

```json
{
  "adventure_title": "You're Trapped in a Bag of Holding!",
  "setting": "You are a person trapped inside a magical Bag of Holding — a pocket dimension full of discarded treasures, dangers, and a dwarf who has been lost here for years.",
  "tone": "Whimsical and slightly dark. The world is absurd but coherent. Danger is real but the tone is more Pratchett than Lovecraft.",
  "turn": 3,

  "current_room": {
    "name": "Axe Handle (Lower)",
    "description": "You are on the lower section of the axe handle. The webs here are denser, blocking the path downward unless you push through. If you look carefully, you see the spider — huge and hungry for blood — lurking in the webs. Below, many irregularly shaped objects are coming into view. It looks like you could drop down safely. There is some muffled clanking from the shadows below.",
    "soft_item_guidance": "Loose stones, dust, and cobwebs are common here.",
    "soft_items_taken": ["rock (taken 1)", "loose stone (taken 1)"],
    "entities_visible": [
      {
        "id": "spider",
        "name": "Huge Spider",
        "type": "npc",
        "description": "A huge, hungry spider lurking in the dense webs.",
        "count": 1,
        "state": { "alive": true },
        "interactions_available": [
          { "id": "attack", "description": "Start combat with this entity" }
        ],
        "dialogue_paths": {
          "flatter": "Praise the spider's hunting prowess to improve its attitude toward the player."
        },
        "can_fight": true
      },
      {
        "id": "webs_dense",
        "name": "Dense Webs",
        "type": "feature",
        "description": "Thick webs blocking the downward path.",
        "count": 1
      }
    ],
    "exits_available": [
      { "id": "exit_up_handle_lower", "direction": "Walk up the axe handle" },
      { "id": "exit_through_webs", "direction": "Push through the dense webs downward" },
      { "id": "exit_drop_lower", "direction": "Drop safely down to the floor" }
    ],
    "room_notes": ["The webs here are partially cleared from the spider's flight."]
  },

  "player_state": {
    "hard_inventory": { "iron_sword": 1 },
    "soft_inventory": ["rock"],
    "equipped_items": [
      {
        "id": "toenail_sword",
        "name": "Giant Toenail Clipping",
        "description": "A giant toenail clipping, curved and razor-sharp...",
        "equip_tags": ["weapon", "martial"],
        "effects_summary": "1d6 damage"
      }
    ],
    "active_flags": { "met_korbar": true },
    "player_stats": {
      "STR": { "value": 14, "modifier": 2 },
      "DEX": { "value": 12, "modifier": 1 },
      "CON": { "value": 13, "modifier": 1 },
      "INT": { "value": 10, "modifier": 0 },
      "WIS": { "value": 8, "modifier": -1 },
      "CHA": { "value": 16, "modifier": 3 }
    },
    "combat_stats": {
      "current_hp": 27,
      "max_hp": 27,
      "ac": 14,
      "proficiency_bonus": 2,
      "skill_proficiencies": ["acrobatics"],
      "weapon_proficiencies": ["simple", "martial"]
    },
    "abilities": [
      {
        "id": "cure_wounds",
        "name": "Cure Wounds",
        "description": "Healing magic that closes wounds.",
        "target": "self",
        "uses_remaining": null,
        "effect": "heal 1d8 + spellcasting modifier",
        "effect_kind": "heal",
        "spell_level": 1,
        "concentration": false,
        "slot_level": 1,
        "casting_time": "action"
      }
    ],
    "spell_slots": { "1": 2 },
    "status_effects": [
      { "id": "mage_armor", "rounds": 480, "description": "AC becomes 13 + DEX modifier while active." }
    ],
    "usable_items": [
      {
        "id": "potion_healing",
        "name": "Potion of Healing",
        "interactions": [
          { "id": "drink", "description": "Drink the potion to restore 2d4+2 HP." }
        ]
      }
    ]
  },

  "player_knowledge_topics": [
    { "topic_id": "padlock_mechanism", "description": "How the exterior padlock can be opened from inside" }
  ],

  "recent_history": [
    {
      "turn": 2,
      "summary": "Player climbed down the axe handle from axe_head, passing through axe_handle_upper where a dying fly warned about the spider. Now at axe_handle_lower.",
      "location_after": "axe_handle_lower"
    },
    {
      "turn": 1,
      "summary": "Player woke up on the axe head inside the Bag of Holding. Examined surroundings. Noticed the rip in the canvas.",
      "location_after": "axe_head"
    }
  ],

  "dialogue_context": {
    "active_npc": {
      "id": "korbar",
      "name": "Korbar the Dwarf",
      "attitude": 2,
      "dialogue": {
        "guidelines": "Cynical dwarven rogue, heavy drinker, lonely but proud. Cannot leave the bag, stop drinking, or remember which way is north. Knows the padlock mechanism and the secret compartment in the axe head.",
        "attitude_limits": { "min": -5, "max": 10, "step_per_turn": 3 },
        "will_reveal": {
          "padlock_mechanism": {
            "description": "How the exterior padlock can be opened from inside",
            "conditions": ["entity:korbar.attitude >= 2", "topic:abandonment"]
          },
          "secret_compartment": {
            "description": "A hidden cache inside the axe head",
            "conditions": ["entity:korbar.attitude >= 4", "inventory:rusty_key"]
          }
        }
      }
    },
    "recent_exchanges": [
      { "player": "Who are you?", "npc": "Arr, name's Korbar. Me party left me here." },
      { "player": "Tell me more about your party." }
    ],
    "topics_discussed": ["origin", "abandonment"],
    "revealed_topics": ["padlock_mechanism"]
  },

  "revealed_hints": ["The exterior padlock can be opened from the inside."],

  "player_input": "I pull up a chair to sit on and ask Korbar, 'What happened to your party?'"
}
```

During combat, `player_state` drops `abilities`, `spell_slots`, and
`usable_items` (their authoritative, per-combat copies move to
`combat_state`):

```json
{
  "combat_state": {
    "round_number": 2,
    "initiative_order": ["player", "spider"],
    "current_actor": "spider",
    "combatants": [
      {
        "id": "player",
        "name": "Player",
        "side": "party",
        "current_hp": 21,
        "max_hp": 27,
        "status_effects": [],
        "engaged_with": ["spider"],
        "impeded": false,
        "impede_used": false
      },
      {
        "id": "spider",
        "name": "Huge Spider",
        "side": "enemy",
        "current_hp": 12,
        "max_hp": 30,
        "status_effects": [
          { "id": "poisoned", "rounds": 3, "description": "Disadvantage on attack rolls and ability checks." }
        ],
        "engaged_with": ["player"],
        "impeded": false,
        "impede_used": false
      }
    ],
    "abilities": [
      {
        "id": "cure_wounds",
        "name": "Cure Wounds",
        "description": "Healing magic that closes wounds.",
        "target": "self",
        "uses_remaining": null,
        "effect": "heal 1d8 + spellcasting modifier",
        "effect_kind": "heal",
        "spell_level": 1,
        "concentration": false,
        "slot_level": 1,
        "casting_time": "action"
      }
    ],
    "spell_slots": { "1": 2 },
    "usable_items": []
  }
}
```

## Assembly Rules

The Context Assembler builds the briefing each turn as follows:

1. **Title, setting, tone**: `adventure_title` from `corpus.adventure.title`;
   `setting` and `tone` from the corpus `adventure.atmosphere` block.  Some
   brief sentences about the world and narrative style.

2. **Turn**: from hard state `turn_count`.

3. **Current room**: fetched by the player's location ID from the module
   corpus.  The serialized `current_room` never includes its `id` (see
   Serialization Conventions).  Includes the room description, soft-item
   guidance and taken/present listings, `entities_visible`, available
   exits, the room's own `interactions_available` (condition-gated ones
   filtered), and `room_notes`.

4. **Visible entities**: all non-concealed entities in the room's runtime
   containment map, plus any following NPCs.  Entities with hidden state,
   equipped items, and non-stackable items already in the player's
   inventory are omitted.  Each entry carries the entity ID, current hard
   `state`, `entity_notes`, soft-item guidance and taken/present listings,
   usable `interactions_available` (condition-gated ones filtered; empty
   for dead entities), `contains` (container contents, gated on the
   container being open), `dialogue_paths` for NPCs, `can_fight` on
   combat-capable entities, and `count`.

5. **Exits**: only exits whose conditions are met and that are not hidden.
   Hidden exits (e.g. a secret compartment) are omitted unless their
   reveal flag is set.

6. **Player state**: hard inventory, soft inventory, equipped items
   (with `equip_tags` and `effects_summary`), active flags (true ones
   only), entity notes, `player_stats` (when the corpus defines stats —
   effective, gear-adjusted values with computed modifiers), and
   `combat_stats` (when HP is tracked — effective AC included).  Also
   `status_effects` (with effect descriptions when the effect definition
   has one), the current `improvised_weapon`, and — outside combat —
   `abilities`, `spell_slots`, and `usable_items` so LLM Call 1 can rule
   out-of-combat ability and item use (e.g. casting Mage Armor before a
   fight).

7. **Recent history**: the last 5 entries from soft state `turn_history`
   whose action type is not `ooc_discussion` — `ooc_discussion` entries
   are skipped entirely and do not count toward the cap.  Each entry is
   `{turn, summary, location_after}`, where `summary` is the engine's
   condensed result summary.  NO raw chat log.

8. **Player knowledge**: `player_knowledge_topics`, a list of
   `{topic_id, description}` objects for each topic in
   `soft_state.player_knowledge`, so LLM Call 1 knows what the player has
   learned and what each topic means.

9. **Revealed hints**: `revealed_hints`, copied from
   `soft_state.revealed_hints` — hint strings the player has learned or
   observed.

10. **Dialogue context**: included when `soft_state.dialogue_state.active_npc`
    is non-null *and* the NPC exists in the corpus, is alive, and has
    dialogue guidelines.  The block contains the active NPC's identity,
    current attitude, full `dialogue` (guidelines, attitude limits,
    `will_reveal`, dialogue paths), the last 5 exchanges from
    `conversation_log` (adjacent player→NPC entries paired into
    `{player, npc}` dicts), `topics_discussed`, and `revealed_topics`
    (knowledge topics whose source is this NPC).  If `active_npc` is
    null, `dialogue_context` is omitted.

11. **Combat state**: included only while combat is active
    (`hard_state.combat.active`).  Contains round/initiative/current-actor,
    one `combatants` entry per combatant (with `side`, HP, status effects,
    and positioning: `engaged_with`, `impeded`, `impede_used`), plus
    `usable_items`, `abilities` (with per-combat remaining uses), and
    `spell_slots`.  During combat these are the authoritative copies;
    the corresponding `player_state` fields are omitted.

12. **Player input**: the verbatim text entered this turn.  For chained
    actions (see [actions.md](actions.md) §2.2), this is the original
    input plus a clear indication of where the chain currently stands.

---

## Relationship to Other Documents

- [actions.md](actions.md) — the other side of the pipeline:
  `PlayerAction` (LLM Call 1 output) and `EngineResult` (input to
  LLM Call 2).
- [soft-state.md](soft-state.md) / [hard-state.md](hard-state.md) — the
  state sources the briefing is assembled from.
- `mgmai/templates/briefing_reference.j2` — the condensed, LLM-facing
  reference for the same structure; keep in sync with this document.
- `mgmai/models/briefing.py` — the Pydantic models implementing this
  schema; `mgmai/context/assembler.py` — the assembly logic.


> Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
> This document is part of My GM is AI, licensed under the [GNU GPL v3](../LICENSE).
