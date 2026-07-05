from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SkillLevel = Literal["unknown", "awareness", "guided", "independent"]
ConfidenceLevel = Literal["low", "medium", "high"]


class MemoryUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillAssessmentUpdate(BaseModel):
    skill_id: str = Field(min_length=1, max_length=120)
    self_level: SkillLevel | None = None
    assessed_level: SkillLevel | None = None
    confidence: ConfidenceLevel = "low"
    evidence: str = Field(default="", max_length=1200)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    gaps: list[str] = Field(default_factory=list, max_length=6)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def require_evidence_for_assessed_level(self) -> "SkillAssessmentUpdate":
        if self.assessed_level is not None and not self.evidence.strip():
            self.assessed_level = None
        return self


class AssistantResult(BaseModel):
    reply: str = Field(min_length=1)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=5)
    skill_updates: list[SkillAssessmentUpdate] = Field(default_factory=list, max_length=12)
    rolling_summary: str = Field(max_length=1500)
    task_note: str | None = None
    task_completion_suggested: bool = False
    onboarding_completion_suggested: bool = False

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
