import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserProfile
from app.repositories import UserProfileRepository


@dataclass(frozen=True)
class MemoryCandidate:
    profile_key: str
    profile_value: str
    merge_strategy: str


@dataclass(frozen=True)
class MemorySaveResult:
    status: str
    message: str
    profile: UserProfile | None = None
    needs_clarification: bool = False


@dataclass(frozen=True)
class MemoryDeleteResult:
    status: str
    message: str
    profile: UserProfile | None = None


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = UserProfileRepository(session)

    async def save_from_text(self, *, user_id: int, text: str) -> MemorySaveResult:
        candidate = extract_memory_candidate(text)
        if candidate is None:
            return MemorySaveResult(
                status="needs_clarification",
                message="我还没识别出要记住的具体偏好。",
                needs_clarification=True,
            )

        current = await self.repository.get_active_by_key(
            user_id=user_id,
            profile_key=candidate.profile_key,
        )
        value = _merge_profile_value(
            existing=current.profile_value if current else None,
            incoming=candidate.profile_value,
            strategy=candidate.merge_strategy,
        )
        profile = await self.repository.upsert(
            user_id=user_id,
            profile_key=candidate.profile_key,
            profile_value=value,
            value_type="list" if candidate.merge_strategy == "merge_list" else "string",
            extra_metadata={
                "source_text": text,
                "merge_strategy": candidate.merge_strategy,
            },
        )
        return MemorySaveResult(status="saved", message="我记住了。", profile=profile)

    async def list_active(self, *, user_id: int, limit: int = 30) -> list[UserProfile]:
        return await self.repository.list_active(user_id=user_id, limit=limit)

    async def delete_by_id(self, *, user_id: int, profile_id: int) -> MemoryDeleteResult:
        profile = await self.repository.soft_delete(profile_id=profile_id, user_id=user_id)
        if profile is None:
            return MemoryDeleteResult(status="not_found", message="没有找到这条记忆。")
        return MemoryDeleteResult(status="deleted", message="记忆已删除。", profile=profile)

    async def delete_from_text(self, *, user_id: int, text: str) -> MemoryDeleteResult:
        profile_id = _extract_id(text)
        if profile_id is not None:
            return await self.delete_by_id(user_id=user_id, profile_id=profile_id)

        profiles = await self.repository.list_active(user_id=user_id, limit=30)
        keyword = _extract_delete_keyword(text)
        for profile in profiles:
            if keyword and (keyword in profile.profile_key or keyword in profile.profile_value):
                return await self.delete_by_id(user_id=user_id, profile_id=profile.id)
        return MemoryDeleteResult(status="not_found", message="没有找到要删除的记忆。")


def extract_memory_candidate(text: str) -> MemoryCandidate | None:
    # Rule-based extraction keeps the first memory MVP deterministic.
    normalized = text.strip()
    if not normalized:
        return None

    topics = _extract_known_topics(normalized)
    if topics and any(keyword in normalized for keyword in ("资讯", "新闻", "早报", "简报")):
        return MemoryCandidate("briefing.topics", ",".join(topics), "merge_list")

    avoid = _match_value(normalized, [r"不喜欢(.+)", r"不吃(.+)", r"讨厌(.+)", r"对(.+)过敏"])
    if avoid:
        return MemoryCandidate("preference.avoid", avoid, "merge_list")

    like = _match_value(normalized, [r"喜欢(.+)", r"偏好(.+)", r"爱看(.+)", r"爱吃(.+)"])
    if like:
        return MemoryCandidate("preference.like", like, "merge_list")

    explicit = _match_value(normalized, [r"记住[:：]?\s*(.+)", r"记一下[:：]?\s*(.+)"])
    if explicit:
        return MemoryCandidate("preference.note", explicit, "merge_list")

    scalar = re.search(r"我的(.+?)是(.+)", normalized)
    if scalar:
        key = _normalize_profile_key(scalar.group(1))
        return MemoryCandidate(f"user.{key}", _clean_value(scalar.group(2)), "overwrite")

    return None


def format_memories_for_prompt(profiles: list[UserProfile]) -> str:
    if not profiles:
        return "无"
    return "\n".join(
        f"- #{profile.id} {profile.profile_key}: {profile.profile_value}" for profile in profiles
    )


def _merge_profile_value(*, existing: str | None, incoming: str, strategy: str) -> str:
    if strategy != "merge_list" or not existing:
        return incoming
    values = _split_values(existing) + _split_values(incoming)
    deduped = list(dict.fromkeys(value for value in values if value))
    return ",".join(deduped[:30])


def _extract_known_topics(text: str) -> list[str]:
    candidates = ["AI", "科技", "财经", "商业", "体育", "娱乐", "国际", "国内", "健康", "天气"]
    return [topic for topic in candidates if topic.lower() in text.lower()]


def _match_value(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_value(match.group(1))
    return ""


def _clean_value(value: str) -> str:
    value = re.sub(r"(，|。|,|\.|；|;).*$", "", value)
    value = re.sub(r"^(我|你|请|以后|帮我|可以)", "", value)
    return value.strip(" ：:，。,.；;")


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，、/]", value) if item.strip()]


def _extract_id(text: str) -> int | None:
    match = re.search(r"(?:#|编号|id|ID)\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _extract_delete_keyword(text: str) -> str:
    keyword = re.sub(r"(删除|取消|忘掉|别记|记忆|偏好|编号|id|ID|#|\d+)", "", text)
    return keyword.strip(" ，。,.")


def _normalize_profile_key(raw_key: str) -> str:
    key = re.sub(r"\s+", "_", raw_key.strip().lower())
    return re.sub(r"[^a-z0-9_\u4e00-\u9fff]", "", key)[:40] or "note"
