from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from solana.rpc.api import Client
from solana.publickey import PublicKey
from solana.message import Message
from solana.transaction import Transaction
from dotenv import load_dotenv
import os
import logging
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import json

load_dotenv()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
if not SOLANA_RPC_URL:
    raise RuntimeError("SOLANA_RPC_URL environment variable not set")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
client = Client(SOLANA_RPC_URL)

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: List[int]
    message: str

class AuthResponse(BaseModel):
    success: bool
    user_id: str
    auth_token: str = None

class PostCreate(BaseModel):
    content: str
    author: str
    wallet_address: str

class Post(BaseModel):
    id: int
    content: str
    author: str
    wallet_address: str
    likes: int = 0
    liked_by: List[str] = []

posts_db = []
current_id = 0

def verify_signed_message(wallet_address: str, message: str, signed_message: List[int]) -> bool:
    try:
        public_key = PublicKey(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message(bytes(message, 'utf-8'))
        transaction = Transaction()
        transaction.add_signature(public_key, signature_bytes)
        return transaction.verify(message_obj)
    except Exception as e:
        logger.error(f"Signature verification failed: {str(e)}")
        return False

@app.post("/auth/wallet", response_model=AuthResponse)
async def wallet_auth(request: WalletAuthRequest):
    if not verify_signed_message(
        request.wallet_address,
        request.message,
        request.signed_message
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wallet verification failed"
        )
    return {
        "success": True,
        "user_id": request.wallet_address,
        "auth_token": "generated_jwt_here"
    }

@app.post("/posts", response_model=Post)
async def create_post(post: PostCreate):
    global current_id
    new_post = Post(
        id=current_id,
        content=post.content,
        author=post.author,
        wallet_address=post.wallet_address
    )
    posts_db.append(new_post)
    current_id += 1
    return new_post

@app.get("/posts", response_model=List[Post])
async def get_posts():
    return posts_db

@app.post("/posts/{post_id}/like", response_model=Post)
async def like_post(post_id: int, wallet_address: str):
    for post in posts_db:
        if post.id == post_id:
            if wallet_address not in post.liked_by:
                post.liked_by.append(wallet_address)
                post.likes += 1
            else:
                post.liked_by.remove(wallet_address)
                post.likes -= 1
            return post
    raise HTTPException(status_code=404, detail="Post not found")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}