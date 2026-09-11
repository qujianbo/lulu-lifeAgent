from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationMessage


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self, *, user_id: int, conversation_uuid: str | None = None
    ) -> Conversation:
        if conversation_uuid:
            try:
                parsed_uuid = UUID(conversation_uuid)
            except ValueError:
                parsed_uuid = None
            if parsed_uuid is not None:
                result = await self.session.execute(
                    select(Conversation).where(
                        Conversation.conversation_uuid == parsed_uuid,
                        Conversation.user_id == user_id,
                        Conversation.status == "active",
                        Conversation.deleted_at.is_(None),
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    return existing
        now = datetime.now(UTC)
        item = Conversation(
            conversation_uuid=uuid4(),
            user_id=user_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_for_user(self, *, user_id: int, limit: int = 30) -> list[Conversation]:
        query: Select[tuple[Conversation]] = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.status == "active",
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def add_message(
        self,
        *,
        conversation: Conversation,
        role: str,
        content: str,
        intent: str | None = None,
        tool_name: str | None = None,
        related_entities: list[dict] | None = None,
        extra_metadata: dict | None = None,
    ) -> ConversationMessage:
        now = datetime.now(UTC)
        item = ConversationMessage(
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            role=role,
            content=content[:10000],
            intent=intent,
            tool_name=tool_name,
            related_entities=related_entities,
            extra_metadata=extra_metadata,
            created_at=now,
        )
        self.session.add(item)
        conversation.last_message_at = now
        conversation.updated_at = now
        if not conversation.title and role == "user":
            conversation.title = content.strip()[:40]
        await self.session.flush()
        return item

    async def set_pending_action(
        self, *, conversation: Conversation, pending_action: dict | None
    ) -> None:
        conversation.pending_action = pending_action
        conversation.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def list_messages(
        self, *, conversation_id: int, user_id: int, limit: int = 40
    ) -> list[ConversationMessage]:
        conversation = await self.get_by_id(conversation_id=conversation_id, user_id=user_id)
        if conversation is None:
            return []
        result = await self.session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
            )
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def get_by_uuid(self, *, conversation_uuid: str, user_id: int) -> Conversation | None:
        try:
            parsed_uuid = UUID(conversation_uuid)
        except ValueError:
            return None
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.conversation_uuid == parsed_uuid,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, *, conversation_id: int, user_id: int) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
