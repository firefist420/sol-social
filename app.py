from fastapi import FastAPI, HTTPException, Request, Depends, status, Form
import httpx
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
from datetime import datetime, timedelta
from typing import List
from pydantic import BaseModel, validator
import logging
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.hcaptcha_secret = os.getenv("HCAPTCHA_SECRET")
        self.hcaptcha_sitekey = os.getenv("HCAPTCHA_SITEKEY")
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL")
        self.jwt_secret = os.getenv("JWT_SECRET")
        self.cors_origins = os.getenv("CORS_ORIGINS", "").split(",")

settings = Settings()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "SolSocial API running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/health")
async def api_health_check():
    return {"status": "healthy"}

async def verify_hcaptcha(token: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://hcaptcha.com/siteverify",
                data={"secret": settings.hcaptcha_secret, "response": token}
            )
            return response.json()
    except Exception as e:
        logger.error(f"hCaptcha verification failed: {e}")
        return {"success": False}

@app.post("/verify-captcha")
async def verify_captcha(token: str = Form(...)):
    result = await verify_hcaptcha(token)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail="Captcha verification failed")
    return {"success": True}

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

@app.post("/auth/wallet")
async def wallet_auth(request: Request, auth: WalletAuthRequest, hcaptcha_token: str = Form(...)):
    captcha_result = await verify_hcaptcha(hcaptcha_token)
    if not captcha_result.get("success"):
        raise HTTPException(status_code=400, detail="Captcha verification failed")
    
    try:
        pubkey = Pubkey.from_string(auth.wallet_address)
        msg = Message.new(bytes(auth.message, 'utf-8'))
        if not pubkey.verify(msg, bytes(auth.signed_message)):
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        return {"success": True, "wallet_address": auth.wallet_address}
    except Exception as e:
        logger.error(f"Wallet verification failed: {e}")
        raise HTTPException(status_code=401, detail="Wallet verification failed")

@app.get("/posts")
async def get_posts():
    return {"posts": []}

@app.post("/posts")
async def create_post():
    return {"status": "success"}