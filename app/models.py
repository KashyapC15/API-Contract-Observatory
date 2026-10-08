"""Typed models for deterministic API contract changes."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeType(str, Enum):
    ENDPOINT_ADDED = "endpoint_added"
    ENDPOINT_REMOVED = "endpoint_removed"
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    FIELD_TYPE_CHANGED = "field_type_changed"
    REQUIRED_FIELD_ADDED = "required_field_added"
    PARAMETER_REQUIRED = "parameter_required"


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: ChangeType
    path: str
    method: str | None = None
    scope: str | None = None
    field: str | None = None
    old_value: Any = None
    new_value: Any = None
    breaking: bool
    message: str


class DiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Change]


class RiskSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_index: int = Field(ge=0)
    breaking: bool
    severity: RiskSeverity
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    affected_consumers: list[str]
    recommended_action: str = Field(min_length=1)
    human_review_required: bool


class ModelAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_index: int = Field(ge=0)
    severity: RiskSeverity
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    affected_consumers: list[str]
    recommended_action: str = Field(min_length=1)
    human_review_required: bool


class AssessmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[ModelAssessment]


class RiskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    assessments: list[ChangeAssessment]
