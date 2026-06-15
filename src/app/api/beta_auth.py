from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.dependencies import get_database_session
from app.models import BetaFeedback, BetaUser
from app.repositories import EmailSendLogRepository
from app.services.beta_auth import BETA_SESSION_COOKIE, BetaAuthError, BetaAuthService
from app.services.notifications import EmailNotificationService

router = APIRouter(tags=["beta-auth"])
SETTINGS_DEPENDENCY = Depends(get_settings)
DATABASE_SESSION_DEPENDENCY = Depends(get_database_session)
SESSION_COOKIE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class MeResponse(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: str | None
    role: str
    status: str


class AdminCreateBetaUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)
    role: str = Field(default="tester", max_length=32)
    remark: str | None = Field(default=None, max_length=500)


class AdminUpdateBetaUserRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled|invited)$")


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AdminBetaUserItem(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: str | None
    role: str
    status: str
    last_login_at: str | None
    last_seen_at: str | None
    created_at: str
    email: str | None = None
    email_status: str = "missing"
    email_enabled: bool = True
    email_daily_briefing_enabled: bool = True
    email_daily_briefing_time: str = "09:00"
    email_reminder_enabled: bool = True


class AdminBetaUsersResponse(BaseModel):
    items: list[AdminBetaUserItem]


class AdminBetaFeedbackItem(BaseModel):
    id: int
    user_id: int
    beta_user_id: int
    category: str
    content: str
    page_url: str | None
    status: str
    created_at: str


class AdminBetaFeedbackResponse(BaseModel):
    items: list[AdminBetaFeedbackItem]


class AdminEmailSettingsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    enabled: bool = True
    daily_briefing_time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    reminder_enabled: bool = True


class AdminEmailLogItem(BaseModel):
    id: int
    job_id: int | None
    user_id: int
    email: str
    email_type: str
    subject: str
    status: str
    error_message: str | None
    latency_ms: int | None
    created_at: str


class AdminEmailLogsResponse(BaseModel):
    items: list[AdminEmailLogItem]


def _require_database(session: AsyncSession | None) -> AsyncSession:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    return session


async def require_admin_token(
    settings: Settings = SETTINGS_DEPENDENCY,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    # MVP 管理后台沿用 ADMIN_TOKEN，后续可替换成独立管理员账号。
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


ADMIN_DEPENDENCY = Depends(require_admin_token)


@router.post("/api/auth/login", response_model=MeResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> MeResponse:
    db = _require_database(session)
    async with db.begin():
        service = BetaAuthService(db)
        try:
            result = await service.login(
                username=payload.username,
                password=payload.password,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        except BetaAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(response, result.token, secure=_cookie_secure(settings, request))
    return _me_response(result.user)


@router.post("/api/auth/logout")
async def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=BETA_SESSION_COOKIE)] = None,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    db = _require_database(session)
    async with db.begin():
        await BetaAuthService(db).logout(session_token)
    response.delete_cookie(BETA_SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/auth/me", response_model=MeResponse)
async def me(
    session_token: Annotated[str | None, Cookie(alias=BETA_SESSION_COOKIE)] = None,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> MeResponse:
    db = _require_database(session)
    async with db.begin():
        user = await BetaAuthService(db).authenticate_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return _me_response(user)


@router.get(
    "/api/admin/beta-users",
    response_model=AdminBetaUsersResponse,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_list_beta_users(
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUsersResponse:
    db = _require_database(session)
    users = await BetaAuthService(db).list_beta_users()
    email_service = EmailNotificationService(db, settings)
    return AdminBetaUsersResponse(
        items=[await _admin_user_item(user, email_service=email_service) for user in users]
    )


@router.post(
    "/api/admin/beta-users",
    response_model=AdminBetaUserItem,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_create_beta_user(
    payload: AdminCreateBetaUserRequest,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUserItem:
    db = _require_database(session)
    async with db.begin():
        try:
            user = await BetaAuthService(db).create_beta_user(
                username=payload.username,
                password=payload.password,
                display_name=payload.display_name,
                role=payload.role,
                remark=payload.remark,
            )
        except BetaAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _admin_user_item(user, email_service=EmailNotificationService(db, settings))


@router.patch(
    "/api/admin/beta-users/{user_id}",
    response_model=AdminBetaUserItem,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_update_beta_user(
    user_id: int,
    payload: AdminUpdateBetaUserRequest,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUserItem:
    db = _require_database(session)
    async with db.begin():
        try:
            user = await BetaAuthService(db).set_status(user_id, payload.status)
        except BetaAuthError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _admin_user_item(user, email_service=EmailNotificationService(db, settings))


@router.post(
    "/api/admin/beta-users/{user_id}/reset-password",
    response_model=AdminBetaUserItem,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_reset_beta_user_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUserItem:
    db = _require_database(session)
    async with db.begin():
        try:
            user = await BetaAuthService(db).reset_password(user_id, payload.password)
        except BetaAuthError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _admin_user_item(user, email_service=EmailNotificationService(db, settings))


@router.put(
    "/api/admin/beta-users/{user_id}/email",
    response_model=AdminBetaUserItem,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_update_beta_user_email(
    user_id: int,
    payload: AdminEmailSettingsRequest,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUserItem:
    db = _require_database(session)
    async with db.begin():
        result = await db.execute(
            select(BetaUser).where(BetaUser.id == user_id, BetaUser.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="user_not_found")
        await EmailNotificationService(db, settings).set_user_email(
            user_id=user.user_id,
            email=payload.email,
            enabled=payload.enabled,
            daily_briefing_time=payload.daily_briefing_time,
            reminder_enabled=payload.reminder_enabled,
        )
    return await _admin_user_item(user, email_service=EmailNotificationService(db, settings))


@router.post(
    "/api/admin/beta-users/{user_id}/email/test",
    response_model=AdminBetaUserItem,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_send_beta_user_test_email(
    user_id: int,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaUserItem:
    db = _require_database(session)
    async with db.begin():
        result = await db.execute(
            select(BetaUser).where(BetaUser.id == user_id, BetaUser.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="user_not_found")
        try:
            await EmailNotificationService(db, settings).create_test_email_job(user_id=user.user_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _admin_user_item(user, email_service=EmailNotificationService(db, settings))


@router.get(
    "/api/admin/beta-feedback",
    response_model=AdminBetaFeedbackResponse,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_list_beta_feedback(
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminBetaFeedbackResponse:
    db = _require_database(session)
    result = await db.execute(
        select(BetaFeedback).order_by(BetaFeedback.created_at.desc()).limit(100)
    )
    return AdminBetaFeedbackResponse(
        items=[_admin_feedback_item(item) for item in result.scalars().all()]
    )


@router.get(
    "/api/admin/email-logs",
    response_model=AdminEmailLogsResponse,
    dependencies=[ADMIN_DEPENDENCY],
)
async def admin_list_email_logs(
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> AdminEmailLogsResponse:
    db = _require_database(session)
    items = await EmailSendLogRepository(db).list_recent(limit=100)
    return AdminEmailLogsResponse(items=[_admin_email_log_item(item) for item in items])


def _set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        BETA_SESSION_COOKIE,
        token,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _cookie_secure(settings: Settings, request: Request) -> bool:
    # Use Secure cookies only when the current browser request is actually HTTPS.
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if forwarded_proto:
        return forwarded_proto == "https"
    if request.url.scheme == "https":
        return True
    public_host = ""
    if settings.public_base_url:
        public_host = str(settings.public_base_url).removeprefix("https://").split("/", 1)[0]
    return bool(
        settings.public_base_url
        and str(settings.public_base_url).startswith("https://")
        and request.url.hostname == public_host
        and request.url.port in {443, None}
    )


def _me_response(user: BetaUser) -> MeResponse:
    return MeResponse(
        id=user.id,
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
    )


async def _admin_user_item(
    user: BetaUser,
    *,
    email_service: EmailNotificationService,
) -> AdminBetaUserItem:
    email_settings = await email_service.get_user_email_settings(user_id=user.user_id)
    return AdminBetaUserItem(
        id=user.id,
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        last_login_at=_iso(user.last_login_at),
        last_seen_at=_iso(user.last_seen_at),
        created_at=_iso(user.created_at) or datetime.now(UTC).isoformat(),
        **email_settings,
    )


def _admin_feedback_item(item: BetaFeedback) -> AdminBetaFeedbackItem:
    return AdminBetaFeedbackItem(
        id=item.id,
        user_id=item.user_id,
        beta_user_id=item.beta_user_id,
        category=item.category,
        content=item.content,
        page_url=item.page_url,
        status=item.status,
        created_at=_iso(item.created_at) or datetime.now(UTC).isoformat(),
    )


def _admin_email_log_item(item) -> AdminEmailLogItem:
    return AdminEmailLogItem(
        id=item.id,
        job_id=item.job_id,
        user_id=item.user_id,
        email=item.email,
        email_type=item.email_type,
        subject=item.subject,
        status=item.status,
        error_message=item.error_message,
        latency_ms=item.latency_ms,
        created_at=_iso(item.created_at) or datetime.now(UTC).isoformat(),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
