# -*- coding: utf-8 -*-

from fastapi import FastAPI, HTTPException, Request, Depends, status, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
import time
import logging
from datetime import datetime, timedelta
from typing import List
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update, insert, Index
import sqlalchemy
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from hcaptcha import hCaptcha
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL")
        self.database_url = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://")
        self.jwt_secret = os.getenv("JWT_SECRET")
        self.jwt_algorithm = "HS256"
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", 10080))
        self.hcaptcha_secret = os.getenv("HCAPTCHA_SECRET")
        self.hcaptcha_sitekey = os.getenv("HCAPTCHA_SITEKEY")
        self.cors_origins = os.getenv("CORS_ORIGINS", "").split(",")

settings = Settings()
client = Client(settings.solana_rpc_url)
engine = create_async_engine(settings.database_url)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
metadata = sqlalchemy.MetaData()
security = HTTPBearer()
hcaptcha = hCaptcha(settings.hcaptcha_secret)

posts = sqlalchemy.Table(
    "posts",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("content", sqlalchemy.String),
    sqlalchemy.Column("author", sqlalchemy.String),
    sqlalchemy.Column("wallet_address", sqlalchemy.String, index=True),
    sqlalchemy.Column("likes", sqlalchemy.Integer),
    sqlalchemy.Column("liked_by", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, index=True)
)

Index("idx_posts_wallet", posts.c.wallet_address)
Index("idx_posts_created", posts.c.created_at)
Index("idx_posts_likes", posts.c.likes)

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: List[int]
    message: str

    @validator('wallet_address')
    def validate_wallet_address(cls, v):
        try:
            Pubkey.from_string(v)
            return v
        except:
            raise ValueError('Invalid Solana wallet address')

class AuthResponse(BaseModel):
    success: bool
    user_id: str
    auth_token: str = None

class PostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=280)
    author: str = Field(..., min_length=3, max_length=50)
    wallet_address: str

class Post(PostCreate):
    id: int
    likes: int = 0
    liked_by: List[str] = []
    created_at: datetime = datetime.now()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["yourdomain.com"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
    max_age=600
)

async def get_db():
    async with async_session() as session:
        yield session

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        wallet_address: str = payload.get("sub")
        if wallet_address is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return wallet_address
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/")
async def root():
    return {"status": "API running"}

@app.post("/verify-captcha")
async def verify_captcha(token: str = Form(...)):
    try:
        result = await hcaptcha.verify(token)
        if not result["success"]:
            raise HTTPException(status_code=400, detail="Captcha verification failed")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/wallet", response_model=AuthResponse)
@limiter.limit("5/minute")
async def wallet_auth(request: Request, auth: WalletAuthRequest, captcha_token: str = Form(...)):
    captcha_result = await hcaptcha.verify(captcha_token)
    if not captcha_result["success"]:
        raise HTTPException(status_code=400, detail="Captcha verification failed")
    
    try:
        pubkey = Pubkey.from_string(auth.wallet_address)
        msg = Message.new(bytes(auth.message, 'utf-8'))
        if not pubkey.verify(msg, bytes(auth.signed_message)):
            raise HTTPException(status_code=401, detail="Invalid signature")
        token = jwt.encode({
            "sub": auth.wallet_address,
            "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
        }, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        return {"success": True, "user_id": auth.wallet_address, "auth_token": token}
    except Exception:
        raise HTTPException(status_code=401, detail="Wallet verification failed")

@app.post("/posts", response_model=Post)
@limiter.limit("3/minute")
async def create_post(request: Request, post: PostCreate, wallet: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if wallet != post.wallet_address:
        raise HTTPException(status_code=403, detail="Unauthorized")
    result = await db.execute(
        insert(posts).values(
            content=post.content,
            author=post.author,
            wallet_address=post.wallet_address,
            likes=0,
            liked_by=[],
            created_at=datetime.now()
        ).returning(posts)
    )
    await db.commit()
    post_data = result.first()
    return {**post.dict(), "id": post_data.id, "likes": 0, "liked_by": []}

@app.get("/posts", response_model=List[Post])
async def get_posts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(posts).order_by(posts.c.created_at.desc()))
    return result.scalars().all()

@app.post("/posts/{post_id}/like", response_model=Post)
@limiter.limit("10/minute")
async def like_post(post_id: int, wallet: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(posts).where(posts.c.id == post_id))
    post = result.scalar()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    liked_by = post.liked_by or []
    if wallet not in liked_by:
        liked_by.append(wallet)
        new_likes = post.likes + 1
    else:
        liked_by.remove(wallet)
        new_likes = post.likes - 1
    await db.execute(
        update(posts)
        .where(posts.c.id == post_id)
        .values(likes=new_likes, liked_by=liked_by)
    )
    await db.commit()
    await db.refresh(post)
    return {
        "id": post.id,
        "content": post.content,
        "author": post.author,
        "wallet_address": post.wallet_address,
        "likes": new_likes,
        "liked_by": liked_by,
        "created_at": post.created_at
    }