from fastapi import FastAPI, HTTPException, Request, Depends, status, Form
import httpx
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel, validator
import logging
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.hcaptcha_secret = os.getenv("HCAPTCHA_SECRET")
        self.hcaptcha_sitekey = os.getenv("HCAPTCHA_SITEKEY")
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL")
        self.jwt_secret = os.getenv("JWT_SECRET")
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM")
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES"))
        self.database_url = os.getenv("DATABASE_URL")
        self.cors_origins = os.getenv("CORS_ORIGINS").split(",")

settings = Settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def verify_hcaptcha(token: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://hcaptcha.com/siteverify",
            data={"secret": settings.hcaptcha_secret, "response": token}
        )
        return response.json()

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: List[int]
    message: str

    @validator('wallet_address')
    def validate_wallet_address(cls, v):
        Pubkey.from_string(v)
        return v

class PostCreate(BaseModel):
    content: str
    author: str

@app.get("/")
async def root():
    return {"status": "SolSocial API running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/verify-captcha")
async def verify_captcha(token: str = Form(...)):
    result = await verify_hcaptcha(token)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail="Captcha verification failed")
    return {"success": True}

@app.post("/auth/wallet")
async def wallet_auth(auth: WalletAuthRequest, hcaptcha_token: str = Form(...)):
    captcha_result = await verify_hcaptcha(hcaptcha_token)
    if not captcha_result.get("success"):
        raise HTTPException(status_code=400, detail="Captcha verification failed")
    
    pubkey = Pubkey.from_string(auth.wallet_address)
    msg = Message.new(bytes(auth.message, 'utf-8'))
    if not pubkey.verify(msg, bytes(auth.signed_message)):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    access_token = create_access_token({"sub": auth.wallet_address})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/posts")
async def get_posts():
    return {"posts": []}

@app.post("/posts")
async def create_post(post: PostCreate):
    return {"status": "success", "post": post}