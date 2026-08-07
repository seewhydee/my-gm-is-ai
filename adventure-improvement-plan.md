# Densifying "You're Trapped in a Bag!" — Proposal List (2nd draft)

**Status: proposals only, no implementation.** The user wants the
bag-of-holding adventure made "denser" while keeping its scope fixed:
same 5 rooms (axe_head, axe_handle_upper, axe_handle_lower, bag_floor,
secret_pocket), same 3 NPCs (fly, spider, korbar). This document is the
deliverable: a menu of proposals for the user to pick from. Any adopted
proposal would later be implemented across `scenario.md`,
`scenario-map.md`, and `corpus.json` (kept in sync, validated with
`scripts/validate_adventure.py`), plus `default-player.json` where
noted.

**Second-draft changes:** every first-draft proposal was feasibility-
checked against the engine docs (`schema/corpus.md`, `schema/events.md`,
`doc/combat.md`, `doc/npcs.md`, `doc/rests.md`, `doc/soft.md`,
`doc/gear.md`, `doc/player-stats.md`, `schema/srd-5e-pack.md`); a few
were corrected where the first draft assumed engine features that don't
exist (marked *Engine note*). Nine new proposals were added (##9, #10,
#11, #12, #21, #22, #25, plus the density map and engine-facts
sections), and the lore proposals were rewoven into three connected
story threads.

## What "denser" means here

Scope is pinned (rooms, NPCs, win/lose conditions), so density must come
from five levers:

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
   18 SRD skills (#18). The adventure should reward playing a Rogue.

## Current shape (for orientation)

- One golden path: find key in secret pocket → haul it up (STR checks,
  Korbar assist) → padlock → win.
- Spider: fight it, or flatter to attitude 0 then persuade (armed only;
  otherwise it lies).
- Korbar: rapport (+1 ×3 cap), convince spider dead, follower, key
  hauler, optional fighter.
- Fly: single warning, then dies.
- Finds: toenail sword, handkerchief, key. That's it.

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
  an NPC entity ID**), `increment_entity_state` (negative deltas OK),
  `remove_item`, `set_player_location`.
- Built-in SRD conditions usable out of the box: `poisoned`,
  `restrained`, `frightened`, etc. Custom status effects are declarable.
- Combat AI supports `ai.flee_below_hp_pct` (1–99), `ai.passive`,
  `ai.targeting`. NPC combat blocks are **pre-computed**: nothing can
  change an NPC's damage/AC at runtime, and consented transfers to
  living NPCs fire no state-change events (gate on dialogue paths or
  attitude instead).
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
  armor tables, and 7 spells. A corpus entity reusing a pack ID
  replaces the pack entry wholesale (e.g., to add `cure_status_effects`
  to a potion).
- On-hit effects only fire against the player. Encounter-rule Results
  may combine damage/status/flags with `start_combat` in one atomic
  result (opening effects). One encounter per turn.

## Proposals

### Tier 1 — Enrichment (low risk, no new solution paths)

1. **Staged rubbish finds (bag_floor).** Add 2–3 more hard-item
   discoveries to the rubbish pile, gated behind successive rigorous
   examinations with rising DCs (the pattern already established by
   toenail → handkerchief):
   - an *unbroken* potion bottle among the empties →
     `potion_of_healing` (ships in the SRD data pack — zero new
     authoring, and a real reward for the combat path). *Engine note:*
     reusing the pack ID lets us replace it wholesale — worth adding
     `cure_status_effects: ["poisoned"]` to its `drink` interaction so
     it doubles as antivenom once #16b lands;
   - edible (if revolting) rations → giftable to Korbar (see #7) or
     nibbled for 1 HP;
   - a giant copper piece → throwable distraction (see #19).
2. **A previous prisoner's web husk (axe_handle_upper) — the
   locksmith.** One of the wrapped masses, on rigorous examination,
   turns out to be a desiccated shrunken *person* — a previous
   prisoner. Loot: a normal-sized `dagger` (SRD pack item; a
   simple-weapon alternative to the toenail, and it matters for #25)
   and a tattered note: "the key below opens the lock above" — a
   redundant hint path toward the secret pocket, useful if the player
   never befriends Korbar and fails the WIS 15 handkerchief check.
   Design intent: this husk is the first beat of the **locksmith
   thread** (beats: #2 → #3 → #4). He was the locksmith of Korbar's
   old party — the man who made the padlock, who hid the key, and who
   never got out.
3. **Secret pocket epilogue (secret_pocket).** The pocket currently
   holds only the key — anticlimactic. Add scratches on the canvas
   wall: tally marks that stop mid-count, and the previous prisoner's
   last words (dread + an explicit hint about the padlock and what
   squeezing through the rip means — "do not go into the gray"). Second
   beat of the locksmith thread; makes the final room land emotionally.
4. **Maker's-mark lore web.** New examination results plus Korbar
   dialogue hooks:
   - the giant axe bears a dwarven smith's mark — Korbar's *own* forge
     mark (extension of the existing "the battleaxe was actually her
     weapon" lore: she forged it);
   - the padlock (examined closely from the rip) bears a *different*
     mark, and so does the key — the locksmith's mark (#2, #3);
   - asking Korbar about either mark unlocks dialogue-path lore: the
     axe is hers; she recognizes the padlock mark as her party's
     locksmith — which raises the question she avoids: if the
     locksmith ended up in here too, what did her party *actually* do?
   Reward: a new +1 attitude dialogue path and richer `will_reveal`
   topics (who abandoned her, why the bag is locked). Connects all
   three set pieces (axe, padlock, Korbar) without changing any
   puzzle.
5. **Korbar's ladle shelter (bag_floor).** Examinable: her meager
   stash — a party badge (pairs with #4's abandonment dialogue) and a
   wineskin of dregs she guards jealously. The badge unlocks the
   abandonment dialogue; the wineskin enables #7.
6. **Save the fly.** If the player frees the fly from the web (DEX
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
   Charming, cheap, and ties the three NPCs together. *Engine note:*
   its death reactions just gain a "not freed" condition.
7. **More rapport routes for Korbar.** The 3-cap conversation rapport
   stays, but gifts now also count toward it: giving her the rations
   (#1) or drink (#5) is a rapport effort. Gives quiet players an
   alternative to sweet-talking, without raising the cap. *Engine
   note:* transfers to living NPCs are consent-adjudicated and fire no
   events, so gifts count via GM discretion inside the existing
   rapport dialogue paths — no new machinery needed.
8. **`reveals` strings and knowledge-gated narration.** Add `reveals`
   to the major discoveries (many Results lack them) so the GM briefing
   tracks player knowledge, and extend scenario.md's Narration Notes
   with concrete guidance for post-`knows_bag_of_holding` room
   descriptions (the doc already flags this as a TODO for the scenario
   generator).
9. **The rubbish is *yours*.** Upgrade the existing
   `knows_rubbish_is_supplies` realization: on the follow-up INT check
   (or a third examination), the player recognizes specific items as
   their own — your dented tin cup, your chipped die, your single moldy
   boot. Someone robbed you on that night out and dumped you in here
   with your own discarded pack. Personal stakes, explains the
   introduction, and gives Korbar a new `will_reveal` (she watched
   "the tall ones" drop you in). Optional variant: keep it ambiguous
   ("some adventurer's supplies") if the user prefers the mystery
   open-ended.
10. **The fly's dying fragment.** Even on the default path (fly not
    saved), it gasps one extra fragment with its last breath — GM's
    pick or player's choice: "it loves pretty words…" (teaches that
    flattery works on the spider) or "the clanking one knows where the
    wipe hides a door…" (points at the handkerchief). One free hint
    that makes the fly more than a warning dispenser.
11. **Korbar's muttering.** Her drunken dirges contain hints. On
    entering bag_floor or in dialogue, a WIS (Insight) check (DC 12,
    repeatable) catches fragments: one verse hints at the handkerchief
    ("…wiped her nose and hid the door beneath…"), another at the
    spider's vanity ("…eight eyes gleaming, it preens and dreams…").
    Redundant hint paths *and* character color; pairs with #10 and #12.
12. **Sensory palette and the vibration logic.** Narration guidance
    (scenario.md): the web transmits vibrations — which is *why* the
    spider always detects forcing, *why* stealth must be slow and
    careful (#13), and *why* Korbar's noisy armor is a curse: she can
    never sneak, which is why she never escaped. Add smell guidance
    (worse toward the secret pocket) and the glow's quality per room.
    Makes the mechanics feel inevitable instead of arbitrary, at zero
    mechanical cost.

### Tier 2 — New mechanical options (moderate, reuses engine features)

13. **Sneak past the spider / cut quietly vs. force loudly.** A
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
    imposes disadvantage while she follows; she'll agree to doff the
    armor only once she believes the spider is dead — tying her fear
    arc to the stealth path.
14. **Bait, distraction, and the dark bargain.** Offer the spider food
    — the fly's corpse, a moldy sandwich, or the rations (#1) — as a
    dialogue path: sets a short-lived `spider_distracted` numeric room
    state (decremented on `turn.end`) that suppresses
    `web_spider_attack` and grants one unopposed traversal. Dark
    variant: a Deception check (DC 11) to convince the stupid spider
    that the clanking two-legs below is already dead — it loses
    interest in its territory and departs (same outcome as
    `persuade_passage`, but built on lies instead of arms). Cruel
    role-players may instead *promise* it future prey; GM adjudicates
    Korbar's attitude hit if she overhears. Dark humor, fits the tone,
    uses existing primitives.
15. **Environmental opening (axe_handle_upper → lower).** Shove one of
    the heavy wrapped masses off the upper handle onto the spider below
    (STR DC 13): opening effect before combat — a negative
    `increment_entity_state` on `spider.current_hp` and/or a brief
    `restrained` status (`apply_status_effect` with `target: spider`),
    combined with `start_combat` in one encounter result. Rewards
    spatial play between two existing rooms.
16. **Spider combat polish.** (a) `ai: { flee_below_hp_pct: 30 }` — a
    losing spider breaks off and departs (non-lethal resolution that
    still clears the path; fits "vain, stupid, malicious" → cowardly;
    design call: its flight also sets `web_cleared`). (b) Its bite
    applies the built-in `poisoned` condition on the failed CON save
    (`apply_status_effect` in the existing on-hit failure result) in
    addition to the poison damage — poisoned means disadvantage on the
    player's attacks and ability checks, making the fight scarier and
    the potion (#1) more valuable. The status system exists and the
    adventure currently uses none of it.
17. **Arm Korbar.** A new dialogue path `offer_weapon` with
    `using_results` keyed on the toenail sword / dagger: the player
    hands over their only weapon — `remove_item`, set `korbar_armed`
    flag, attitude +2 (a genuine gift per the attitude conventions).
    Payoff: `persuade_fight` becomes available at attitude 2 instead of
    3 when she's armed. A real sacrifice decision exercising the
    living-NPC transfer path. *Engine note (correction to first
    draft):* NPC combat blocks are pre-computed — a transferred weapon
    **cannot** raise her damage at runtime, and consented transfers
    fire no events; hence the dialogue-path modeling. Her fighting with
    the blade stays narrative (or the author raises her base `dmg`
    outright, accepting it applies always).
18. **Enable 5e skills.** scenario.md currently says "Other 5e
    mechanics, including skills, are unused" — that line dates from the
    early-stage engine. *Engine note:* there is no skill-check type;
    skills are `stat_check`s whose `stat` names the skill, with
    proficiency from `player.skill_proficiencies`. Proposal: add a
    Rogue-appropriate list to `default-player.json` (Stealth, Sleight
    of Hand, Investigation, Perception, Deception, Acrobatics, plus
    Athletics, Persuasion, Insight as fits) and re-express relevant
    checks as skill checks — notice spider → Perception, rubbish finds
    → Investigation, web forcing → Athletics, flattery → Persuasion,
    overheard muttering → Insight (#11), rip squeeze → Acrobatics,
    lockpick → Sleight of Hand (#23), canvas climb → Athletics (#25).
    Keep DCs as-is; proficiency (+2) is the reward.
19. **Soft-item problem-solving, blessed by the corpus.** *Engine note
    (correction to first draft):* `using_results` keys are hard-item
    IDs or the `"*"` wildcard; soft items have no IDs and carry no
    mechanical weight beyond the improvised-weapon bridge — so blessings
    for soft items are GM guidance, not corpus hooks. Proposal: (a) GM
    guidance in scenario.md listing sanctioned improvisations — a
    frayed rope negates drop damage, a thrown copper piece (#1) grants
    one Stealth attempt against the spider, a boot heel or tin cup as a
    step-up eases the padlock reach, a wad of webbing as adhesive,
    spider venom (#22) as a one-shot blade coating; (b) a few `"*"`
    wildcard `using_results` on key obstacles where *any* hard item
    could plausibly help, with adjudication notes.
20. **A safe rest spot.** *Engine note (correction to first draft):*
    there is no safe-rest-location construct; the ruling LLM decides
    whether a rest is fictionally safe, so this is authored as prose.
    Add: once Korbar's attitude ≥ 1, her ladle shelter is narrated as
    safe enough to rest (long rest heals the player and, per engine, a
    following Korbar — which the rest system already does for
    followers); the axe head is safe once the spider is gone. Optional
    garnish: a `rest.completed` reaction that lets a resting player
    overhear one of Korbar's muttering fragments (#11) for free. Makes
    the combat path survivable.
21. **The egg sac.** Hidden in the dense webs of axe_handle_lower
    (rigorous WIS DC 14 examination — risky, with the spider lurking in
    the same room). Three interactions: (a) *threaten* — unlocks a new
    dialogue path on the spider: Intimidation DC 12, non-repeatable;
    success = it grudgingly lets the player pass and departs; failure =
    immediate attack. (b) *destroy* — the spider attacks at once,
    enraged. (c) leave it. The vain, malicious spider cares about
    nothing else — that's the leverage. Moral texture plus a Rogue's
    way through, at real risk.
22. **Harvest the spider.** If it dies, its corpse yields trophies the
    social paths never get: a fang (explicit physical evidence for
    `convince_spider_dead`, skipping the CHA check — already implied by
    the scenario, now concrete) and a venom sac (soft item; GM-blessed
    one-shot blade coating or bait ingredient, per #19). Makes the
    combat path pay like the social ones.

### Tier 3 — Structural alternates (bigger design change; opt-in)

23. **Lockpick the padlock (alternate win route).** The player is a
    Rogue with no lockpicks — but the husk (#2) can yield a wire pick,
    or quill/spoon soft items can serve (GM-adjudicated, perhaps DC +2
    without a proper pick). Sleight of Hand DC ~18, non-repeatable;
    failure *jams* the lock — implemented as split `insert_key`
    variants with worsened DCs (the split-interaction pattern the
    corpus already uses). Creates a genuine second way out — high
    risk, high cost, thematically perfect for the class. Flagged
    Tier 3 because it changes the adventure's single-golden-path
    character; the key route stays canonical and safer.
24. **Rig a hoist for the key.** With frayed rope (soft item) and the
    axe head as anchor, an INT (Investigation) → Athletics sequence
    (interaction with `then_check`) hauls the key from bag floor to axe
    head directly, bypassing the per-room heavy-key STR checks. Rewards
    soft-item creativity with a mechanical payoff; solo alternative to
    recruiting Korbar as key-hauler. The final `insert_key` check still
    applies.
25. **Climb the canvas with a blade.** The dagger or toenail sword as a
    climbing pick: a hidden exit from bag_floor (and/or
    axe_handle_lower) straight to axe_head, bypassing the webs and the
    spider entirely. *Engine note:* clean implementation — exit
    `condition` on `tag:weapon` (invisible until the player is armed),
    Athletics DC 15 traversal check, failure Result carrying 1d6 fall
    damage; gate it with `unless tag:heavy` so the key cannot be
    climbed up with — the key route stays canonical. Structural because
    it bypasses the central obstacle; cheap to build.

### Deliberately NOT proposed

- No new rooms, NPCs, or win/lose conditions. (The egg sac and the
  husk are features/items, not NPCs.)
- The rip stays lethal and the key-loss cascade stays harsh — that edge
  is the adventure's identity; softening it would flatten the tension.
- No time-pressure mechanics (e.g., spider growing bolder per turn) —
  adds a failure axis the gentle exploratory tone doesn't need.
- No NPC equipment system — the engine pre-computes NPC combat stats
  and cannot equip transferred items (see #17); proposals work around
  this rather than fighting it.
- No off-screen NPC events (e.g., the spider hunting Korbar while the
  player is elsewhere) — the engine resolves everything in the
  player's scene.

## How it connects (density map)

Three story threads weave the proposals together:

- **The locksmith thread:** husk + note (#2) → pocket scratches (#3) →
  key/padlock maker's marks (#4) → Korbar's recognition (#4). Answers
  "who was here before, and what happened to them."
- **The abandonment thread:** party badge (#5) → axe/padlock marks
  (#4) → Korbar's story (#4, #9) → "the tall ones" who dumped the
  player (#9). Answers "who did this, and to whom."
- **The vanity thread:** fly's fragment (#10) → Korbar's muttering
  (#11) → flattery mechanics (existing) → egg-sac leverage (#21).
  Answers "how do you get past the spider without a fight."

Room/NPC coverage (proposal numbers):

| Where        | Proposals                                              |
|--------------|--------------------------------------------------------|
| axe_head     | #4, #19, #20, #23, #24, #25                            |
| handle_upper | #2, #6, #15                                            |
| handle_lower | #12, #13, #14, #15, #16, #21, #22, #25                 |
| bag_floor    | #1, #5, #7, #9, #11, #19, #20, #24, #25                |
| secret_pocket| #3, #4                                                 |
| fly          | #6, #10                                                |
| spider       | #13, #14, #15, #16, #21, #22                           |
| korbar       | #4, #5, #7, #9, #11, #13 (interlock), #17, #20         |

Every room gains 2+ new beats; every NPC gains knowledge, a hook, or a
choice; the spider gains four non-combat vectors (stealth #13, bait
#14, eggs #21, dark bargain #14) on top of fight and flattery.

## Suggested grouping if adopted

If the user adopts everything in Tiers 1–2, the natural implementation
order is: #18 (skills groundwork, incl. `default-player.json`) →
#1–#5, #9 (finds + lore threads) → #8, #12 (reveals + narration
guidance) → #13–#16, #21, #22 (spider options) → #6, #7, #10, #11,
#17, #20 (NPC depth) → #19 (soft-item blessings), each landed in
scenario.md + scenario-map.md + corpus.json with
`scripts/validate_adventure.py` run after each batch. Tier 3 (#23–#25)
is opt-in and lands last, since it changes the golden-path character.
