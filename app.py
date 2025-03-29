# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta
from typing import List, Optional, AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends, status, Form, Security
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, validator, Field
from jose import jwt, JWTError
from passlib.context import CryptContext
import httpx
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('solsocial.log')
    ]
)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.hcaptcha_secret = os.getenv("HCAPTCHA_SECRET", "ES_9f53170c4cda406bb9876e00087807c5")
        self.hcaptcha_sitekey = os.getenv("HCAPTCHA_SITEKEY", "fc42e7c4-9244-4726-a4c6-1f1e37c45ff8")
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.jwt_secret = os.getenv("JWT_SECRET", "d95dbb2e3fa2c0e6c064dc3598d3cebf")
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./solsocial.db")
        self.cors_origins = os.getenv("CORS_ORIGINS", "https://solsocial-frontend-firefist420s-projects.vercel.app,http://localhost:8501").split(",")
        self.environment = os.getenv("ENVIRONMENT", "production")

settings = Settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String(44), unique=True, index=True)
    username = Column(String(50), unique=True, nullable=True)
    bio = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    posts = relationship("Post", back_populates="author")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    author_wallet = Column(String(44), ForeignKey("users.wallet_address"))
    created_at = Column(DateTime, default=datetime.utcnow)
    author = relationship("User", back_populates="posts")

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting SolSocial API")
    yield
    logger.info("Shutting down SolSocial API")

app = FastAPI(
    lifespan=lifespan,
    title="SolSocial API",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    response = None
    try:
        request.state.db = SessionLocal()
        response = await call_next(request)
    finally:
        request.state.db.close()
    return response

def get_db(request: Request) -> Session:
    return request.state.db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)

async def get_current_user(
    token: str = Security(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        wallet_address: str = payload.get("sub")
        if wallet_address is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.wallet_address == wallet_address).first()
    if user is None:
        raise credentials_exception
    return user

async def verify_hcaptcha(token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://hcaptcha.com/siteverify",
                data={
                    "secret": settings.hcaptcha_secret,
                    "response": token,
                    "sitekey": settings.hcaptcha_sitekey
                }
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"hCaptcha verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify captcha"
        )

class WalletAuthRequest(BaseModel):
    wallet_address: str = Field(..., min_length=32, max_length=44)
    signed_message: List[int]
    message: str = Field(..., min_length=10)

    @validator('wallet_address')
    def validate_wallet_address(cls, v):
        try:
            Pubkey.from_string(v)
        except ValueError:
            raise ValueError("Invalid Solana wallet address")
        return v

class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)

class PostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=280)

class PostResponse(BaseModel):
    id: int
    content: str
    author_wallet: str
    created_at: datetime
    author: Optional[dict]

    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    wallet_address: str
    username: Optional[str]
    bio: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

@app.get("/")
async def root():
    return {"status": "SolSocial API running"}

@app.get("/health")
async def health_check():
    try:
        with SessionLocal() as db:
            db.execute("SELECT 1")
        solana_client = Client(settings.solana_rpc_url)
        solana_client.get_version()
        return {"status": "healthy"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503)

@app.post("/verify-captcha")
async def verify_captcha(token: str = Form(...)):
    result = await verify_hcaptcha(token)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captcha verification failed"
        )
    return {"success": True}

@app.post("/auth/wallet")
async def wallet_auth(
    auth: WalletAuthRequest,
    hcaptcha_token: str = Form(...),
    db: Session = Depends(get_db)
):
    captcha_result = await verify_hcaptcha(hcaptcha_token)
    if not captcha_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captcha verification failed"
        )
    
    try:
        pubkey = Pubkey.from_string(auth.wallet_address)
        msg = Message.new(bytes(auth.message, 'utf-8'))
        if not pubkey.verify(msg, bytes(auth.signed_message)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    user = db.query(User).filter(User.wallet_address == auth.wallet_address).first()
    if not user:
        user = User(wallet_address=auth.wallet_address)
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token({"sub": auth.wallet_address})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@app.get("/users/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user

@app.patch("/users/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user

@app.get("/posts", response_model=List[PostResponse])
async def get_posts(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    posts = db.query(Post).order_by(Post.created_at.desc()).offset(skip).limit(limit).all()
    return posts

@app.post("/posts", response_model=PostResponse)
async def create_post(
    post: PostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_post = Post(
        content=post.content,
        author_wallet=current_user.wallet_address
    )
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found"}
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc: HTTPException):
    logger.error(f"Server error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )