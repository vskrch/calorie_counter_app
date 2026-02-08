from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class UserSummary(BaseModel):
    id: int
    name: str
    code_hint: str
    created_at: datetime


class RegisterResponse(BaseModel):
    user: UserSummary
    code: str
    message: str


class SessionRequest(BaseModel):
    code: str = Field(..., min_length=4)


class SessionResponse(BaseModel):
    mode: str
    user: UserSummary | None = None


class ManualAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=2)
    save_entry: bool = True


class ImageAnalysisResult(BaseModel):
    dish: str
    calories_kcal: float | None = None
    protein_g: float | None = None
    fiber_g: float | None = None
    nutrients: list[str] = Field(default_factory=list)
    chemicals: list[str] = Field(default_factory=list)
    notes: str | None = None
    source: str
    model: str | None = None
    raw: str | None = None


class MealEntry(BaseModel):
    id: int
    user_id: int
    source: str
    dish: str
    calories_kcal: float | None = None
    protein_g: float | None = None
    fiber_g: float | None = None
    nutrients: list[str] = Field(default_factory=list)
    chemicals: list[str] = Field(default_factory=list)
    notes: str | None = None
    eaten_at: datetime
    created_at: datetime


class MealListResponse(BaseModel):
    entries: list[MealEntry]


class SummaryResponse(BaseModel):
    days: int
    entries: int
    calories_kcal: float
    protein_g: float
    fiber_g: float


class AdminOverview(BaseModel):
    users: int
    entries: int
    calories_kcal: float


class AdminUser(BaseModel):
    id: int
    name: str
    code_hint: str
    created_at: datetime
    entries: int
    calories_kcal: float


class ResetCodeResponse(BaseModel):
    user: UserSummary
    new_code: str


class DeleteResponse(BaseModel):
    status: str
