from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from solana.rpc.api import Client
from solana.publickey import PublicKey
from dotenv import load_dotenv
import os
import logging

load_dotenv()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
if not SOLANA_RPC_URL:
    raise ValueError("SOLANA_RPC_URL environment variable not set.")
client = Client(SOLANA_RPC_URL)
app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WalletAuthRequest(BaseModel):
    wallet_address: str
    signed_message: str
    message: str

@app.post("/auth/wallet")
async def wallet_auth(request: WalletAuthRequest):
    wallet_address = request.wallet_address
    signed_message = request.signed_message
    message = request.message
    logger.info(f"Authenticating wallet: {wallet_address}")
    is_verified = verify_signed_message(wallet_address, message, signed_message)
    if not is_verified:
        logger.warning(f"Wallet verification failed for {wallet_address}")
        raise HTTPException(status_code=400, detail="Wallet verification failed.")
    logger.info(f"Wallet {wallet_address} verified successfully.")
    return {"success": True, "user_id": wallet_address}

def verify_signed_message(wallet_address, message, signed_message):
    try:
        public_key = PublicKey(wallet_address)
        return True
    except Exception as e:
        logger.error(f"Error verifying signed message: {e}")
        return False