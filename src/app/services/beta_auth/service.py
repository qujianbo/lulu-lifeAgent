import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BetaSession, BetaUser
from app.repositories.users import UserRepository
from app.services.user_ids import DEFAULT_PRODUCT_CODE, DEFAULT_WEB_BETA_CHANNEL_CODE

BETA_SESSION_COOKIE = "lulu_beta_session"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390_000
SESSION_DAYS = 7


@dataclass(frozen=True)
class BetaLoginResult:
    user: BetaUser
    token: str
    expires_at: datetime


class BetaAuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_beta_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = "tester",
        remark: str | None = None,
    ) -> BetaUser:
        normalized = normalize_username(username)
        if len(password) < 8:
            raise BetaAuthError("password_too_short")
        existing = await self.get_by_username(normalized)
        if existing is not None:
            raise BetaAuthError("username_exists")

        now = datetime.now(UTC)
        user_repo = UserRepository(self.session)
        business_user = await user_repo.create_web_beta_user(
            beta_username=normalized,
            now=now,
            product_code=DEFAULT_PRODUCT_CODE,
            channel_code=DEFAULT_WEB_BETA_CHANNEL_CODE,
        )
        beta_user = BetaUser(
            user_id=business_user.id,
            username=normalized,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
            status="active",
            remark=remark,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(beta_user)
        await self.session.flush()
        return beta_user

    async def get_by_username(self, username: str) -> BetaUser | None:
        result = await self.session.execute(
            select(BetaUser).where(
                BetaUser.username == normalize_username(username),
                BetaUser.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_beta_users(self, *, limit: int = 100) -> list[BetaUser]:
        result = await self.session.execute(
            select(BetaUser).where(BetaUser.deleted_at.is_(None)).order_by(BetaUser.id).limit(limit)
        )
        return list(result.scalars().all())

    async def login(
        self,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BetaLoginResult:
        user = await self.get_by_username(username)
        now = datetime.now(UTC)
        password_ok = user is not None and verify_password(password, user.password_hash)
        if user is None or user.status != "active" or not password_ok:
            if user is not None:
                user.failed_login_count += 1
                user.updated_at = now
                await self.session.flush()
            raise BetaAuthError("invalid_credentials")

        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(days=SESSION_DAYS)
        session = BetaSession(
            user_id=user.id,
            session_token_hash=hash_session_token(token),
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        user.last_login_at = now
        user.last_seen_at = now
        user.failed_login_count = 0
        user.updated_at = now
        self.session.add(session)
        await self.session.flush()
        return BetaLoginResult(user=user, token=token, expires_at=expires_at)

    async def authenticate_session(self, token: str | None) -> BetaUser | None:
        if not token:
            return None
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(BetaSession, BetaUser)
            .join(BetaUser, BetaUser.id == BetaSession.user_id)
            .where(
                BetaSession.session_token_hash == hash_session_token(token),
                BetaSession.revoked_at.is_(None),
                BetaSession.expires_at > now,
                BetaUser.status == "active",
                BetaUser.deleted_at.is_(None),
            )
        )
        row = result.first()
        if row is None:
            return None
        session, user = row
        user.last_seen_at = now
        user.updated_at = now
        session.updated_at = now
        await self.session.flush()
        return user

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        result = await self.session.execute(
            select(BetaSession).where(
                BetaSession.session_token_hash == hash_session_token(token),
                BetaSession.revoked_at.is_(None),
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return
        now = datetime.now(UTC)
        session.revoked_at = now
        session.updated_at = now
        await self.session.flush()

    async def set_status(self, user_id: int, status: str) -> BetaUser:
        result = await self.session.execute(
            select(BetaUser).where(BetaUser.id == user_id, BetaUser.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise BetaAuthError("user_not_found")
        user.status = status
        user.updated_at = datetime.now(UTC)
        await self.session.flush()
        return user

    async def reset_password(self, user_id: int, password: str) -> BetaUser:
        if len(password) < 8:
            raise BetaAuthError("password_too_short")
        result = await self.session.execute(
            select(BetaUser).where(BetaUser.id == user_id, BetaUser.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise BetaAuthError("user_not_found")
        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.updated_at = datetime.now(UTC)
        await self.session.flush()
        return user


class BetaAuthError(RuntimeError):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_HASH_ALGORITHM,
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
