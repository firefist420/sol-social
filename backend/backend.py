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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
JWT_SECRET = os.getenv("JWT_SECRET", "secret")
JWT_ALGORITHM = "HS256"

client = Client(SOLANA_RPC_URL)
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()
security = HTTPBearer()

posts = sqlalchemy.Table(
    "posts",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("content", sqlalchemy.String),
    sqlalchemy.Column("author", sqlalchemy.String),
    sqlalchemy.Column("wallet_address", sqlalchemy.String),
    sqlalchemy.Column("likes", sqlalchemy.Integer),
    sqlalchemy.Column("liked_by", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime)
)

engine = sqlalchemy.create_engine(DATABASE_URL)
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

@app.head("/")
@app.get("/")
async def root():
    return {"status": "SolSocial API is running"}

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600
)

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

def verify_signed_message(wallet_address: str, message: str, signed_message: List[int]) -> bool:
    if "SolSocial Auth" not in message:
        return False
    try:
        public_key = Pubkey.from_string(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message.new(bytes(message, 'utf-8'))
        return public_key.verify(message_obj, signature_bytes)
    except Exception as e:
        logging.error(f"Verification failed: {str(e)}")
        return False

@app.get("/api/")
async def api_root():
    return {"message": "SolSocial API is running"}

@app.post("/api/auth/wallet", response_model=AuthResponse)
@limiter.limit("5/minute")
async def wallet_auth(request: Request, auth_request: WalletAuthRequest):
    if not verify_signed_message(auth_request.wallet_address, auth_request.message, auth_request.signed_message):
        raise HTTPException(status_code=401, detail="Wallet verification failed")
    token_data = {
        "sub": auth_request.wallet_address,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    token = jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"success": True, "user_id": auth_request.wallet_address, "auth_token": token}

@app.post("/api/posts", response_model=Post)
@limiter.limit("5/minute")
async def create_post(request: Request, post: PostCreate):
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
async def like_post(post_id: int, wallet_address: str):
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

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}