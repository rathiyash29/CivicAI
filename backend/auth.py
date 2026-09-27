import os
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from jose import JWTError, jwt

load_dotenv = None
try:
    from dotenv import load_dotenv as _load_dotenv
    load_dotenv = _load_dotenv
except ImportError:
    pass

if load_dotenv:
    load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

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

class UserInDB(UserResponse):
    password_hash: str

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
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
        return TokenData(email=email)
    except JWTError:
        return None

MOCK_USERS_DB: dict[int, UserInDB] = {}
USER_ID_COUNTER = 0

def create_user(user_data: UserCreate) -> UserInDB:
    global USER_ID_COUNTER
    USER_ID_COUNTER += 1
    
    for user in MOCK_USERS_DB.values():
        if user.email == user_data.email:
            raise ValueError("Email already registered")
    
    hashed_password = get_password_hash(user_data.password)
    now = datetime.utcnow()
    
    user = UserInDB(
        id=USER_ID_COUNTER,
        full_name=user_data.full_name,
        email=user_data.email,
        password_hash=hashed_password,
        role=user_data.role,
        created_at=now
    )
    
    MOCK_USERS_DB[USER_ID_COUNTER] = user
    return user

def get_user_by_email(email: str) -> Optional[UserInDB]:
    for user in MOCK_USERS_DB.values():
        if user.email == email:
            return user
    return None

def get_user_by_id(user_id: int) -> Optional[UserInDB]:
    return MOCK_USERS_DB.get(user_id)

def authenticate_user(email: str, password: str) -> Optional[UserInDB]:
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user