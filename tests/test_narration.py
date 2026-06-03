import pytest
from pydantic import ValidationError

from mgmai.models.narration import AttitudeChange, KnowledgeTags, NarrationOutput


class TestAttitudeChange:
    def test_basic(self) -> None:
        a = AttitudeChange.model_validate({
            "old_value": 0,
            "new_value": 2,
            "reason": "The player complimented Korbar's beard.",
        })
        assert a.old_value == 0
        assert a.new_value == 2
        assert "beard" in a.reason

    def test_missing_reason_raises(self) -> None:
        with pytest.raises(ValidationError):
            AttitudeChange.model_validate({
                "old_value": 0,
                "new_value": 2,
            })


class TestKnowledgeTags:
    def test_npc_revealed(self) -> None:
        k = KnowledgeTags.model_validate({
            "npc_revealed": {
                "korbar": ["padlock_mechanism", "secret_compartment"],
            },
        })
        assert k.npc_revealed is not None
        assert k.npc_revealed["korbar"] == ["padlock_mechanism", "secret_compartment"]

    def test_empty(self) -> None:
        k = KnowledgeTags.model_validate({})
        assert k.npc_revealed is None


class TestNarrationOutput:
    def test_basic(self) -> None:
        n = NarrationOutput.model_validate({
            "narration": "You push through the sticky webs and emerge onto the floor of the bag.",
        })
        assert "webs" in n.narration
        assert n.npc_response is None
        assert n.knowledge_tags is None
        assert n.attitude_changes is None

    def test_with_npc_response(self) -> None:
        n = NarrationOutput.model_validate({
            "narration": "Korbar looks up from his drink. 'Name's Korbar. Who's askin'?",
            "npc_response": "Name's Korbar. Who's askin'?",
        })
        assert n.npc_response == "Name's Korbar. Who's askin'?"

    def test_with_knowledge_tags(self) -> None:
        n = NarrationOutput.model_validate({
            "narration": "Korbar leans in close. 'See that padlock? It's got a mechanism...'",
            "knowledge_tags": {
                "npc_revealed": {
                    "korbar": ["padlock_mechanism"],
                },
            },
        })
        assert n.knowledge_tags is not None
        assert n.knowledge_tags.npc_revealed is not None
        assert n.knowledge_tags.npc_revealed["korbar"] == ["padlock_mechanism"]

    def test_with_attitude_changes(self) -> None:
        n = NarrationOutput.model_validate({
            "narration": "Korbar smiles warmly at your gesture.",
            "attitude_changes": {
                "korbar": {
                    "old_value": 1,
                    "new_value": 3,
                    "reason": "The player shared their rations with Korbar.",
                },
            },
        })
        assert n.attitude_changes is not None
        assert n.attitude_changes["korbar"].new_value == 3
        assert n.attitude_changes["korbar"].old_value == 1

    def test_full(self) -> None:
        n = NarrationOutput.model_validate({
            "narration": "'Aye, I know the way out,' Korbar whispers, 'but it'll cost ya.'",
            "npc_response": "Aye, I know the way out, but it'll cost ya.",
            "knowledge_tags": {
                "npc_revealed": {
                    "korbar": ["escape_route"],
                },
            },
            "attitude_changes": {
                "korbar": {
                    "old_value": 0,
                    "new_value": 1,
                    "reason": "The player expressed genuine interest in Korbar's knowledge.",
                },
            },
        })
        assert n.npc_response is not None
        assert n.knowledge_tags is not None
        assert n.attitude_changes is not None

    def test_missing_narration_raises(self) -> None:
        with pytest.raises(ValidationError):
            NarrationOutput.model_validate({
                "npc_response": "Hello.",
            })
