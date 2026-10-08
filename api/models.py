from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeType = Literal[
    "ENDPOINT_ADDED",
    "ENDPOINT_REMOVED",
    "FIELD_ADDED",
    "FIELD_REMOVED",
    "FIELD_TYPE_CHANGED",
    "REQUIRED_FIELD_ADDED",
    "RESPONSE_PROPERTY_REMOVED",
]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ChangeType
    location: str


class RiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk: RiskLevel
    breaking: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    affected_consumers: list[str]
    recommended_action: str
    human_review_required: bool


class AnalyzeResponse(BaseModel):
    changes: list[Change]
    risk_report: RiskReport
