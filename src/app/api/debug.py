from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["debug"])
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/debug/chat", response_class=FileResponse)
async def debug_chat_page() -> FileResponse:
    # Serve the no-build chat UI used to verify Agent behavior in local and server envs.
    return FileResponse(STATIC_DIR / "debug_chat.html", media_type="text/html")
