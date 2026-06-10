import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LifeRecord
from app.repositories import LifeRecordRepository


@dataclass(frozen=True)
class LifeRecordCandidate:
    record_type: str
    content: str
    amount: Decimal | None
    currency: str | None
    tags: list[str]


@dataclass(frozen=True)
class LifeRecordCreateResult:
    status: str
    message: str
    record: LifeRecord | None = None
    needs_clarification: bool = False


class LifeRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = LifeRecordRepository(session)

    async def create_from_text(self, *, user_id: int, text: str) -> LifeRecordCreateResult:
        candidate = parse_life_record_text(text)
        if candidate is None:
            return LifeRecordCreateResult(
                status="needs_clarification",
                message="我还没识别出要保存的备忘内容。",
                needs_clarification=True,
            )
        record = await self.repository.create(
            user_id=user_id,
            record_type=candidate.record_type,
            content=candidate.content,
            amount=candidate.amount,
            currency=candidate.currency,
            tags=candidate.tags,
            extra_metadata={"source_text": text},
            recorded_at=datetime.now(UTC),
        )
        return LifeRecordCreateResult(status="created", message="备忘录已保存。", record=record)

    async def list_active(
        self,
        *,
        user_id: int,
        record_type: str | None = None,
        limit: int = 20,
    ) -> list[LifeRecord]:
        return await self.repository.list_active(
            user_id=user_id,
            record_type=record_type,
            limit=limit,
        )


def parse_life_record_text(text: str) -> LifeRecordCandidate | None:
    # Rule parser covers common MVP memos: expense, income, weight, exercise, sleep and water.
    normalized = text.strip()
    if not normalized:
        return None

    if any(keyword in normalized for keyword in ("收入", "入账", "工资")):
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("income", _clean_record_content(normalized), amount, "CNY", [])

    if any(keyword in normalized for keyword in ("记账", "花了", "消费", "支出", "买")):
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("expense", _clean_record_content(normalized), amount, "CNY", [])

    if "体重" in normalized:
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("weight", _clean_record_content(normalized), amount, "kg", [])

    if any(keyword in normalized for keyword in ("运动", "跑步", "健身", "骑行", "游泳")):
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("exercise", _clean_record_content(normalized), amount, None, [])

    if any(keyword in normalized for keyword in ("睡了", "睡眠", "睡觉")):
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("sleep", _clean_record_content(normalized), amount, "hour", [])

    if "喝水" in normalized:
        amount = _extract_amount(normalized)
        return LifeRecordCandidate("water", _clean_record_content(normalized), amount, "ml", [])

    if any(keyword in normalized for keyword in ("备忘", "备忘录", "记录")):
        return LifeRecordCandidate("note", _clean_record_content(normalized), None, None, [])

    return None


def infer_record_type_for_query(text: str) -> str | None:
    if any(keyword in text for keyword in ("花", "消费", "支出", "记账")):
        return "expense"
    if "收入" in text:
        return "income"
    if "体重" in text:
        return "weight"
    if any(keyword in text for keyword in ("运动", "跑步", "健身")):
        return "exercise"
    if any(keyword in text for keyword in ("睡眠", "睡了")):
        return "sleep"
    return None


def _extract_amount(text: str) -> Decimal | None:
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return Decimal(match.group(1)) if match else None


def _clean_record_content(text: str) -> str:
    content = re.sub(r"^(帮我|请|备忘一下|备忘录|备忘|记录一下|记录|记账)", "", text)
    return content.strip(" ：:，。,.；;")[:2000]
