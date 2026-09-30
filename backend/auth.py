"""
Authentication for CivicAI.

Accounts live in PostgreSQL, in the existing `users` table
(`database/models.py`), so a user survives a restart and a second process sees
the same accounts. They are looked up through the shared engine in
`database/db.py` -- the one engine the rest of the app already uses, rather
than a second one created here.

Passwords are hashed with bcrypt and only the hash is ever stored. No code path
in this module writes a plaintext password, and no response model includes the
hash column.

Tokens
------
`JWT_SECRET_KEY` is required. There is deliberately no default and no random
per-process fallback: a secret generated at startup would silently invalidate
every issued token on the next restart, which looks like a mass logout rather
than a configuration problem. A missing key is a startup error instead, and the
message names the variable without ever printing a value.

The secret is read once at import. Tests that need to exercise a different
secret reload the module; see tests/test_auth_persistence.py.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy.orm import Session

load_dotenv = None
try:
    from dotenv import load_dotenv as _load_dotenv
    load_dotenv = _load_dotenv
except ImportError:
    pass

if load_dotenv:
    load_dotenv()

logger = logging.getLogger("auth")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

#: bcrypt produces a 60-character digest; 255 leaves room for a future scheme
#: without needing another migration.
PASSWORD_HASH_MAX_LENGTH = 255


class AuthConfigurationError(RuntimeError):
    """
    The service is not configured well enough to issue or verify tokens.

    Raised at import time when `JWT_SECRET_KEY` is absent. This is a
    configuration fault, not a user error, so it is a hard failure: continuing
    would mean signing tokens with a secret that changes on every restart,
    quietly logging everyone out each time the process is replaced.
    """


def _resolve_secret_key() -> str:
    """
    Read `JWT_SECRET_KEY` from the environment, or fail clearly.

    Called once at import. The value is never logged, echoed, or included in
    the error, so a failure cannot leak the secret into a log file or a CI
    transcript.
    """
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if not secret:
        raise AuthConfigurationError(
            "JWT_SECRET_KEY is not set. Authentication cannot start without a "
            "stable signing secret: a generated one would invalidate every "
            "issued token on the next restart. Set JWT_SECRET_KEY in "
            "backend/.env (see backend/.env.example), or in the process "
            "environment. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    if secret == "your_jwt_secret_key_here_change_in_production":
        # The value shipped in .env.example. It is public in the repository, so
        # anyone could mint a token for any account with it.
        raise AuthConfigurationError(
            "JWT_SECRET_KEY is still the placeholder from backend/.env.example. "
            "That value is published in the repository, so it cannot sign real "
            "tokens. Generate a unique secret with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return secret


SECRET_KEY = _resolve_secret_key()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserRole(str):
    CITIZEN = "citizen"
    OFFICER = "officer"


class UserBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    role: str = Field(default=UserRole.CITIZEN)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
        return TokenData(email=email)
    except JWTError:
        return None


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

def _models():
    """Import the model lazily so this module can be imported on its own."""
    from database import models
    return models


def normalise_email(email: str) -> str:
    """
    The single form an email is stored and looked up as.

    Matching is case-insensitive and whitespace-tolerant, so `Alice@x.com` and
    `alice@x.com` are one account rather than two. This is also the value
    `users.auth_key` is derived from, so the two can never disagree about who an
    account is -- the failure that would let one person inherit another's
    complaints.
    """
    return str(email).strip().lower()


def to_response(row) -> UserResponse:
    """Project a `users` row onto the API shape. Never includes the hash."""
    return UserResponse(
        id=row.id,
        full_name=row.name or row.email,
        email=row.email,
        role=row.role or UserRole.CITIZEN,
        created_at=row.created_at,
    )


def create_user(db: Session, user_data: UserCreate) -> UserResponse:
    """
    Insert an account into PostgreSQL and return it.

    `role` is honoured here because this is the service layer: out-of-band
    provisioning (scripts, tests, an admin tool) needs to create officers. The
    public HTTP registration route does not call this directly with a
    caller-chosen role -- see `main.register`.

    Raises `ValueError` when the email is taken, which the HTTP layer turns into
    a 400.
    """
    models = _models()
    email = normalise_email(user_data.email)

    existing = db.query(models.User).filter_by(email=email).first()
    if existing is not None:
        raise ValueError("Email already registered")

    row = models.User(
        name=user_data.full_name,
        email=email,
        # Set at creation so complaint ownership resolves to this same row
        # without a second lookup or an adoption step.
        auth_key=email,
        password_hash=get_password_hash(user_data.password),
        role=(user_data.role or UserRole.CITIZEN).strip().lower(),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 - re-raised as a 400 by the caller
        db.rollback()
        # A unique-violation here means a concurrent registration of the same
        # email won the race. The loser gets the same message as anyone
        # registering a taken address rather than a driver error.
        logger.info("User insert for %s failed: %s", email, type(exc).__name__)
        raise ValueError("Email already registered") from exc
    db.refresh(row)
    return to_response(row)


def get_user_by_email(db: Session, email: str) -> Optional[object]:
    models = _models()
    key = normalise_email(email)
    row = db.query(models.User).filter_by(email=key).first()
    if row is None:
        # Tolerate a row stored before normalisation, matched on auth_key.
        row = db.query(models.User).filter_by(auth_key=key).first()
    return row


def get_user_by_id(db: Session, user_id: int) -> Optional[object]:
    models = _models()
    return db.query(models.User).filter_by(id=user_id).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[object]:
    """
    The row for a correct email+password, or None.

    A row with no `password_hash` cannot log in. Such rows exist for accounts
    that predated database-backed auth, and the password that unlocked them
    lived in a process that no longer exists. They are refused rather than
    accepted, because the alternative -- treating a missing hash as an empty
    password -- would be an authentication bypass.
    """
    row = get_user_by_email(db, email)
    if row is None:
        return None
    if not row.password_hash:
        logger.info("Login refused for %s: account has no password set", row.email)
        return None
    if not verify_password(password, row.password_hash):
        return None
    return row
