# Densifying "You're Trapped in a Bag!" — Proposal List (rev 2)

**Status: proposals only, no implementation.** The user wants the
bag-of-holding adventure made "denser" while keeping its scope fixed:
same 5 rooms (axe_head, axe_handle_upper, axe_handle_lower, bag_floor,
secret_pocket), same 3 NPCs (fly, spider, korbar), same win/lose
shape (padlock/key win; death, rip, and key-loss losses). This document
is the deliverable: a menu of proposals for the user to pick from. Any
adopted proposal would later be implemented across `scenario.md`,
`scenario-map.md`, and `corpus.json` (kept in sync, validated with
`scripts/validate_adventure.py`), plus `default-player.json` where
noted.

**Rev 2 changes** (per user feedback — more creativity, whimsy,
D&D-isms, more magic): added the satirical through-line and density
lever 6; expanded the engine facts with magic-authoring capabilities;
added proposals #11–#15 (whimsy/satire finds) and #25–#30 (magical
mechanics); renumbered and repaired stale cross-references; folded the
previous prisoner, the polymorph gag, and the potion vats into richer
versions of the rev 1 items. Rev 1's low-hanging fruit is retained
essentially intact.

## What "denser" means here

Scope is pinned: no new rooms, NPCs, or win/lose conditions.  Density
must come from six levers:

1. **Finds** — more discoverable items, and items with *uses* (gifts,
   tools, leverage, evidence), not just flavor.
2. **Solution paths** — each obstacle currently has ~1.5 solutions; the
   goal is ≥2.5, differentiated by approach (force / stealth / social /
   improvisation) and by risk.
3. **Connected knowledge** — lore that currently sits inert in NPC
   guidelines should become discoverable, and should connect the cast to
   each other and to the set pieces (axe, padlock, key, handkerchief,
   rubbish).
4. **Meaningful choices** — resource trade-offs (your only weapon, your
   only potion), risk/reward gambles, and a little moral texture.
5. **Class synergy** — the player is a Rogue; the engine supports all
   18 SRD skills (#20). The adventure should reward playing a Rogue.
6. **Wonder & genre satire** *(new in rev 2)* — the setting is one of
   D&D's most iconic magic items; it should feel enchanted. Every find
   should either *do* something or *say* something (ideally both). The
   satire stays mechanically faithful: jokes live in the prose, the
   math stays honest (real SRD spells, real conditions, real DCs).

## Current shape (for orientation)

- One golden path: find key in secret pocket → haul it up (STR checks,
  Korbar assist) → padlock → win.
- Spider: fight it, or flatter to attitude 0 then persuade (armed only;
  otherwise it lies).
- Korbar: rapport (+1 ×3 cap), convince spider dead, follower, key
  hauler, optional fighter.
- Fly: single warning, then dies.
- Finds: toenail sword, handkerchief, key. That's it.
- Thinnest spots: `secret_pocket` is nearly empty (one item, no
  examinations), `axe_head` has no presence, and there is **no usable
  magic anywhere** — potions exist only as empty bottles. That last
  gap is rev 2's main target.

The adventure is sparse in three ways: (1) few *finds*, (2) few *ways
past obstacles*, (3) NPC knowledge is transactional — lore exists in
guidelines but there's little to discover and little that connects the
cast to each other or the set pieces.

## Engine facts that shape these proposals (verified)

- Checks: only `roll` and `stat_check`. A `stat_check`'s `stat` may
  name any of the 18 SRD skills (case-insensitive); proficiency comes
  from `player.skill_proficiencies` (settable in `default-player.json`).
  There is no separate skill-check type.
- `using_results` (item-keyed override checks) works on traversal
  checks, interactions, examine effects, and dialogue paths; it accepts
  an item entity ID **or the `"*"` wildcard** (any hard item). Soft
  items have no entity IDs and cannot be keyed this way.
- Soft items are narrative-only; the single mechanical bridge is the
  improvised-weapon patch. Creative soft-item use is adjudicated by the
  GM, steered by `soft_item_guidance` prose.
- Results support `reveals` (appends to `soft_state.revealed_hints`),
  `player_heal`, `apply_status_effect` (target may be the player **or
  an NPC entity ID**), `cure_status_effects`, `increment_entity_state`
  (negative deltas OK — the only direct HP lever on an NPC outside
  combat), `remove_item` / `remove_item_count`, `add_item`,
  `adjust_attitude`, `set_player_location` (runs the full room-
  transition pipeline — usable for teleport gags), flags, and inline
  `game_over` (win *and* lose).
- Item `interactions` are full Resolvables (condition/check/result/
  using_results). The SRD pack ships **no scrolls, wands, or magic
  items** — but none are needed: a "scroll" is just an item whose
  `use`/`read` interaction carries a Result (see `potion_of_healing`'s
  `drink`). Charges can be modeled with a numeric `state_field` +
  `increment_entity_state` on self; one-shots with `remove_item_count`.
- Built-in SRD conditions usable out of the box include `poisoned`,
  `restrained`, `frightened`, **`invisible`** (advantage on attacks /
  disadvantage against), **`incapacitated`** (skips turns), and
  `unconscious`. Custom status effects are declarable in corpus
  `status_effects` (`scope`, `duration` rounds/until_cleared, 5e
  `system_effects`); **no save-ends mechanic** exists.
- Conditions may query `status_effect:<id>` (including per-entity,
  e.g. `status_effect:spider.incapacitated`) and hard-item possession
  (precedent: the spider's `persuade_passage` checks `tag:weapon`).
- Combat AI supports `ai.flee_below_hp_pct` (1–99), `ai.passive`,
  `ai.targeting`. NPC combat blocks are **pre-computed**: nothing can
  change an NPC's damage/AC at runtime, and consented transfers to
  living NPCs fire no state-change events (gate on dialogue paths or
  attitude instead).
- Player spells/abilities are **sheet-only** (`spellbook`/`abilities`/
  `spell_slots` in `default-player.json`); no Result grants abilities
  mid-game. All magical loot must therefore be item-interaction-based.
- Exits support exactly one `traversal_check`; an exit whose
  `condition` is false is invisible to player *and* GM (hidden-exit
  mechanism). Exit `failure` is a full Result (may carry damage).
- Rests: the ruling LLM decides whether a rest is fictionally
  possible/safe — there is **no** safe-rest-location field and no
  mid-rest ambush. Long rests heal the player to full and restore
  follower allies to full HP. A `rest.completed` event exists for
  reactions.
- The SRD data pack ships `dagger`, four healing-potion tiers
  (`potion_of_healing` = 2d4+2 with a `drink` interaction), full weapon/
  armor tables, 23 conditions, and 7 spells (including `sleep` and
  `mage_armor`). A corpus entity reusing a pack ID replaces the pack
  entry wholesale.
- On-hit effects only fire against the player. Encounter-rule Results
  may combine damage/status/flags with `start_combat` in one atomic
  result (opening effects). One encounter per turn.

## Proposals

### Tier 1 — Enrichment & whimsy (low risk, no new solution paths)

1. **Staged rubbish finds (bag_floor).** Add more hard-item
   discoveries to the rubbish pile, gated behind successive rigorous
   examinations with rising DCs (the pattern already established by
   toenail → handkerchief):
   - Three *unbroken* giant potion bottles (disambiguated by color),
     which can be uncapped with a STR check. In the player's shrunken
     state each bottle is the size of a vat: they must be drunk from
     directly and can't be carried. The potion types are initially
     unknown and can be teased out with INT (Arcana/Investigation)
     checks — or identified the old-fashioned way, by sipping
     (a taste test; the poison one costs a CON save vs. a small
     poison-damage lick, satirizing the classic "sip to identify"
     ritual). One is a long-duration antivenom (pairs with #18's
     `poisoned` condition), one heals, and one is a poison
     (insta-loss — the fine print kills; see the through-line).
   - Edible (if revolting) rations → giftable to Korbar (see #8) or
     nibbled for 1 HP.
   - Giant Lockpick — the size of a two-handed staff (and can be used
     as such), and also to attempt picking the padlock (#22).
2. **A previous prisoner's web husk (axe_handle_upper).** One of the
   wrapped masses, on rigorous examination, turns out to be a
   desiccated shrunken *person* — a previous prisoner. Loot: a
   normal-sized `dagger` (SRD pack item; a simple-weapon alternative
   to the toenail), a **journal**, and (tucked in its pages as a
   bookmark) the scroll from #25. The journal satirizes the
   dead-adventurer-with-convenient-exposition trope: entries devolve
   from lucid to lint-obsessed ("Day 41: still no rescue. Day 42:
   I have named the lint."), deliver two real hints in passing, and
   the final entry trails off mid-sentence: *"The spider is actually
   quite reasonable if you—"* (ambiguous: tempting and unreliable,
   which is exactly what the spider's persuade path is).
3. **Maker's-mark lore web.** New examination results plus Korbar
   dialogue hooks:
   - the giant axe bears a dwarven smith's mark — Korbar's *own* forge
     mark (extension of the existing "the battleaxe was actually her
     weapon" lore: she forged it);
   - the padlock bears a maker's mark too: *"Steadfast Lock Co. —
     tested against 47 rogues. The 48th is pending."* (a wink at the
     player; pure prose);
   - asking Korbar about the axe mark unlocks dialogue-path lore: the
     axe is hers.
   Reward: a new +1 attitude dialogue path and richer `will_reveal`
   topics (who abandoned her, why the bag is locked). Connects all
   three set pieces (axe, padlock, Korbar) without changing any puzzle.
4. **Korbar's ladle shelter (bag_floor).** Examinable: her meager
   stash — a party badge (pairs with #3's abandonment dialogue and
   #12's sending stone) and a wineskin of dregs she guards jealously.
   The badge unlocks the abandonment dialogue; the wineskin enables #8.
   Flavor upgrade for the through-line: her plate mail is *why* the
   party ditched her on the stealth mission — it is comically loud.
5. **Save the fly.** If the player frees the fly from the web (DEX
   check, easier with a blade via `using_results`) instead of letting
   it die, one small boon, player's choice of tone:
   - (a) it buzzes ahead and its alarm auto-reveals the spider the
     next time the player enters axe_handle_lower (a `room.entered`
     reaction clearing `spider.hidden`);
   - (b) it flutters down to Korbar and "vouches" for the player
     (+1 attitude).
   - (c) *variant:* a drop of the healing potion (#1) revives it
     entirely — it lives, becoming a small recurring presence that
     grants both (a) and (b) over the course of play. A real
     trade-off: your only healing for a friend.
   Character concept (works whether or not it's saved): the fly
   *claims* to be a polymorphed adventurer — "tell Eldrin I— wait.
   What was I saying?" It can no longer remember; it's a fly. The
   scenario never confirms it. This preserves and deepens the
   existing anti-clue joke ("it's a fly; it doesn't have useful
   information") while making its death land harder. *Engine note:*
   its death reactions just gain a "not freed" condition.
6. **More rapport routes for Korbar.** The 3-cap conversation rapport
   stays, but gifts now also count toward it: giving her the rations
   (#1), the wineskin dregs (#4), or the emergency gin (#13) is a
   rapport effort. Gives quiet players an alternative to sweet-talking,
   without raising the cap. *Engine note:* transfers to living NPCs
   are consent-adjudicated and fire no events, so gifts count via GM
   discretion inside the existing rapport dialogue paths — no new
   machinery needed.
7. **`reveals` strings and knowledge-gated narration.** Add `reveals`
   to the major discoveries (many Results lack them) so the GM briefing
   tracks player knowledge, and extend scenario.md's Narration Notes
   with concrete guidance for post-`knows_bag_of_holding` room
   descriptions (the doc already flags this as a TODO for the scenario
   generator).
8. **Sensory palette and the vibration logic.** Narration guidance
    (scenario.md): the web transmits vibrations — which is *why* the
    spider always detects forcing, *why* stealth must be slow and
    careful (#16), and *why* Korbar's noisy armor is a curse: she can
    never sneak, which is why she never escaped (#4 makes this a
    character beat). Add smell guidance (worse toward the secret
    pocket) and the glow's quality per room. Makes the mechanics feel
    inevitable instead of arbitrary, at zero mechanical cost.
9. **The Bag's instruction label (secret_pocket).** Sewn into the
    pocket's seam: a giant care label, readable on examination.
    - *"Do not wash. Do not iron. Do not place living creatures
      inside. Do not place within another extradimensional space."*
    - *"Contents may shrink by different amounts. This is normal."*
      (canonizes the existing variable-shrinkage whimsy);
    - *"Tears compromise containment."*.
    Fine print requires INT (Arcana) DC 12 and adds a `reveals`
    string; sets flag `read_label`. Fills the emptiest room with the
    adventure's mission statement.
10. **The sending stone (secret_pocket).** One half of a pair of
    sending stones, tossed in the bag because it wouldn't stop buzzing.
	In current state, too heavy too move.  Interactions:
    - `listen` (repeatable): on a good WIS check it crackles alive —
      the party wizard's voice, distant: *"Korbar? Korbar, where did
      you—"* then static. Sets `wizard_voice_heard`, appends a
      `reveals` string; if Korbar is told, contributes to
      rapport. Ties the abandonment lore (#3, #4) to a voice.
    - `speak_into`: the player shouts their name, situation, and
      location into the stone. Nothing comes back. Somewhere, a
      wizard's pocket buzzes. He does not check it.
11. **Emergency gin (secret_pocket).** A hip flask the size of a beer
    barrel. A sip heals 1 HP and is narrated as liquid courage; the
    real use is social — it's the premium rapport gift for Korbar
    (#8), who has been rationing wineskin dregs (#4) for what feels
    like years.  Needs STR check to lug it out of the compartment.
12. **A Bag of Holding within (bag_floor, deep rubbish stage).**
    *The* forbidden D&D-ism. A tiny pouch — at the player's scale, a
    normal-sized Bag of Holding. Examination (INT/Arcana DC 12, or
    free if `read_label` from #11): it is unmistakably a Bag of
    Holding. The player character feels the planes hold their breath.
    - Interaction `open_it`: first attempt *warns* (sets a flag —
      exactly the `the_rip.squeeze_through` two-step pattern);
      confirmed attempt → inline `game_over` (lose): both bags
      rupture, everything is scattered across the Astral Plane,
      narrated with maximum ceremony. This is a new loss *interaction*
      but the same lose-shape as the rip — flagged here in case the
      scope pin is read strictly; if so, the pouch is warning-only
      color.
13. **Genre-satire garnish.**
    - *The astral drifter:* added to `the_rip`'s examinations —
      something vast drifts past outside. It does not notice the
      player. They are glad. (Wonder and menace, one sentence each.)

### Tier 2 — New mechanical options (moderate, reuses engine features)

14. **Sneak past the spider / cut quietly vs. force loudly.** A
    Stealth-based traversal option on the web-blocked path: a slow,
    careful DEX (Stealth) approach (interaction on the webs, DC 13,
    repeatable) that on success opens the passage *without* triggering
    the spider (sets `web_cleared` quietly); on failure the spider
    attacks (an `interaction.used` reaction with `trigger_encounter`).
    Split the existing forcing results the same way: a blade allows a
    quiet DEX-based cut (no provocation on success), brute STR forcing
    always provokes. Turns a flat DC-reduction into a real tactical
    choice; the most on-class addition available for a Rogue. *Engine
    note:* an exit supports only one `traversal_check`, so the sneak is
    an interaction, not an exit variant. *Interlock:* Korbar's clanking
    (#4) imposes disadvantage while she follows; she'll agree to doff
    the armor only once she believes the spider is dead — tying her
    fear arc to the stealth path.
15. **Spider combat polish.** (a) `ai: { flee_below_hp_pct: 30 }` — a
    losing spider breaks off and departs (non-lethal resolution that
    still clears the path; fits "vain, stupid, malicious" → cowardly;
    design call: its flight also sets `web_cleared`). (b) Its bite
    applies the built-in `poisoned` condition on the failed CON save
    (`apply_status_effect` in the existing on-hit failure result) in
    addition to the poison damage — poisoned means disadvantage on the
    player's attacks and ability checks, making the fight scarier and
    the antivenom (#1) more valuable. The status system exists and the
    adventure currently uses none of it.
16. **Arm Korbar.** A new dialogue path `offer_weapon` with
    `using_results` keyed on the toenail sword, dagger, or giant
    lockpick: the player hands over their only weapon — `remove_item`,
    set `korbar_armed` flag, attitude +2 (a genuine gift per the
    attitude conventions).  Payoff: `persuade_fight` becomes available
    at attitude 2 instead of 3 when she's armed. A real sacrifice
    decision exercising the living-NPC transfer path. *Engine note:*
    NPC combat blocks are pre-computed — a transferred weapon
    **cannot** raise her damage at runtime, and consented transfers
    fire no events; hence the dialogue-path modeling. Her fighting
    with the blade stays narrative (or the author raises her base
    `dmg` outright, accepting it applies always).
17. **Enable 5e skills.** scenario.md currently says "Other 5e
    mechanics, including skills, are unused" — that line dates from
    the early-stage engine. *Engine note:* there is no skill-check
    type; skills are `stat_check`s whose `stat` names the skill, with
    proficiency from `player.skill_proficiencies`. Proposal: add a
    Rogue-appropriate list to `default-player.json` (Stealth, Sleight
    of Hand, Investigation, Perception, Deception, Acrobatics, Arcana,
    plus Athletics, Persuasion, Insight as fits) and re-express
    relevant checks as skill checks — notice spider → Perception,
    rubbish finds → Investigation, web forcing → Athletics, flattery →
    Persuasion, overheard muttering → Insight (#7), rip squeeze →
    Acrobatics, keyway climb → Acrobatics and lock tumblers → Sleight
    of Hand (#26), label fine print and scroll reading → Arcana
    (#11, #25, #27, #28). Keep DCs as-is; proficiency (+2) is the
    reward.
18. **Soft-item problem-solving, blessed by the corpus.** *Engine
    note:* `using_results` keys are hard-item IDs or the `"*"`
    wildcard; soft items have no IDs and carry no mechanical weight
    beyond the improvised-weapon bridge — so blessings for soft items
    are GM guidance, not corpus hooks. Proposal: (a) GM guidance in
    scenario.md listing sanctioned improvisations — a frayed rope
    negates drop damage, a boot heel or tin cup as a step-up eases the
    padlock reach, a wad of webbing as adhesive, spider venom (#24)
    as a one-shot blade coating, giant corks/bottles as improvised
    weapons via the existing patch; (b) a few `"*"` wildcard
    `using_results` on key obstacles where *any* hard item could
    plausibly help, with adjudication notes.
19. **A safe rest spot.** *Engine note:* there is no safe-rest-
    location construct; the ruling LLM decides whether a rest is
    fictionally safe, so this is authored as prose. Add: once Korbar's
    attitude ≥ 1, her ladle shelter is narrated as safe enough to rest
    (long rest heals the player and, per engine, a following Korbar);
    the axe head is safe once the spider is gone. Optional garnish: a
    `rest.completed` reaction that lets a resting player overhear one
    of Korbar's muttering fragments (#7) for free. Makes the combat
    path survivable.
20. **Harvest the spider.** If it dies, its corpse yields trophies the
    social paths never get: a fang (explicit physical evidence for
    `convince_spider_dead`, skipping the CHA check — already implied
    by the scenario, now concrete) and a venom sac (soft item;
    GM-blessed one-shot blade coating or bait ingredient, per #21).
    Makes the combat path pay like the social ones.
21. **Scroll of Sleep (the husk's bookmark, #2).** The previous
    prisoner died holding a spell he never got to cast. Item with a
    `read_at_spider` interaction (condition: spider alive, present,
    not departed): `apply_status_effect { id: incapacitated, rounds:
    10, target: spider }` + `remove_item_count` on the scroll.
    **No save** — faithful to SRD sleep (HP-threshold, no save; the
    spider's 14 HP is under any reasonable threshold; the pack's own
    `sleep` spell approximates it with a WIS save, but a scroll can do
    better). Satire: *Sleep* — the spell that has ended more low-level
    encounters than every sword in history combined. *Engine notes:*
    the spider's attack reactions (`web_spider_attack`,
    `spider_attacks_on_entry`) gain a "not
    `status_effect:spider.incapacitated`" condition; attacking the
    sleeping spider starts combat with it incapacitated (a brutal
    opening — intended); the social/stealth player can instead simply
    walk past. One use.
22. **Pick the giant lock (axe_head).** The padlock's keyway, at the
    player's scale, is a narrow tunnel. A Rogue can attempt to pick
    the lock, but at a vastly different scale than what they're used
    to.  With an INT check, the player realizes how to do it.  It's a
    two-person job: Korbar holds the lockpick from inside the bag, and
    the player climbs across the pick and into the lock, and guides
    the pick head into the tumblers, one by one.  It's an action
    set-piece with difficult stat checks, but yields an escape method
    if the key isn't found, or the key drops into the Astral Plane.
23. **The spider's hoard (axe_handle_lower).** Of course the vain
    spider has a hoard — it's a D&D monster. Revealed by searching the
    web once the spider is dead or departed: a shiny drift of copper
    pieces, a wooden button, a bottle cap, all too cumbersome to
    carry.
	
