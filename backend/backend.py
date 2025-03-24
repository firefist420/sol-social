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

def verify_signed_message(wallet_address: str, message: str, signed_message: List[int]) -> bool:
    try:
        public_key = PublicKey(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message(bytes(message, 'utf-8'))
        transaction = Transaction.populate(message_obj, [signature_bytes])
        return transaction.verify(public_key)
    except Exception as e:
        logger.error(f"Signature verification failed for {wallet_address}: {str(e)}")
        return False

@app.post("/auth/wallet", response_model=AuthResponse)
async def wallet_auth(request: WalletAuthRequest):
    if not verify_signed_message(
        request.wallet_address,
        request.message,
        request.signed_message
    ):
        logger.warning(f"Failed authentication attempt from {request.wallet_address}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wallet signature verification failed"
        )
    
    logger.info(f"Successful authentication for {request.wallet_address}")
    return {
        "success": True,
        "user_id": request.wallet_address,
        "auth_token": "generated_jwt_here"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}