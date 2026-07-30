from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from poolos.clock import FixedClock
from poolos.commands import Command, CommandAction
from poolos.enums import PolicyPriority
from poolos.exceptions import DuplicatePolicyError, UnknownPolicyError
from poolos.kernel import PoolKernel
from poolos.policies import PolicyOutcome
from poolos.policy_library import (
    ActivationDecision,
    AlwaysActive,
    EquipmentAttributeEquals,
    OperatingProfile,
    PolicyLibrary,
)
from poolos.state import EquipmentState
from poolos.equipment import Equipment
from poolos.enums import EquipmentType


@dataclass(frozen=True)
class StaticPolicy:
    policy_id: str
    priority: PolicyPriority
    target: str
    action: CommandAction

    def evaluate(self, context):
        return PolicyOutcome(
            self.policy_id,
            self.priority,
            (Command(self.target, self.action, requested_by=self.policy_id, issued_at=context.evaluated_at),),
        )


@dataclass(frozen=True)
class StaticRule:
    active: bool
    reason: str

    def evaluate(self, context):
        return ActivationDecision(self.active, self.reason)


def kernel():
    value = PoolKernel()
    value.clock = FixedClock(datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc))
    return value


def profile(profile_id="normal", priority=PolicyPriority.BACKGROUND, activation=AlwaysActive()):
    return OperatingProfile(
        profile_id,
        priority,
        (StaticPolicy(f"{profile_id}.policy", PolicyPriority.OPTIMIZATION, "pump", CommandAction.START),),
        activation,
    )


def test_library_selects_highest_priority_active_profile():
    library = PolicyLibrary()
    library.register(profile("normal", PolicyPriority.BACKGROUND))
    library.register(profile("safety", PolicyPriority.SAFETY))
    result = library.evaluate(kernel())
    assert result.selected_profile_id == "safety"
    assert result.policy_evaluation is not None
    assert result.policy_evaluation.commands[0].requested_by == "safety.policy"


def test_inactive_higher_priority_profile_is_skipped_with_trace():
    library = PolicyLibrary()
    library.register(profile("normal", PolicyPriority.BACKGROUND))
    library.register(profile("outage", PolicyPriority.EMERGENCY, StaticRule(False, "grid available")))
    result = library.evaluate(kernel())
    assert result.selected_profile_id == "normal"
    assert result.activations[1].decision.reason == "grid available"
    assert not result.activations[1].decision.active


def test_registration_order_breaks_equal_priority_ties():
    library = PolicyLibrary()
    library.register(profile("first", PolicyPriority.USER_REQUEST))
    library.register(profile("second", PolicyPriority.USER_REQUEST))
    assert library.evaluate(kernel()).selected_profile_id == "first"


def test_no_active_profile_returns_no_policy_evaluation():
    library = PolicyLibrary()
    library.register(profile(activation=StaticRule(False, "disabled")))
    result = library.evaluate(kernel())
    assert result.selected_profile_id is None
    assert result.policy_evaluation is None


def test_equipment_attribute_rule_uses_normalized_state():
    value = kernel()
    value.equipment.register(Equipment("grid", "Grid", EquipmentType.SENSOR))
    value.update_equipment_state("grid", EquipmentState(attributes={"available": False}))
    rule = EquipmentAttributeEquals("grid", "available", False)
    decision = rule.evaluate(type("Context", (), {"kernel": value})())
    assert decision.active
    assert "expected False" in decision.reason


def test_equipment_attribute_rule_handles_missing_state():
    decision = EquipmentAttributeEquals("grid", "available", False).evaluate(
        type("Context", (), {"kernel": kernel()})()
    )
    assert not decision.active
    assert "no state" in decision.reason


def test_profile_rejects_duplicate_policy_ids():
    policy = StaticPolicy("duplicate", PolicyPriority.OPTIMIZATION, "pump", CommandAction.START)
    with pytest.raises(ValueError, match="unique"):
        OperatingProfile("bad", PolicyPriority.BACKGROUND, (policy, policy))


def test_library_rejects_duplicate_and_unknown_profiles():
    library = PolicyLibrary()
    library.register(profile())
    with pytest.raises(DuplicatePolicyError):
        library.register(profile())
    with pytest.raises(UnknownPolicyError):
        library.get("missing")


def test_profile_metadata_is_immutable_copy():
    metadata = {"season": "summer"}
    item = OperatingProfile("normal", PolicyPriority.BACKGROUND, (StaticPolicy("p", PolicyPriority.BACKGROUND, "pump", CommandAction.START),), metadata=metadata)
    metadata["season"] = "winter"
    assert item.metadata["season"] == "summer"
    with pytest.raises(TypeError):
        item.metadata["season"] = "winter"


def test_activation_decision_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        ActivationDecision(True, " ")
