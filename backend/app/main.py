from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .schemas import (
    AdminOverview,
    AdminUser,
    DeleteResponse,
    ImageAnalysisResult,
    ManualAnalysisRequest,
    MealEntry,
    MealListResponse,
    ProviderConnectRequest,
    ProviderSessionStatus,
    RegisterRequest,
    RegisterResponse,
    ResetCodeResponse,
    SessionRequest,
    SessionResponse,
    SummaryResponse,
    UserSummary,
)
from .services import (
    admin_overview,
    analyze_image,
    analyze_manual,
    count_entries,
    connect_perplexity_web_session,
    create_entry,
    create_user,
    delete_provider_session,
    delete_entry,
    delete_user,
    get_provider_session,
    get_user_by_code,
    list_admin_users,
    list_entries,
    reset_user_code,
    summary_for_user,
)
from .security import (
    DEFAULT_CSP,
    InMemoryRateLimiter,
    RatePolicy,
    apply_security_headers,
    extract_client_ip,
    load_rate_policies,
    policy_key_for_path,
)

app = FastAPI(title="Calorie Counter API", version="1.0.0")

# No access logs are persisted, and only minimum runtime logs are emitted.
logging.getLogger("uvicorn.access").disabled = True

app.state.rate_limiter = InMemoryRateLimiter(load_rate_policies())
app.state.csp = os.getenv("SECURITY_CONTENT_SECURITY_POLICY") or DEFAULT_CSP

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.getenv("FRONTEND_STATIC_DIR")
if STATIC_DIR and os.path.isdir(STATIC_DIR):
    next_dir = os.path.join(STATIC_DIR, "_next")
    if os.path.isdir(next_dir):
        app.mount("/_next", StaticFiles(directory=next_dir), name="next")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.middleware("http")
async def security_middleware(request: Request, call_next) -> Response:
    policy_name = policy_key_for_path(request.url.path)
    rate_policy: RatePolicy | None = None
    remaining = -1

    if policy_name:
        rate_limiter: InMemoryRateLimiter = app.state.rate_limiter
        rate_policy = rate_limiter.policies[policy_name]
        fallback_ip = request.client.host if request.client else "unknown"
        client_ip = extract_client_ip(request.headers, fallback_ip)
        key = f"{policy_name}:{client_ip}"
        allowed, retry_after, remaining = rate_limiter.check(key, rate_policy)

        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please retry shortly."},
            )
            response.headers["Retry-After"] = str(retry_after)
            _attach_rate_limit_headers(response, rate_policy, remaining=0)
            apply_security_headers(
                response,
                is_https=request.url.scheme == "https",
                csp=app.state.csp,
            )
            return response

    response = await call_next(request)
    apply_security_headers(
        response,
        is_https=request.url.scheme == "https",
        csp=app.state.csp,
    )
    if rate_policy:
        _attach_rate_limit_headers(response, rate_policy, remaining=remaining)
    return response


@app.post("/api/auth/register", response_model=RegisterResponse)
def register(payload: RegisterRequest) -> RegisterResponse:
    try:
        user = create_user(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RegisterResponse(
        user=_to_user_summary(user),
        code=user["code"],
        message="Save this code now. It is only shown once.",
    )


@app.post("/api/auth/session", response_model=SessionResponse)
def session(payload: SessionRequest) -> SessionResponse:
    admin_code = os.getenv("ADMIN_CODE")
    if admin_code and payload.code.strip() == admin_code:
        return SessionResponse(mode="admin", user=None)

    user = get_user_by_code(payload.code)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid code")
    return SessionResponse(mode="user", user=_to_user_summary(user))


@app.get("/api/profile", response_model=UserSummary)
def profile(access_code: str = Header(..., alias="X-Access-Code")) -> UserSummary:
    user = _require_user(access_code)
    return _to_user_summary(user)


@app.get("/api/meals", response_model=MealListResponse)
def meals(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    meal_type: str | None = Query(default=None),
    access_code: str = Header(..., alias="X-Access-Code"),
) -> MealListResponse:
    user = _require_user(access_code)
    entries_raw = list_entries(
        user["id"],
        limit=limit,
        offset=offset,
        query=q,
        source=source,
        meal_type=meal_type,
    )
    entries = [MealEntry(**entry) for entry in entries_raw]
    total = count_entries(user["id"], query=q, source=source, meal_type=meal_type)
    return MealListResponse(entries=entries, total=total, limit=limit, offset=offset)


@app.get("/api/summary", response_model=SummaryResponse)
def summary(
    days: int = Query(default=7, ge=1, le=90),
    access_code: str = Header(..., alias="X-Access-Code"),
) -> SummaryResponse:
    user = _require_user(access_code)
    return SummaryResponse(**summary_for_user(user["id"], days))


@app.delete("/api/meals/{entry_id}", response_model=DeleteResponse)
def remove_entry(
    entry_id: int,
    access_code: str = Header(..., alias="X-Access-Code"),
) -> DeleteResponse:
    user = _require_user(access_code)
    removed = delete_entry(user["id"], entry_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Entry not found")
    return DeleteResponse(status="ok")


@app.post("/api/analyze/photo", response_model=ImageAnalysisResult)
async def analyze_photo(
    image: UploadFile = File(...),
    provider: str = Form(default="perplexity"),
    save_entry: bool = Form(default=True),
    access_code: str = Header(..., alias="X-Access-Code"),
    perplexity_api_key: str | None = Header(default=None, alias="X-Perplexity-Api-Key"),
    openrouter_api_key: str | None = Header(default=None, alias="X-Openrouter-Api-Key"),
) -> ImageAnalysisResult:
    user = _require_user(access_code)
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image is empty")

    try:
        result = analyze_image(
            image_bytes=image_bytes,
            provider=provider,
            perplexity_api_key=perplexity_api_key,
            openrouter_api_key=openrouter_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {exc}") from exc

    if save_entry:
        create_entry(
            user_id=user["id"],
            source=result["source"],
            dish=result["dish"],
            calories_kcal=result["calories_kcal"],
            protein_g=result["protein_g"],
            fiber_g=result["fiber_g"],
            nutrients=result["nutrients"],
            chemicals=result["chemicals"],
            notes=result["notes"],
            meal_type=result.get("meal_type", "other"),
            confidence_score=result.get("confidence_score"),
        )

    return ImageAnalysisResult(**result)


@app.post("/api/analyze/manual", response_model=ImageAnalysisResult)
def analyze_from_text(
    payload: ManualAnalysisRequest,
    access_code: str = Header(..., alias="X-Access-Code"),
) -> ImageAnalysisResult:
    user = _require_user(access_code)
    result = analyze_manual(payload.text)

    if payload.save_entry:
        create_entry(
            user_id=user["id"],
            source=result["source"],
            dish=result["dish"],
            calories_kcal=result["calories_kcal"],
            protein_g=result["protein_g"],
            fiber_g=result["fiber_g"],
            nutrients=result["nutrients"],
            chemicals=result["chemicals"],
            notes=result["notes"],
            meal_type=result.get("meal_type", payload.meal_type),
            confidence_score=result.get("confidence_score"),
        )

    return ImageAnalysisResult(**result)


@app.get("/api/admin/overview", response_model=AdminOverview)
def admin_dashboard(admin_code: str = Header(..., alias="X-Admin-Code")) -> AdminOverview:
    _require_admin(admin_code)
    return AdminOverview(**admin_overview())


@app.get("/api/admin/users", response_model=list[AdminUser])
def admin_users(admin_code: str = Header(..., alias="X-Admin-Code")) -> list[AdminUser]:
    _require_admin(admin_code)
    return [AdminUser(**item) for item in list_admin_users()]


@app.post("/api/admin/users/{user_id}/reset-code", response_model=ResetCodeResponse)
def admin_reset_code(
    user_id: int,
    admin_code: str = Header(..., alias="X-Admin-Code"),
) -> ResetCodeResponse:
    _require_admin(admin_code)
    updated = reset_user_code(user_id)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return ResetCodeResponse(user=_to_user_summary(updated), new_code=updated["code"])


@app.delete("/api/admin/users/{user_id}", response_model=DeleteResponse)
def admin_delete_user(
    user_id: int,
    admin_code: str = Header(..., alias="X-Admin-Code"),
) -> DeleteResponse:
    _require_admin(admin_code)
    removed = delete_user(user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="User not found")
    return DeleteResponse(status="ok")


@app.get("/api/admin/providers/perplexity_web", response_model=ProviderSessionStatus)
def admin_perplexity_web_status(
    admin_code: str = Header(..., alias="X-Admin-Code"),
) -> ProviderSessionStatus:
    _require_admin(admin_code)
    session = get_provider_session("perplexity_web")
    if not session:
        return ProviderSessionStatus(provider="perplexity_web", connected=False, updated_at=None)
    return ProviderSessionStatus(
        provider="perplexity_web",
        connected=True,
        updated_at=datetime.fromisoformat(session["updated_at"]),
    )


@app.post("/api/admin/providers/perplexity_web", response_model=ProviderSessionStatus)
def admin_perplexity_web_connect(
    payload: ProviderConnectRequest,
    admin_code: str = Header(..., alias="X-Admin-Code"),
) -> ProviderSessionStatus:
    _require_admin(admin_code)
    try:
        result = connect_perplexity_web_session(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Provider connect failed: {exc}") from exc
    return ProviderSessionStatus(
        provider=result.get("provider", "perplexity_web"),
        connected=True,
        updated_at=datetime.fromisoformat(result["updated_at"]),
    )


@app.delete("/api/admin/providers/perplexity_web", response_model=DeleteResponse)
def admin_perplexity_web_disconnect(
    admin_code: str = Header(..., alias="X-Admin-Code"),
) -> DeleteResponse:
    _require_admin(admin_code)
    delete_provider_session("perplexity_web")
    return DeleteResponse(status="ok")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/")
def root() -> FileResponse:
    return _serve_index()


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    if path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not found")
    asset = _serve_asset(path)
    if asset:
        return asset
    return _serve_index()


def _serve_index() -> FileResponse:
    if STATIC_DIR and os.path.isdir(STATIC_DIR):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
    raise HTTPException(status_code=404, detail="Frontend not built")


def _serve_asset(path: str) -> FileResponse | None:
    if not STATIC_DIR:
        return None
    asset_path = os.path.join(STATIC_DIR, path)
    if os.path.isfile(asset_path):
        return FileResponse(asset_path)
    return None


def _require_user(code: str) -> dict:
    user = get_user_by_code(code)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid access code")
    return user


def _require_admin(admin_code: str) -> None:
    expected = os.getenv("ADMIN_CODE")
    if not expected or admin_code != expected:
        raise HTTPException(status_code=401, detail="Invalid admin code")


def _to_user_summary(user: dict) -> UserSummary:
    return UserSummary(
        id=user["id"],
        name=user["name"],
        code_hint=user["code_hint"],
        created_at=datetime.fromisoformat(user["created_at"]),
    )


def _attach_rate_limit_headers(
    response: Response, policy: RatePolicy, remaining: int
) -> None:
    response.headers["X-RateLimit-Limit"] = str(policy.max_requests)
    response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
    response.headers["X-RateLimit-Window"] = str(policy.window_seconds)
    response.headers["X-RateLimit-Scope"] = policy.name
