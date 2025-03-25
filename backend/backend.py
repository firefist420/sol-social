from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.transaction import Transaction
import os
import logging
from datetime import datetime
from typing import List, Optional

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
if not SOLANA_RPC_URL:
    raise RuntimeError("SOLANA_RPC_URL not set")

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

class Post(PostCreate):
    id: int
    likes: int = 0
    liked_by: List[str] = []
    created_at: Optional[datetime] = None

posts_db = []
current_id = 0

def verify_signed_message(wallet_address: str, message: str, signed_message: List[int]) -> bool:
    try:
        public_key = Pubkey.from_string(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message.new(bytes(message, 'utf-8'))
        transaction = Transaction.new_unsigned(message_obj)
        transaction.add_signature(public_key, signature_bytes)
        return transaction.verify()
    except Exception as e:
        logging.error(f"Signature verification failed: {str(e)}")
        return False

@app.get("/")
def home():
    return {"status": "running"}

@app.post("/auth/wallet", response_model=AuthResponse)
async def wallet_auth(request: WalletAuthRequest):
    if not verify_signed_message(request.wallet_address, request.message, request.signed_message):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wallet verification failed")
    return {"success": True, "user_id": request.wallet_address, "auth_token": "generated_jwt_here"}

@app.post("/posts", response_model=Post)
async def create_post(post: PostCreate):
    global current_id
    new_post = Post(
        id=current_id,
        content=post.content,
        author=post.author,
        wallet_address=post.wallet_address,
        created_at=datetime.now()
    )
    posts_db.append(new_post)
    current_id += 1
    return new_post

@app.get("/posts", response_model=List[Post])
async def get_posts():
    return sorted(posts_db, key=lambda x: x.created_at, reverse=True)

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