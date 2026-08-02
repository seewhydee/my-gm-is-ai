# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for llm/ruling_validation.py — semantic validation of rulings."""

from __future__ import annotations

from mgmai.llm.ruling_validation import (
    validate_positioning_assertion,
    validate_ruling_action,
)
from mgmai.models.actions import (
    CombatAction,
    GearAction,
    InteractAction,
    MoveAction,
    PositioningAssertion,
    TalkAction,
    TransferAction,
    UseAbilityAction,
    WaitAction,
)
from mgmai.models.briefing import (
    BriefingEntity,
    BriefingExit,
    BriefingRoom,
    CombatBriefing,
    EquippedItemBriefing,
    GMBriefing,
    PlayerStateBriefing,
)


def _combat_briefing(
    abilities: list[dict] | None = None,
) -> GMBriefing:
    return GMBriefing(
        adventure_title="Test",
        setting="test",
        tone="neutral",
        turn=1,
        current_room=BriefingRoom(
            id="arena",
            name="Arena",
            description="A fighting pit.",
            exits_available=[
                BriefingExit(
                    id="exit_north", direction="north", target_room="hall"
                ),
            ],
        ),
        player_state=PlayerStateBriefing(location="arena"),
        player_input="I act.",
        combat_state=CombatBriefing(
            round_number=1,
            initiative_order=["player", "goblin"],
            current_actor="player",
            combatants=[
                {"id": "player", "name": "Player", "side": "party",
                 "current_hp": 10, "max_hp": 10, "status_effects": [],
                 "engaged_with": ["goblin"], "impeded": False,
                 "impede_used": False},
                {"id": "korbar", "name": "Korbar", "side": "party",
                 "current_hp": 20, "max_hp": 20, "status_effects": [],
                 "engaged_with": [], "impeded": False, "impede_used": False},
                {"id": "goblin", "name": "Goblin", "side": "enemy",
                 "current_hp": 7, "max_hp": 7, "status_effects": [],
                 "engaged_with": ["player"], "impeded": False,
                 "impede_used": False},
                {"id": "orc", "name": "Orc", "side": "enemy",
                 "current_hp": 12, "max_hp": 12, "status_effects": [],
                 "engaged_with": [], "impeded": False, "impede_used": False},
            ],
            usable_items=[
                {"id": "health_potion", "name": "Healing Potion",
                 "effects": "Heals 2d4+2 HP"},
            ],
            abilities=(
                [
                    {"id": "second_wind", "name": "Second Wind",
                     "description": "Catch your breath.", "target": "self",
                     "uses_remaining": 1, "effect": "Heal 1d10 HP"},
                    {"id": "smite", "name": "Smite",
                     "description": "A holy strike.", "target": "enemy",
                     "uses_remaining": 2, "effect": "2d6 radiant damage"},
                    {"id": "rally", "name": "Rally",
                     "description": "Bolster an ally.", "target": "ally",
                     "uses_remaining": 1, "effect": "Ally gains 1d4 HP"},
                ]
                if abilities is None else abilities
            ),
        ),
    )


def _peaceful_briefing() -> GMBriefing:
    briefing = _combat_briefing()
    return briefing.model_copy(update={"combat_state": None})


def _combat(combat_action: str, target: str):
    return CombatAction(
        action_type="combat",
        combat_action=combat_action,
        target=target,
        detail="test",
    )


def _use_ability(ability_id: str, target: str = "player"):
    return UseAbilityAction(
        action_type="use_ability",
        ability_id=ability_id,
        target=target,
        detail="test",
    )


def _move(target: str):
    return MoveAction(action_type="move", target=target, detail="test")


def _talk(target: str = "goblin"):
    return TalkAction(
        action_type="talk", target=target, utterance="Parley!", detail="test"
    )


def _gear(equip_targets=None, unequip_targets=None):
    return GearAction(
        action_type="gear",
        equip_targets=equip_targets or [],
        unequip_targets=unequip_targets or [],
        detail="test",
    )


def _interact(target: str = "goblin", interaction_id: str = "pull_lever"):
    return InteractAction(
        action_type="interact",
        target=target,
        interaction_id=interaction_id,
        detail="test",
    )


def _briefing_with_equipped(equipped_items: list) -> GMBriefing:
    briefing = _combat_briefing()
    briefing.player_state.equipped_items = equipped_items
    return briefing


class TestAttack:
    def test_valid_enemy_target_passes(self):
        assert validate_ruling_action(
            _combat("attack", "goblin"), _combat_briefing()
        ) is None

    def test_party_target_flagged(self):
        error = validate_ruling_action(
            _combat("attack", "korbar"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid attack target 'korbar'" in error
        assert "goblin" in error

    def test_unknown_target_flagged(self):
        error = validate_ruling_action(
            _combat("attack", "bugbear"), _combat_briefing()
        )
        assert error is not None
        assert "bugbear" in error


class TestUseAbility:
    def test_valid_self_ability_passes(self):
        assert validate_ruling_action(
            _use_ability("second_wind", "player"),
            _combat_briefing(),
        ) is None

    def test_valid_enemy_ability_passes(self):
        assert validate_ruling_action(
            _use_ability("smite", "goblin"), _combat_briefing()
        ) is None

    def test_valid_ally_ability_passes(self):
        assert validate_ruling_action(
            _use_ability("rally", "korbar"), _combat_briefing()
        ) is None

    def test_unknown_ability_flagged(self):
        error = validate_ruling_action(
            _use_ability("fireball", "goblin"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid ability_id 'fireball'" in error
        assert "second_wind" in error and "smite" in error

    def test_empty_abilities_flagged(self):
        error = validate_ruling_action(
            _use_ability("second_wind", "player"),
            _combat_briefing(abilities=[]),
        )
        assert error is not None
        assert "no abilities" in error

    def test_self_ability_with_enemy_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("second_wind", "goblin"),
            _combat_briefing(),
        )
        assert error is not None
        assert "second_wind" in error
        assert '"self"' in error and '"player"' in error

    def test_enemy_ability_with_player_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("smite", "player"), _combat_briefing()
        )
        assert error is not None
        assert "smite" in error and "goblin" in error

    def test_ally_ability_with_enemy_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("rally", "goblin"), _combat_briefing()
        )
        assert error is not None
        assert "rally" in error and "korbar" in error

    def _spell_briefing(self, spell_slots: dict) -> GMBriefing:
        briefing = _combat_briefing(abilities=[
            {"id": "magic_missile", "name": "Magic Missile",
             "description": "Three unerring darts.", "target": "enemy",
             "uses_remaining": None,
             "effect": "level 1 spell, evocation: 3d4+3 force damage (no attack roll or save)",
             "spell_level": 1, "concentration": False, "slot_level": 1},
            {"id": "fire_bolt", "name": "Fire Bolt",
             "description": "A mote of fire.", "target": "enemy",
             "uses_remaining": None,
             "effect": "cantrip, evocation: attack (INT) for 1d10 fire damage",
             "spell_level": 0, "concentration": False, "slot_level": 0},
        ])
        briefing.combat_state.spell_slots = spell_slots
        return briefing

    def test_leveled_spell_without_slot_flagged(self):
        error = validate_ruling_action(
            _use_ability("magic_missile", "goblin"),
            self._spell_briefing({1: 0}),
        )
        assert error is not None
        assert "no level-1 spell slots" in error

    def test_leveled_spell_with_slot_passes(self):
        assert validate_ruling_action(
            _use_ability("magic_missile", "goblin"),
            self._spell_briefing({1: 1}),
        ) is None

    def test_cantrip_needs_no_slot(self):
        assert validate_ruling_action(
            _use_ability("fire_bolt", "goblin"),
            self._spell_briefing({}),
        ) is None


class TestUseAbilityOutOfCombat:
    """Out-of-combat use_ability: self/ally heal/on_cast abilities only."""

    def _ooc_briefing(self, spell_slots: dict | None = None) -> GMBriefing:
        briefing = _peaceful_briefing()
        briefing.current_room.entities_visible = [
            BriefingEntity(
                id="medic", name="Medic", type="npc",
                description="A field medic.", state={"alive": True},
            ),
        ]
        briefing.player_state.abilities = [
            {"id": "cure_wounds", "name": "Cure Wounds",
             "description": "Healing touch.", "target": "ally",
             "uses_remaining": None,
             "effect": "level 1 spell, abjuration: heals 2d8",
             "effect_kind": "heal",
             "spell_level": 1, "concentration": False, "slot_level": 1},
            {"id": "mage_armor", "name": "Mage Armor",
             "description": "Protective magical force.", "target": "self",
             "uses_remaining": None,
             "effect": "level 1 spell, abjuration: applies status 'mage_armor'",
             "effect_kind": "on_cast",
             "spell_level": 1, "concentration": False, "slot_level": 1},
            {"id": "fire_bolt", "name": "Fire Bolt",
             "description": "A mote of fire.", "target": "enemy",
             "uses_remaining": None,
             "effect": "cantrip, evocation: attack (INT) for 1d10 fire damage",
             "effect_kind": "attack",
             "spell_level": 0, "concentration": False, "slot_level": 0},
            {"id": "magic_missile", "name": "Magic Missile",
             "description": "Three bolts of force.", "target": "enemy",
             "uses_remaining": None,
             "effect": "level 1 spell, evocation: 3d4 force damage",
             "effect_kind": "auto_damage",
             "spell_level": 1, "concentration": False, "slot_level": 1},
            {"id": "warding_flare", "name": "Warding Flare",
             "description": "A burst of light.", "target": "ally",
             "uses_remaining": None,
             "effect": "cantrip: DEX save DC 13: 1d6 damage",
             "effect_kind": "save",
             "spell_level": 0, "concentration": False, "slot_level": 0},
        ]
        if spell_slots is not None:
            briefing.player_state.spell_slots = spell_slots
        return briefing

    def test_valid_self_buff_passes(self):
        assert validate_ruling_action(
            _use_ability("mage_armor", "player"),
            self._ooc_briefing({1: 1}),
        ) is None

    def test_valid_ally_heal_passes(self):
        assert validate_ruling_action(
            _use_ability("cure_wounds", "medic"),
            self._ooc_briefing({1: 1}),
        ) is None
        assert validate_ruling_action(
            _use_ability("cure_wounds", "player"),
            self._ooc_briefing({1: 1}),
        ) is None

    def test_unknown_ability_flagged(self):
        error = validate_ruling_action(
            _use_ability("fireball", "player"),
            self._ooc_briefing(),
        )
        assert error is not None
        assert "player_state.abilities" in error

    def test_enemy_targeted_ability_passes(self):
        # Enemy-targeted abilities out of combat start combat (mirroring
        # interact/attack); the validator allows them through.
        assert validate_ruling_action(
            _use_ability("fire_bolt", "goblin"),
            self._ooc_briefing(),
        ) is None

    def test_enemy_targeted_no_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("fire_bolt", ""),
            self._ooc_briefing(),
        )
        assert error is not None
        assert "enemy" in error

    def test_enemy_leveled_spell_without_slot_flagged(self):
        # Enemy-targeted leveled spells still need a slot (it will be
        # consumed on the first combat turn).
        error = validate_ruling_action(
            _use_ability("magic_missile", "goblin"),
            self._ooc_briefing({1: 0}),
        )
        assert error is not None
        assert "no level-1 spell slots" in error

    def test_save_effect_flagged(self):
        error = validate_ruling_action(
            _use_ability("warding_flare", "medic"),
            self._ooc_briefing(),
        )
        assert error is not None
        assert "save" in error and "combat" in error

    def test_self_ability_with_npc_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("mage_armor", "medic"),
            self._ooc_briefing({1: 1}),
        )
        assert error is not None
        assert "player" in error

    def test_ally_ability_with_unknown_target_flagged(self):
        error = validate_ruling_action(
            _use_ability("cure_wounds", "goblin"),
            self._ooc_briefing({1: 1}),
        )
        assert error is not None
        assert "medic" in error

    def test_leveled_spell_without_slot_flagged(self):
        error = validate_ruling_action(
            _use_ability("mage_armor", "player"),
            self._ooc_briefing({1: 0}),
        )
        assert error is not None
        assert "no level-1 spell slots" in error


class TestMove:
    def test_exit_target_passes(self):
        assert validate_ruling_action(
            _move("exit_north"), _combat_briefing()
        ) is None

    def test_non_exit_target_flagged(self):
        error = validate_ruling_action(
            _move("goblin"), _combat_briefing()
        )
        assert error is not None
        assert "Invalid move target 'goblin'" in error
        assert "FLEEING" in error
        assert "exit_north" in error
        assert "positioning" in error and "maneuver" in error


class TestTalk:
    def test_talk_during_combat_flagged(self):
        error = validate_ruling_action(_talk(), _combat_briefing())
        assert error is not None
        assert "talk" in error
        assert "'wait'" in error and "detail" in error
        assert "Never convert a talk attempt into an attack" in error

    def test_talk_outside_combat_passes(self):
        assert validate_ruling_action(_talk(), _peaceful_briefing()) is None


class TestValidateDialoguePath:
    """Hallucinated dialogue_path IDs are rejected (corrective retry
    fodder); unknown IDs must never reach the resolver, which would
    hard-fail the whole turn."""

    def _corpus(self):
        from mgmai.models.corpus import (
            Adventure,
            DialogueGuidelines,
            Entity,
            ModuleCorpus,
            Resolvable,
            Result,
        )
        return ModuleCorpus(
            adventure=Adventure(title="T", introduction="i"),
            rooms={},
            entities={
                "marta": Entity(
                    type="npc", name="Marta", description="Barkeep.",
                    dialogue=DialogueGuidelines(
                        guidelines="Warm, guarded.",
                        dialogue_paths={
                            "sympathetic_ear": Resolvable(
                                description="Listen warmly.",
                                result=Result(narrative="She thaws."),
                            ),
                        },
                    ),
                ),
                "fen": Entity(
                    type="npc", name="Fen", description="Old fisherman.",
                    dialogue=DialogueGuidelines(guidelines="Rambles."),
                ),
            },
        )

    def test_known_path_accepted(self):
        action = TalkAction(
            action_type="talk", target="marta", detail="test",
            dialogue_path="sympathetic_ear",
        )
        assert validate_ruling_action(
            action, _peaceful_briefing(), self._corpus()
        ) is None

    def test_unknown_path_rejected(self):
        action = TalkAction(
            action_type="talk", target="marta", detail="test",
            dialogue_path="tell_secrets",
        )
        error = validate_ruling_action(
            action, _peaceful_briefing(), self._corpus()
        )
        assert error is not None
        assert "tell_secrets" in error
        assert "sympathetic_ear" in error  # available paths listed

    def test_unknown_path_on_pathless_npc_rejected(self):
        action = TalkAction(
            action_type="talk", target="fen", detail="test",
            dialogue_path="night_crossings",
        )
        error = validate_ruling_action(
            action, _peaceful_briefing(), self._corpus()
        )
        assert error is not None
        assert "no dialogue paths" in error

    def test_no_path_passes(self):
        assert validate_ruling_action(
            _talk("marta"), _peaceful_briefing(), self._corpus()
        ) is None

    def test_no_corpus_no_judgment(self):
        action = TalkAction(
            action_type="talk", target="marta", detail="test",
            dialogue_path="anything",
        )
        assert validate_ruling_action(action, _peaceful_briefing()) is None


class TestGear:
    _SWORD = EquippedItemBriefing(
        id="sword", name="Sword", description="A blade.",
        equip_tags=["weapon"], effects_summary="1d8 damage",
    )
    _ARMOR = EquippedItemBriefing(
        id="plate_armor", name="Plate Armor", description="Heavy plate.",
        equip_tags=["armor"], effects_summary="AC 18",
    )

    def test_weapon_swap_passes(self):
        briefing = _briefing_with_equipped([self._SWORD])
        assert validate_ruling_action(
            _gear(equip_targets=["axe"], unequip_targets=["sword"]),
            briefing,
        ) is None

    def test_unequip_armor_flagged(self):
        briefing = _briefing_with_equipped([self._SWORD, self._ARMOR])
        error = validate_ruling_action(
            _gear(unequip_targets=["plate_armor"]), briefing
        )
        assert error is not None
        assert "plate_armor" in error
        assert "weapon" in error

    def test_equip_only_passes(self):
        """Equip-target tags are not in the briefing: stay conservative."""
        briefing = _briefing_with_equipped([self._SWORD])
        assert validate_ruling_action(
            _gear(equip_targets=["axe"]), briefing
        ) is None

    def test_unknown_unequip_target_passes(self):
        """Not provably non-weapon from the briefing: stay conservative."""
        briefing = _briefing_with_equipped([self._SWORD])
        assert validate_ruling_action(
            _gear(unequip_targets=["helmet"]), briefing
        ) is None

    def test_gear_outside_combat_passes(self):
        briefing = _peaceful_briefing()
        briefing.player_state.equipped_items = [self._ARMOR]
        assert validate_ruling_action(
            _gear(unequip_targets=["plate_armor"]), briefing
        ) is None


class TestEnvironmentalActionsLegal:
    """interact/transfer/examine are legal in combat: never rejected."""

    def test_interact_during_combat_passes(self):
        assert validate_ruling_action(
            _interact(), _combat_briefing()
        ) is None

    def test_transfer_during_combat_passes(self):
        from mgmai.models.actions import TransferAction

        action = TransferAction(
            action_type="transfer", target="goblin",
            taken_items=["dagger"], detail="test",
        )
        assert validate_ruling_action(action, _combat_briefing()) is None

    def test_rigorous_examine_during_combat_passes(self):
        from mgmai.models.actions import ExamineAction

        action = ExamineAction(
            action_type="examine", target="goblin", rigorous=True,
            detail="test",
        )
        assert validate_ruling_action(action, _combat_briefing()) is None


class TestConservative:
    """Cases where the validator must stay silent (return None)."""

    def test_no_combat_state_anything_passes(self):
        briefing = _peaceful_briefing()
        assert validate_ruling_action(
            _combat("attack", "goblin"), briefing
        ) is None
        assert validate_ruling_action(_move("goblin"), briefing) is None

    def test_wait_in_combat_passes(self):
        assert validate_ruling_action(
            WaitAction(action_type="wait", detail="persuade the goblin"),
            _combat_briefing(),
        ) is None


def _attack_with_positioning(positioning: dict) -> CombatAction:
    return CombatAction(
        action_type="combat",
        combat_action="attack",
        target="goblin",
        detail="test",
        positioning=PositioningAssertion.model_validate(positioning),
    )


def _wait_with_positioning(positioning: dict) -> WaitAction:
    return WaitAction(
        action_type="wait",
        detail="test",
        positioning=PositioningAssertion.model_validate(positioning),
    )


class TestPositioning:
    """Soft-fail validation of the optional positioning assertion."""

    def test_no_positioning_passes(self):
        assert validate_positioning_assertion(
            _combat("attack", "goblin"), _combat_briefing()
        ) is None

    def test_valid_engage_passes(self):
        action = _attack_with_positioning(
            {"engage": [["korbar", "orc"]], "disengage": [], "impede": []}
        )
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_valid_disengage_passes(self):
        # player and goblin are engaged in the briefing fixture.
        action = _attack_with_positioning(
            {"engage": [], "disengage": [["player", "goblin"]], "impede": []}
        )
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_valid_impede_passes(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_valid_on_wait_action_passes(self):
        action = _wait_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_valid_on_interact_action_passes(self):
        action = _interact()
        action.positioning = PositioningAssertion.model_validate(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_unknown_engage_id_flagged(self):
        action = _attack_with_positioning(
            {"engage": [["player", "ghost"]], "disengage": [], "impede": []}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "ghost" in error and "not a living combatant" in error

    def test_unknown_disengage_id_flagged(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [["ghost", "goblin"]], "impede": []}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "ghost" in error

    def test_same_id_pair_flagged(self):
        action = _attack_with_positioning(
            {"engage": [["player", "player"]], "disengage": [], "impede": []}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "distinct" in error

    def test_both_lists_conflict_flagged(self):
        action = _attack_with_positioning({
            "engage": [["korbar", "goblin"]],
            "disengage": [["goblin", "korbar"]],
            "impede": [],
        })
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "both 'engage' and 'disengage'" in error

    def test_disengage_not_currently_engaged_flagged(self):
        # korbar and goblin are not engaged in the briefing fixture.
        action = _attack_with_positioning(
            {"engage": [], "disengage": [["korbar", "goblin"]], "impede": []}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "not currently engaged" in error

    def test_engagement_check_skipped_without_map(self):
        """Conservative: briefings lacking engaged_with are not judged."""
        briefing = _combat_briefing()
        for c in briefing.combat_state.combatants:
            del c["engaged_with"]
        action = _attack_with_positioning(
            {"engage": [], "disengage": [["korbar", "goblin"]], "impede": []}
        )
        assert validate_positioning_assertion(action, briefing) is None

    def test_cap_counts_impede_entries(self):
        action = _attack_with_positioning({
            "engage": [["korbar", "goblin"], ["korbar", "orc"]],
            "disengage": [["player", "goblin"]],
            "impede": ["goblin", "orc"],
        })
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "at most 4" in error

    def test_cap_allows_four_entries(self):
        action = _attack_with_positioning({
            "engage": [["korbar", "goblin"], ["korbar", "orc"]],
            "disengage": [["player", "goblin"]],
            "impede": ["orc"],
        })
        assert validate_positioning_assertion(
            action, _combat_briefing()
        ) is None

    def test_impede_player_flagged(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["player"]}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "impede" in error and "player" in error

    def test_impede_ally_flagged(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["korbar"]}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "korbar" in error

    def test_impede_pending_flagged(self):
        briefing = _combat_briefing()
        for c in briefing.combat_state.combatants:
            if c["id"] == "orc":
                c["impeded"] = True
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        error = validate_positioning_assertion(action, briefing)
        assert error is not None
        assert "already impeded" in error

    def test_impede_already_used_flagged(self):
        briefing = _combat_briefing()
        for c in briefing.combat_state.combatants:
            if c["id"] == "orc":
                c["impede_used"] = True
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        error = validate_positioning_assertion(action, briefing)
        assert error is not None
        assert "already impeded" in error

    def test_impede_duplicate_flagged(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc", "orc"]}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "already impeded" in error

    def test_wrong_phase_flagged(self):
        action = _attack_with_positioning(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        error = validate_positioning_assertion(action, _peaceful_briefing())
        assert error is not None
        assert "only valid during combat" in error

    def test_wrong_action_type_flagged(self):
        action = _move("exit_north")
        action.positioning = PositioningAssertion.model_validate(
            {"engage": [], "disengage": [], "impede": ["orc"]}
        )
        error = validate_positioning_assertion(action, _combat_briefing())
        assert error is not None
        assert "only valid on 'combat', 'wait', and 'interact'" in error


class TestPositioningSoftFail:
    """A failed positioning assertion never costs the player their turn:
    the block is stripped (no corrective retry, no LLMOutputError) and a
    warning is surfaced on the engine result."""

    def _enter_combat(self, state_manager) -> None:
        from mgmai.models.combat import CombatState
        from mgmai.models.corpus import CombatBlock

        state_manager.corpus.entities["spider"].combat = CombatBlock(
            hp=15, ac=12, atk=4, dmg="1d4+2",
        )
        hard = state_manager.hard_state
        hard.entity_states.setdefault("spider", {})["current_hp"] = 15
        hard.player.current_hp = 30
        hard.player.max_hp = 30
        hard.combat = CombatState(
            active=True,
            combatants=["player", "spider"],
            initiative_order=["player", "spider"],
            current_index=0,
            round_number=1,
        )

    @staticmethod
    def _wait_ruling(positioning: dict | None) -> str:
        import json as _json

        ruling = {
            "action_type": "wait",
            "detail": "Player sizes up the spider",
            "follow_up": None,
            "soft_state_patches": [],
        }
        if positioning is not None:
            ruling["positioning"] = positioning
        return _json.dumps(ruling)

    @staticmethod
    def _prose() -> str:
        import json as _json

        return _json.dumps({
            "narration": "The spider circles.",
            "npc_response": None,
            "knowledge_tags": None,
            "attitude_changes": None,
        })

    @staticmethod
    def _display():
        from unittest.mock import MagicMock

        m = MagicMock()
        m.format_exits.return_value = ""
        return m

    def _make_loop(self, state_manager, ruling: str):
        from mgmai.game.loop import GameLoop

        class _LLM:
            def __init__(self):
                self.ruling_calls = []

            def call_ruling(inner, sp, up):
                inner.ruling_calls.append((sp, up))
                return ruling

            def call_prose(inner, sp, up):
                return self._prose()

        llm = _LLM()
        loop = GameLoop(state_manager, llm, display=self._display())
        return loop, llm

    def test_invalid_positioning_stripped(self, state_manager) -> None:
        self._enter_combat(state_manager)
        ruling = self._wait_ruling(
            {"engage": [["player", "ghost"]], "disengage": [], "impede": []}
        )
        loop, llm = self._make_loop(state_manager, ruling)

        narration = loop._execute_turn("wait", "wait", 0)

        # The core action proceeded — no fallback, no retry.
        assert "The spider circles." in narration
        assert len(llm.ruling_calls) == 1
        assert loop._last_action.positioning is None
        assert loop._last_result is not None
        assert loop._last_result.success
        assert any(
            "positioning assertion ignored" in w
            for w in loop._last_result.warnings
        )

    def test_valid_positioning_not_stripped(self, state_manager) -> None:
        self._enter_combat(state_manager)
        ruling = self._wait_ruling(
            {"engage": [], "disengage": [], "impede": ["spider"]}
        )
        loop, llm = self._make_loop(state_manager, ruling)

        narration = loop._execute_turn("wait", "wait", 0)

        assert "The spider circles." in narration
        assert len(llm.ruling_calls) == 1
        assert loop._last_action.positioning is not None
        assert not any(
            "positioning assertion ignored" in w
            for w in loop._last_result.warnings
        )
        # The engine applied the impede: the spider spent its turn
        # closing in instead of attacking.
        combat = state_manager.hard_state.combat
        assert "spider" in combat.impede_used
        assert "spider" not in combat.impeded


class TestSoftPatchValidation:
    """set_improvised_weapon patches: an invalid keyword or damage_type is
    provably wrong and must earn a corrective retry."""

    @staticmethod
    def _wait_with_patch(new_value) -> WaitAction:
        from mgmai.models.soft_state import SoftStatePatch

        return WaitAction(
            action_type="wait",
            detail="improvise a weapon",
            soft_state_patches=[SoftStatePatch(
                field="set_improvised_weapon",
                new_value=new_value,
                reason="wield an object",
            )],
        )

    def test_unknown_keyword_rejected(self, state_manager) -> None:
        action = self._wait_with_patch({"keyword": "colossal"})
        error = validate_ruling_action(
            action, _combat_briefing(), state_manager.corpus
        )
        assert error is not None
        assert "colossal" in error
        assert "light" in error  # lists the valid keywords

    def test_invalid_damage_type_rejected(self, state_manager) -> None:
        action = self._wait_with_patch(
            {"keyword": "light", "damage_type": "fire"}
        )
        error = validate_ruling_action(
            action, _combat_briefing(), state_manager.corpus
        )
        assert error is not None
        assert "fire" in error

    def test_valid_patch_accepted(self, state_manager) -> None:
        action = self._wait_with_patch(
            {"keyword": "standard", "damage_type": "slashing"}
        )
        assert (
            validate_ruling_action(action, _combat_briefing(), state_manager.corpus)
            is None
        )

    def test_null_value_accepted(self, state_manager) -> None:
        action = self._wait_with_patch(None)
        assert (
            validate_ruling_action(action, _combat_briefing(), state_manager.corpus)
            is None
        )

    def test_non_object_value_rejected(self, state_manager) -> None:
        action = self._wait_with_patch("a chair leg")
        error = validate_ruling_action(
            action, _combat_briefing(), state_manager.corpus
        )
        assert error is not None

    def test_no_corpus_skips_check(self) -> None:
        action = self._wait_with_patch({"keyword": "colossal"})
        assert validate_ruling_action(action, _combat_briefing()) is None

    def test_source_item_not_carried_rejected(self, state_manager) -> None:
        action = self._wait_with_patch(
            {"keyword": "light", "source_item": "rock"}
        )
        error = validate_ruling_action(
            action, _combat_briefing(), state_manager.corpus
        )
        assert error is not None
        assert "rock" in error

    def test_source_item_carried_accepted(self, state_manager) -> None:
        briefing = _combat_briefing()
        briefing.player_state.soft_inventory.append("rock")
        action = self._wait_with_patch(
            {"keyword": "light", "source_item": "rock"}
        )
        assert (
            validate_ruling_action(action, briefing, state_manager.corpus)
            is None
        )


class TestBudgetValidation:
    """Budget-aware ruling validation (§3.3, §4.1a, §4.2): second actions,
    second bonus actions, and second free interactions are rejected."""

    @staticmethod
    def _spent_briefing(
        *,
        action_available=True, bonus_action_available=True,
        free_interaction_available=True,
        usable_items=None,
        abilities=None,
    ) -> GMBriefing:
        briefing = _combat_briefing(abilities=abilities)
        briefing.combat_state.action_available = action_available
        briefing.combat_state.bonus_action_available = bonus_action_available
        briefing.combat_state.bonus_action_options = (
            ["healing_word"] if bonus_action_available else []
        )
        briefing.combat_state.free_interaction_available = free_interaction_available
        if usable_items is not None:
            briefing.combat_state.usable_items = usable_items
        return briefing

    def test_second_action_rejected(self):
        briefing = self._spent_briefing(action_available=False)
        error = validate_ruling_action(_combat("attack", "goblin"), briefing)
        assert error is not None
        assert "off-hand attack" in error

    def test_second_attack_allowed_when_off_hand_available(self):
        briefing = self._spent_briefing(action_available=False)
        briefing.combat_state.off_hand_attack_available = True
        assert (
            validate_ruling_action(_combat("attack", "goblin"), briefing)
            is None
        )

    def test_second_action_transfer_rejected(self):
        briefing = self._spent_briefing(action_available=False)
        error = validate_ruling_action(
            TransferAction(
                action_type="transfer", target="current_room",
                taken_items=["gem"], detail="test",
            ),
            briefing,
        )
        assert error is not None
        assert "no action left" in error

    def test_second_bonus_action_rejected(self):
        abilities = [
            {"id": "healing_word", "name": "Healing Word",
             "description": "A word.", "target": "ally",
             "uses_remaining": 1, "effect": "Heal 2d4",
             "spell_level": 1, "casting_time": "bonus_action"},
        ]
        briefing = self._spent_briefing(
            bonus_action_available=False, abilities=abilities,
        )
        error = validate_ruling_action(
            _use_ability("healing_word", "player"), briefing
        )
        assert error is not None
        assert "bonus action was already used" in error

    def test_bonus_action_not_in_legal_set_rejected(self):
        abilities = [
            {"id": "healing_word", "name": "Healing Word",
             "description": "A word.", "target": "ally",
             "uses_remaining": 0, "effect": "Heal 2d4",
             "spell_level": 1, "casting_time": "bonus_action"},
        ]
        # A DIFFERENT legal BA exists (fire_bolt cantrip), so the bonus
        # action is available — but healing_word itself is out of uses.
        briefing = self._spent_briefing(
            abilities=abilities,
        )
        briefing.combat_state.bonus_action_options = ["fire_bolt"]
        error = validate_ruling_action(
            _use_ability("healing_word", "player"), briefing
        )
        assert error is not None
        assert "not a legal bonus-action option" in error

    def test_gear_with_no_budget_rejected(self):
        briefing = self._spent_briefing(
            action_available=False, free_interaction_available=False,
        )
        error = validate_ruling_action(
            _gear(equip_targets=["sword"]), briefing
        )
        assert error is not None
        assert "no object interaction remains" in error

    def test_gear_with_free_interaction_available_passes(self):
        briefing = self._spent_briefing(
            action_available=False, free_interaction_available=True,
        )
        assert (
            validate_ruling_action(_gear(equip_targets=["sword"]), briefing)
            is None
        )

    def test_second_free_interaction_rejected(self):
        briefing = self._spent_briefing(free_interaction_available=False)
        error = validate_ruling_action(
            InteractAction(
                action_type="interact", target="goblin",
                interaction_id="pull_lever", detail="test",
                interaction_cost="free",
            ),
            briefing,
        )
        assert error is not None
        assert "already used" in error

    def test_potion_free_interaction_rejected(self):
        briefing = self._spent_briefing()
        error = validate_ruling_action(
            InteractAction(
                action_type="interact", target="health_potion",
                interaction_id="drink", detail="test",
                interaction_cost="free",
            ),
            briefing,
        )
        assert error is not None
        assert "always require an action" in error

    def test_carried_item_free_interaction_rejected(self):
        """Mirrors the engine-side rule: any carried item (not just
        usable_items) always requires an action to use."""
        briefing = self._spent_briefing()
        briefing.player_state.hard_inventory = {"torch": 1}
        error = validate_ruling_action(
            InteractAction(
                action_type="interact", target="torch",
                interaction_id="wave", detail="test",
                interaction_cost="free",
            ),
            briefing,
        )
        assert error is not None
        assert "always require an action" in error

    def test_attack_carried_equip_without_free_interaction_rejected(self):
        briefing = self._spent_briefing(free_interaction_available=False)
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", equip_target="sword", detail="test",
        )
        error = validate_ruling_action(action, briefing)
        assert error is not None
        assert "free object interaction was already used" in error

    def test_attack_carried_equip_passes_when_free_available(self):
        briefing = self._spent_briefing()
        action = CombatAction(
            action_type="combat", combat_action="attack",
            target="goblin", equip_target="sword", detail="test",
        )
        assert validate_ruling_action(action, briefing) is None


class TestManeuverValidation:
    """Target checks for the target-requiring maneuvers (Grapple / Shove /
    Help): the target must be a living enemy combatant."""

    def _maneuver(self, kind, target=None) -> CombatAction:
        return CombatAction(
            action_type="combat", combat_action="maneuver",
            maneuver=kind, target=target, detail="test",
        )

    def test_grapple_enemy_target_passes(self):
        briefing = _combat_briefing()
        assert validate_ruling_action(
            self._maneuver("grapple", "goblin"), briefing
        ) is None

    def test_grapple_ally_target_rejected(self):
        briefing = _combat_briefing()
        error = validate_ruling_action(
            self._maneuver("grapple", "korbar"), briefing
        )
        assert error is not None
        assert "living enemy combatant" in error

    def test_shove_unknown_target_rejected(self):
        briefing = _combat_briefing()
        error = validate_ruling_action(
            self._maneuver("shove", "dragon"), briefing
        )
        assert error is not None
        assert "living enemy combatant" in error

    def test_help_player_target_rejected(self):
        briefing = _combat_briefing()
        error = validate_ruling_action(
            self._maneuver("help", "player"), briefing
        )
        assert error is not None
        assert "living enemy combatant" in error

    def test_dodge_without_target_passes(self):
        briefing = _combat_briefing()
        assert validate_ruling_action(
            self._maneuver("dodge"), briefing
        ) is None

    def test_disengage_without_target_passes(self):
        briefing = _combat_briefing()
        assert validate_ruling_action(
            self._maneuver("disengage"), briefing
        ) is None
