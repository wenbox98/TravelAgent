"""Explicit single-click research intent; counts are owned by the server."""

from typing import Literal
from pydantic import Field, field_validator
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import safe_text

CONSENT: Literal["PRIVATE_RESEARCH_AND_ADVICE_V2"] = "PRIVATE_RESEARCH_AND_ADVICE_V2"


class AutomaticStart(StrictModel):
    map_consent: Literal["PRIVATE_KEY_LEG_V1"] | None = None
    request: str = Field(min_length=1, max_length=500)
    destination: str = Field(default="", max_length=80)
    travel_kind: Literal["CITY", "REGIONAL"] = "CITY"
    consent: Literal["PRIVATE_RESEARCH_AND_ADVICE_V2", "PRIVATE_GOAL_AGENT_V3", "PRIVATE_GOAL_AGENT_V4"]

    @field_validator("request", "destination")
    @classmethod
    def safe(cls, v: str) -> str:
        return safe_text(v, 500).strip()


class AutomaticAction(StrictModel):
    map_consent: Literal["PRIVATE_KEY_LEG_V1"] | None = None
    action: Literal["continue", "cancel", "revise", "research_more", "refine"]
    expected_revision: int = Field(ge=0)
    text: str = Field(default="", max_length=500)
    consent: Literal["PRIVATE_RESEARCH_AND_ADVICE_V2", "PRIVATE_GOAL_AGENT_V3", "PRIVATE_GOAL_AGENT_V4"] | None = None

    @field_validator("text")
    @classmethod
    def safe(cls, v: str) -> str:
        return safe_text(v, 500).strip()
