from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(tags=["debug"])
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/debug/chat", response_class=FileResponse)
async def debug_chat_page() -> FileResponse:
    # Serve the no-build chat UI used to verify Agent behavior in local and server envs.
    return FileResponse(STATIC_DIR / "debug_chat.html", media_type="text/html")


@router.get("/", response_class=RedirectResponse)
async def index_page() -> RedirectResponse:
    return RedirectResponse("/chat")


@router.get("/login", response_class=FileResponse)
async def beta_login_page() -> FileResponse:
    # Serve the beta login page without a frontend build step.
    return FileResponse(STATIC_DIR / "beta_login.html", media_type="text/html")


@router.get("/chat", response_class=FileResponse)
async def beta_chat_page() -> FileResponse:
    # Serve the authenticated beta chat page.
    return FileResponse(STATIC_DIR / "beta_chat.html", media_type="text/html")


@router.get("/admin/beta-users", response_class=FileResponse)
async def beta_admin_page() -> FileResponse:
    # Serve the minimal beta user admin page protected by ADMIN_TOKEN APIs.
    return FileResponse(STATIC_DIR / "beta_admin.html", media_type="text/html")
