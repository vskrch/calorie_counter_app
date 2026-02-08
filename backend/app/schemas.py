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


class GoalsResponse(BaseModel):
    calories_kcal: float
    protein_g: float
    fiber_g: float
    updated_at: datetime | None = None


class GoalsUpdateRequest(BaseModel):
    calories_kcal: float = Field(..., ge=100, le=10000)
    protein_g: float = Field(..., ge=0, le=1000)
    fiber_g: float = Field(..., ge=0, le=300)


class ManualAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=2)
    save_entry: bool = True
    meal_type: str = Field(default="other", max_length=30)


class ImageAnalysisResult(BaseModel):
    dish: str
    meal_type: str = "other"
    calories_kcal: float | None = None
    protein_g: float | None = None
    fiber_g: float | None = None
    confidence_score: float | None = None
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
    meal_type: str
    calories_kcal: float | None = None
    protein_g: float | None = None
    fiber_g: float | None = None
    confidence_score: float | None = None
    nutrients: list[str] = Field(default_factory=list)
    chemicals: list[str] = Field(default_factory=list)
    notes: str | None = None
    eaten_at: datetime
    created_at: datetime
    updated_at: datetime


class CustomMealCreateRequest(BaseModel):
    dish: str = Field(..., min_length=1, max_length=120)
    meal_type: str = Field(default="other", max_length=30)
    calories_kcal: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    fiber_g: float | None = Field(default=None, ge=0, le=300)
    nutrients: list[str] = Field(default_factory=list)
    chemicals: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=400)
    eaten_at: datetime | None = None


class MealUpdateRequest(BaseModel):
    dish: str | None = Field(default=None, min_length=1, max_length=120)
    meal_type: str | None = Field(default=None, max_length=30)
    calories_kcal: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    fiber_g: float | None = Field(default=None, ge=0, le=300)
    nutrients: list[str] | None = None
    chemicals: list[str] | None = None
    notes: str | None = Field(default=None, max_length=400)
    eaten_at: datetime | None = None


class MealListResponse(BaseModel):
    entries: list[MealEntry]
    total: int
    limit: int
    offset: int


class DailyAnalyticsPoint(BaseModel):
    date: str
    entries: int
    calories_kcal: float
    protein_g: float
    fiber_g: float


class DailyAnalyticsResponse(BaseModel):
    days: int
    points: list[DailyAnalyticsPoint]


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


class TopDish(BaseModel):
    dish: str
    meal_type: str
    entries: int
    calories_kcal: float


class TopDishListResponse(BaseModel):
    days: int
    items: list[TopDish]


class ResetCodeResponse(BaseModel):
    user: UserSummary
    new_code: str


class DeleteResponse(BaseModel):
    status: str


class ProviderConnectRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class ProviderSessionStatus(BaseModel):
    provider: str
    connected: bool
    updated_at: datetime | None = None
