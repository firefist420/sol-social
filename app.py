# -*- coding: utf-8 -*-

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
import time
import logging
from datetime import datetime, timedelta
from typing import List
import databases
import sqlalchemy
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from contextlib import asynccontextmanager
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.solana_rpc_url = "https://api.mainnet-beta.solana.com"
        self.database_url = os.getenv("DATABASE_URL")
        self.jwt_secret = os.getenv("JWT_SECRET")
        self.jwt_algorithm = "HS256"
        self.jwt_expire_minutes = 10080

settings = Settings()
client = Client(settings.solana_rpc_url)
database = databases.Database(settings.database_url)
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

app = FastAPI(lifespan=lifespan)
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

@app.get("/")
async def root():
    return {"status": "API running"}

@app.post("/auth/wallet", response_model=AuthResponse)
@limiter.limit("5/minute")
async def wallet_auth(request: Request, auth: WalletAuthRequest):
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
@limiter.limit("5/minute")
async def create_post(request: Request, post: PostCreate, wallet: str = Depends(get_current_user)):
    if wallet != post.wallet_address:
        raise HTTPException(status_code=403, detail="Unauthorized")
    post_id = await database.execute(posts.insert().values(
        content=post.content,
        author=post.author,
        wallet_address=post.wallet_address,
        likes=0,
        liked_by=[],
        created_at=datetime.now()
    ))
    return {**post.dict(), "id": post_id, "likes": 0, "liked_by": []}

@app.get("/posts", response_model=List[Post])
async def get_posts():
    return await database.fetch_all(posts.select().order_by(posts.c.created_at.desc()))

@app.post("/posts/{post_id}/like", response_model=Post)
async def like_post(post_id: int, wallet: str = Depends(get_current_user)):
    post = await database.fetch_one(posts.select().where(posts.c.id == post_id))
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    liked_by = post["liked_by"] or []
    new_likes = post["likes"] + 1 if wallet not in liked_by else post["likes"] - 1
    await database.execute(posts.update()
        .where(posts.c.id == post_id)
        .values(likes=new_likes, liked_by=liked_by))
    return {**post, "likes": new_likes, "liked_by": liked_by}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000)