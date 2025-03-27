# -*- coding: utf-8 -*-

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional
import databases
import sqlalchemy
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from contextlib import asynccontextmanager
from pydantic.v1 import BaseSettings
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    database_url: str = "postgresql+asyncpg://user:pass@host:5432/db"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080
    
    class Config:
        env_file = ".env"

settings = Settings()

client = Client(settings.solana_rpc_url)
database = databases.Database(settings.database_url, min_size=5, max_size=20)
metadata = sqlalchemy.MetaData()
security = HTTPBearer()

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

engine = sqlalchemy.create_engine(settings.database_url)
metadata.create_all(engine)

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: List[int]
    message: str

class AuthResponse(BaseModel):
    success: bool
    user_id: str
    auth_token: str = None

class PostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=280)
    author: str = Field(..., min_length=3, max_length=50)
    wallet_address: str
    
    @validator('wallet_address')
    def validate_wallet(cls, v):
        try:
            Pubkey.from_string(v)
            return v
        except:
            raise ValueError("Invalid wallet address")

class Post(PostCreate):
    id: int
    likes: int = 0
    liked_by: List[str] = []
    created_at: datetime = datetime.now()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    yield
    await database.disconnect()

app = FastAPI(root_path="/api", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url} {response.status_code} {process_time:.2f}s")
    return response

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        wallet_address: str = payload.get("sub")
        if wallet_address is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return wallet_address
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

def verify_signed_message(wallet_address: str, message: str, signed_message: List[int]) -> bool:
    if "SolSocial Auth" not in message:
        return False
    try:
        public_key = Pubkey.from_string(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message.new(bytes(message, 'utf-8'))
        return public_key.verify(message_obj, signature_bytes)
    except Exception:
        return False

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )

@app.exception_handler(databases.DatabaseError)
async def database_exception_handler(request: Request, exc: databases.DatabaseError):
    logger.error(f"Database error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )

@app.head("/")
@app.get("/")
async def root():
    return {"status": "SolSocial API is running"}

@app.get("/api/health")
async def health_check():
    try:
        await database.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return {"status": "unhealthy", "database": "disconnected"}, 503

@app.post("/api/auth/wallet", response_model=AuthResponse)
@limiter.limit("5/minute")
async def wallet_auth(request: Request, auth_request: WalletAuthRequest):
    if not verify_signed_message(auth_request.wallet_address, auth_request.message, auth_request.signed_message):
        raise HTTPException(status_code=401, detail="Wallet verification failed")
    token_data = {
        "sub": auth_request.wallet_address,
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    }
    token = jwt.encode(token_data, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return {"success": True, "user_id": auth_request.wallet_address, "auth_token": token}

@app.post("/api/posts", response_model=Post)
@limiter.limit("5/minute")
async def create_post(request: Request, post: PostCreate, wallet_address: str = Depends(get_current_user)):
    if wallet_address != post.wallet_address:
        raise HTTPException(status_code=403, detail="Not authorized")
    query = posts.insert().values(
        content=post.content,
        author=post.author,
        wallet_address=post.wallet_address,
        likes=0,
        liked_by=[],
        created_at=datetime.now()
    )
    record_id = await database.execute(query)
    return {**post.dict(), "id": record_id, "likes": 0, "liked_by": [], "created_at": datetime.now()}

@app.get("/api/posts", response_model=List[Post])
async def get_posts():
    query = posts.select().order_by(posts.c.created_at.desc())
    return await database.fetch_all(query)

@app.post("/api/posts/{post_id}/like", response_model=Post)
async def like_post(post_id: int, wallet_address: str = Depends(get_current_user)):
    query = posts.select().where(posts.c.id == post_id)
    post = await database.fetch_one(query)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    liked_by = post["liked_by"] or []
    if wallet_address not in liked_by:
        liked_by.append(wallet_address)
        new_likes = post["likes"] + 1
    else:
        liked_by.remove(wallet_address)
        new_likes = post["likes"] - 1
    update_query = (
        posts.update()
        .where(posts.c.id == post_id)
        .values(likes=new_likes, liked_by=liked_by)
    )
    await database.execute(update_query)
    return {**post, "likes": new_likes, "liked_by": liked_by}