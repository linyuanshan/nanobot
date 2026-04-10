"""Action planning based on current pool state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from hatchery.contracts.api import ActionPlanRequest, ActionPlanResponse, ActionProposal
from hatchery.db import HatcheryRepository


class PolicyService:
    def __init__(self, repository: HatcheryRepository):
        self.repository = repository

    def create_action_plan(self, request: ActionPlanRequest) -> ActionPlanResponse:
        state = self.repository.get_pool_state(request.pool_id)
        trace_id = request.trace_id or str(uuid4())
        if not state:
            actions: list[ActionProposal] = []
            explanation = "no pool state available; action plan intentionally empty"
            risk_level = "low"
        else:
            telemetry = state["telemetry"]
            bio = state["bio"]
            actions = []
            explanation = "state within expected range; no action required"
            risk_level = "low"

            if telemetry.get("temp_c", 0) > 31:
                explanation = "temperature crossed the danger threshold; propose water change"
                risk_level = "high"
                actions = [
                    ActionProposal(
                        action_type="water_change",
                        params={"ratio": 0.30, "duration_sec": 180},
                        risk_level="high",
                        rationale="temperature danger threshold exceeded",
                    )
                ]
            elif telemetry.get("do_mg_l", 99) <= 5:
                explanation = "dissolved oxygen dropped below target; propose aeration"
                risk_level = "medium"
                actions = [
                    ActionProposal(
                        action_type="aerate_up",
                        params={"duration_sec": 180 if telemetry.get('do_mg_l', 0) > 3 else 300},
                        risk_level="medium",
                        rationale="dissolved oxygen below threshold",
                    )
                ]
            elif bio.get("hunger_score", 0) >= 0.7:
                explanation = "bio perception indicates hunger; propose baseline feed"
                risk_level = "medium"
                actions = [
                    ActionProposal(
                        action_type="feed",
                        params={"ratio": 0.60, "duration_sec": 120},
                        risk_level="medium",
                        rationale="bio perception indicates hunger",
                    )
                ]

        response = ActionPlanResponse(
            plan_id=str(uuid4()),
            trace_id=trace_id,
            pool_id=request.pool_id,
            risk_level=risk_level,  # type: ignore[arg-type]
            decision_explanation=explanation,
            actions=actions,
            model_version=request.model_version,
            created_at=datetime.now(UTC),
        )
        self.repository.save_action_plan(response.model_dump(mode="json"))
        return response
