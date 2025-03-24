from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from solana.rpc.api import Client
from solana.publickey import PublicKey
from solana.message import Message
from solana.transaction import Transaction
from dotenv import load_dotenv
import os
import logging
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
if not SOLANA_RPC_URL:
    raise ValueError("SOLANA_RPC_URL environment variable not set.")

client = Client(SOLANA_RPC_URL)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: list
    message: str

@app.post("/auth/wallet")
async def wallet_auth(request: WalletAuthRequest):
    wallet_address = request.wallet_address
    signed_message = request.signed_message
    message = request.message
    
    is_verified = verify_signed_message(wallet_address, message, signed_message)
    if not is_verified:
        raise HTTPException(status_code=400, detail="Wallet verification failed.")
    
    return {"success": True, "user_id": wallet_address}

def verify_signed_message(wallet_address, message, signed_message):
    try:
        public_key = PublicKey(wallet_address)
        signature_bytes = bytes(signed_message)
        message_obj = Message(bytes(message, 'utf-8'))
        transaction = Transaction.populate(message_obj, [signature_bytes])
        return transaction.verify(public_key)
    except Exception as e:
        logger.error(f"Verification error: {e}")
        return False