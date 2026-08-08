# Densifying "You're Trapped in a Bag!" — Proposal List (rev 3)

**Status: proposals only, no implementation.** The user wants the
bag-of-holding adventure made "denser" while keeping its scope fixed:
same 5 rooms (axe_head, axe_handle_upper, axe_handle_lower, bag_floor,
secret_pocket), same 3 NPCs (fly, spider, korbar), same win/lose
shape (padlock/key win; rip and key-loss losses; player death is an
engine default, not a declared game-over). This document is the
deliverable: a menu of proposals for the user to pick from. Any
adopted proposal would later be implemented across `scenario.md`,
`scenario-map.md`, and `corpus.json` (kept in sync, validated with
`scripts/validate_adventure.py`), plus `default-player.json` where
noted.

**The satirical through-line.** D&D magic items are dangerous,
ridiculous, and poorly labeled — and the Bag of Holding is the
archetype. The through-line runs from the care label's warnings (#9)
through the poison potion's fine print (#1) and the
Bag-of-Holding-within's catastrophic interaction (#12) to Korbar's
abandonment via the bag (#3, #4): every magical find either *does*
something or *says* something about the absurdity of living inside a
magic item. The math stays honest (real SRD spells, real conditions,
real DCs); the jokes live in the prose.

**Rev 3 changes** (per user feedback — add magical loot; fix audit
findings): added three magical finds — an invisibility potion (#24,
in the bag_floor rubbish via #1), a Scroll of Mage Armor (#25, in the
husk's loot via #2), and a Scroll of Faerie Fire (#26, an oversized
scroll in the bag_floor rubbish via #1). These form a new Tier 3
(Magical mechanics), addressing the rev 2 gap where the promised
magical-mechanics proposals were never written. Corrected engine
facts: `increment_entity_state` cannot affect reserved `current_hp`
— the NPC HP lever is `set_entity_state`; the SRD pack ships 26
conditions and 29 spells (not 23/7); `duration` also supports
`until_turn_start`. Corrected the "Current shape" section: `axe_head`
is not a thinnest spot. Repaired all stale cross-references (ten were
broken by the rev 2 renumbering). Fixed proposal #15 (spider flee must
set `departed`), noted #22's Korbar dependency and #17's
scenario-map.md update, fleshed out #5's engine note.

**Rev 2 changes** (per user feedback — more creativity, whimsy,
D&D-isms, more magic): added the satirical through-line and density
lever 6; expanded the engine facts with magic-authoring capabilities;
added proposals #11–#13 (whimsy/satire finds); folded the previous
prisoner, the polymorph gag, and the potion vats into richer versions
of the rev 1 items. Rev 1's low-hanging fruit is retained essentially
intact.

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
   18 SRD skills (#17). The adventure should reward playing a Rogue.
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
- Finds: toenail sword, handkerchief, key (plus Korbar's plate
  armor, worn and untakeable). The handkerchief is a feature, not a
  hard item.
- Thinnest spots: `secret_pocket` is nearly empty (one item, no
  examinations), and there is **no usable magic anywhere** — potions
  exist only as empty bottles. That last gap is rev 3's main target.
  (`axe_head` is comparatively rich: it has the padlock, the rip, the
  axe, and a room-level INT examination of the magical glow.)

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
  an NPC entity ID**), `cure_status_effects`,
  `increment_entity_state` (negative deltas OK on declared numeric
  fields — but reserved fields like `current_hp` are rejected; the
  only direct HP lever on an NPC outside combat is `set_entity_state`
  on `current_hp`), `remove_item` / `remove_item_count`, `add_item`,
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
  `status_effects` (`scope`, `duration` rounds/until_cleared/
  until_turn_start, 5e `system_effects`); **no save-ends mechanic**
  exists.
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
  armor tables, 26 conditions, and 29 spells (including `sleep`,
  `mage_armor`, `faerie_fire`, `invisibility`, `hold_person`, `blur`,
  and `charm_person`). A corpus entity reusing a pack ID replaces the
  pack entry wholesale. The built-in `invisible` condition grants
  advantage on attacks / disadvantage against; `mage_armor` sets base
  AC to 13 + DEX (`until_cleared`); `faerie_fire` grants advantage
  against the affected target and negates invisibility.
- On-hit effects only fire against the player. Encounter-rule Results
  may combine damage/status/flags with `start_combat` in one atomic
  result (opening effects). One encounter per turn.

## Proposals

### Tier 1 — Enrichment & whimsy (low risk, no new solution paths)

1. **Staged rubbish finds (bag_floor).** Add more hard-item
   discoveries to the rubbish pile, gated behind successive rigorous
   examinations with rising DCs (the pattern already established by
   toenail → handkerchief):
   - Four *unbroken* giant potion bottles (disambiguated by color),
     which can be uncapped with a STR check. In the player's shrunken
     state each bottle is the size of a vat: they must be drunk from
     directly and can't be carried. The potion types are initially
     unknown and can be teased out with INT (Arcana/Investigation)
     checks — or identified the old-fashioned way, by sipping
     (a taste test; the poison one costs a CON save vs. a small
     poison-damage lick, satirizing the classic "sip to identify"
     ritual). One is a long-duration antivenom (pairs with #15's
     `poisoned` condition), one heals, one grants invisibility (#24),
     and one is a poison (insta-loss — the fine print kills; see the
     through-line). *Scope note:* the poison potion's insta-loss is a
     new lose interaction; if the scope pin is read strictly, the
     poison bottle is warning-only color (like #12's bag-within).
   - Edible (if revolting) rations → giftable to Korbar (see #6) or
     nibbled for 1 HP.
   - Giant Lockpick — the size of a two-handed staff (and can be used
     as such), and also to attempt picking the padlock (#22).
   - A giant Scroll of Faerie Fire (#26) — twice the player's height,
     too large to carry; found in a later rubbish-examination stage.
2. **A previous prisoner's web husk (axe_handle_upper).** One of the
   wrapped masses, on rigorous examination, turns out to be a
   desiccated shrunken *person* — a previous prisoner. Loot: a
   normal-sized `dagger` (SRD pack item; a simple-weapon alternative
   to the toenail), a **journal**, a Scroll of Mage Armor (#25, tucked
   in the journal's pages), and — lodged in the husk's skeletal grip —
   a Scroll of Sleep (#21, the spell the prisoner never got to cast).
   The journal satirizes the
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
   #10's sending stone) and a wineskin of dregs she guards jealously.
   The badge unlocks the abandonment dialogue; the wineskin enables #6.
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
   its death reactions just gain a "not freed" condition. *Engine
   note:* freeing the fly requires a new interaction on the `webs`
   entity (a DEX check, with `using_results` keyed on a blade for an
   easier DC) whose success sets a `fly_freed` flag; the existing
   death reactions (`fly_dies_after_dialogue`,
   `fly_dies_on_departure`) gain a `fly_freed == false` condition.  If
   freed, the fly either departs to `bag_floor` (for boon (b), a
   `set_player_location`-style relocation or a narration-only move)
   or lingers in `axe_handle_upper` (for boon (a), a `room.entered`
   reaction on `axe_handle_lower`).  The freed fly needs its own
   post-free reactions (the auto-reveal or the Korbar vouch), modeled
   as entity reactions on `fly` gated on `fly_freed == true`.
6. **More rapport routes for Korbar.** The 3-cap conversation rapport
   stays, but gifts now also count toward it: giving her the rations
   (#1), the wineskin dregs (#4), or the emergency gin (#11) is a
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
     careful (#14), and *why* Korbar's noisy armor is a curse: she can
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
    (#6), who has been rationing wineskin dregs (#4) for what feels
    like years.  Needs STR check to lug it out of the compartment.
12. **A Bag of Holding within (bag_floor, deep rubbish stage).**
    *The* forbidden D&D-ism. A tiny pouch — at the player's scale, a
    normal-sized Bag of Holding. Examination (INT/Arcana DC 12, or
     free if `read_label` from #9): it is unmistakably a Bag of
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
     fear arc to the stealth path. *Mage armor interlock:* if the
     player reads the Scroll of Mage Armor (#25) on Korbar, she gains
     AC 13 + DEX without plate — she may agree to doff it *before* the
     spider is dead, since she still has magical protection. This
     opens the stealth path without first resolving the spider, at the
     cost of the scroll.
15. **Spider combat polish.** (a) `ai: { flee_below_hp_pct: 30 }` — a
    losing spider breaks off and departs (non-lethal resolution that
    still clears the path; fits "vain, stupid, malicious" → cowardly;
    design call: its flight also sets `web_cleared` **and
    `departed = true`** — without `departed`, the
    `spider_attacks_on_entry` reaction would re-trigger combat on
    the player's next re-entry, since the spider is still alive and
    now revealed). (b) Its bite
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
    the early-stage engine (scenario-map.md §1A repeats the same
    claim; both documents need updating). *Engine note:* there is no
    skill-check type; skills are `stat_check`s whose `stat` names the
    skill, with proficiency from `player.skill_proficiencies`.
    Proposal: add a Rogue-appropriate list to `default-player.json`
    (Stealth, Sleight of Hand, Investigation, Perception, Deception,
    Acrobatics, Arcana, plus Athletics, Persuasion, Insight as fits)
    and re-express relevant checks as skill checks — notice spider →
    Perception, rubbish finds → Investigation, web forcing →
    Athletics, flattery → Persuasion, overheard muttering → Insight
    (#7), rip squeeze → Acrobatics, keyway climb → Acrobatics and
    lock tumblers → Sleight of Hand (#22), label fine print and
    scroll reading → Arcana (#9, #21, #25, #26). Keep DCs as-is;
    proficiency (+2) is the reward.
18. **Soft-item problem-solving, blessed by the corpus.** *Engine
    note:* `using_results` keys are hard-item IDs or the `"*"`
    wildcard; soft items have no IDs and carry no mechanical weight
    beyond the improvised-weapon bridge — so blessings for soft items
    are GM guidance, not corpus hooks. Proposal: (a) GM guidance in
    scenario.md listing sanctioned improvisations — a frayed rope
    negates drop damage, a boot heel or tin cup as a step-up eases the
     padlock reach, a wad of webbing as adhesive, spider venom (#20)
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
    GM-blessed one-shot blade coating or bait ingredient, per #18).
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
    *Dependency note:* this requires Korbar to be following the player
    in `axe_head`, which requires `believes_spider_dead == true` and
    `attitude >= 1`. The spider obstacle must still be resolved
    (killed, persuaded, fled, or the player lies convincingly) before
    lock-picking is possible — it is an alternative *win method*, not
     a path that bypasses the spider entirely.
23. **The spider's hoard (axe_handle_lower).** Of course the vain
    spider has a hoard — it's a D&D monster. Revealed by searching the
    web once the spider is dead or departed: a shiny drift of copper
    pieces, a wooden button, a bottle cap, all too cumbersome to
    carry.

### Tier 3 — Magical mechanics (new finds, reuses SRD pack)

24. **Invisibility potion (bag_floor rubbish, via #1).** One of the
    four potion vats is a Potion of Invisibility. Drinking it (a
    `drink` interaction on the feature, like the other vats) applies
    the built-in `invisible` condition (`apply_status_effect { id:
    invisible, target: player }` — the condition should be overridden
    in the corpus `status_effects` to add `scope: persistent,
    duration: until_cleared`, since the built-in has no duration):
    advantage on the player's attacks, disadvantage on attacks
    against the player. The effect persists across rooms and until
    cleared by starting combat or taking a similarly revealing action
    (engine clears `invisible` when the player attacks). *Design
    payoff:* a magical alternative to the Stealth path (#14) — drink,
    then walk through the web. But the web transmits vibrations (#8),
    so invisibility alone does not guarantee undetected passage: the
    spider may still sense the player through the web. The surest
    combo is invisibility *plus* a quiet DEX (Stealth) cut, which
    together make the spider's notice check nearly futile. This gives
    a Rogue with no weapon and no ally a viable solo path past the
    spider, at the cost of one potion (and the risk of guessing wrong
    — the potions are unidentified until tasted or Arcana-checked).
    *Engine note:* the potion is a feature (vat-sized, can't be
    carried), so the player must drink it in `bag_floor` and then
    travel to `axe_handle_lower` while the effect persists. One use
    (the vat is drained).

25. **Scroll of Mage Armor (the husk, via #2).** Found in the husk's
    journal alongside the dagger and the Scroll of Sleep (#21). A
    scroll with a `read` interaction that applies the built-in
    `mage_armor` condition (`apply_status_effect { id: mage_armor,
    target: <target> }` — the built-in condition is already `scope:
    persistent, duration: until_cleared`): the target's base
    AC becomes 13 + DEX modifier, persisting until the target dons
    armor or the effect is cleared. `remove_item_count` consumes the
    scroll. *Target choice — the meaningful decision:*
    - **Cast on Korbar:** she gains AC 13 (DEX 10) without her plate
      mail. This is worse than AC 18, but it lets her doff the
      comically loud armor *before* the spider is dead — directly
      enabling the Stealth path (#14 interlock). The player trades a
      scroll for a stealthy ally.
    - **Cast on self:** the player gains AC 14 (DEX 13, +1), up from
      AC 11. A pure survivability upgrade for the combat path —
      valuable against the spider's +1-to-hit bite.
    The scroll cannot do both. A player who finds the husk gets two
    scrolls (Sleep and Mage Armor) and must choose how to allocate
    them across the spider obstacle and Korbar's fear arc. *Engine
    note:* the pack's `mage_armor` spell targets `self` and limits
    duration to 1 round — a scroll as an item interaction bypasses
    both limitations: the `apply_status_effect` Result can target any
    entity ID, and the `mage_armor` condition's own `duration` is
    `until_cleared`.

26. **Scroll of Faerie Fire (bag_floor rubbish, via #1).** A giant
    scroll, twice the player's height, found in a deep rubbish-
    examination stage. Too large to carry (a feature, not an item),
    like the potion vats. Interactions:
    - `unfurl`: requires a STR check (DC 12) to wrestle the giant
      parchment open. On failure, the scroll snaps back shut (no
      effect, repeatable).
    - `read_aloud` (available only once unfurled): casts Faerie Fire
      in place. `apply_status_effect { id: faerie_fire, target:
      <target>, rounds: 10 }` — the affected creature is outlined in
      light: attack rolls against it have advantage, and it cannot
      benefit from invisibility. No DEX save (a scroll can do better
      than the pack's spell, which requires one; cf. #21's Sleep
      scroll).
    *Design tension — cast in place:* the scroll can only be read in
    `bag_floor`, but the spider is in `axe_handle_lower`. The only
    creature present is Korbar — and faerie firing your own ally is
    counterproductive (she takes attack disadvantage from any future
    foe). The scroll is thus a *deliberate red herring* for the
    combat path: a D&D treasure that is mechanically real but
    situationally useless, satirizing the "find a scroll you can't
    effectively use" experience. *Possible non-combat use:* the
    faerie fire's light could reveal hidden things in the rubbish —
    if the author wishes, the `read_aloud` Result can additionally
    set `handkerchief.hidden = false` (skipping the normal WIS DC 15
    check), modeling the magical light illuminating the concealed
    flap. This gives the scroll a puzzle utility that rewards
    thorough searchers who find it before the handkerchief.
	
