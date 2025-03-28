from fastapi import FastAPI, HTTPException, Request, Depends, status, Form, Security
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import httpx
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.message import Message
import os
from datetime import datetime, timedelta
from typing import List, Optional, Annotated
from pydantic import BaseModel, validator, Field
import logging
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.hcaptcha_secret = os.getenv("HCAPTCHA_SECRET", "")
        self.hcaptcha_sitekey = os.getenv("HCAPTCHA_SITEKEY", "")
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.jwt_secret = os.getenv("JWT_SECRET", "secret")
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./solsocial.db")
        self.cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")

settings = Settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = create_engine(
    settings.database_url,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String(44), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    author_wallet = Column(String(44), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting SolSocial API")
    yield
    logger.info("Shutting down SolSocial API")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Authorization"]
)

@app.middleware("http")
async def force_https(request: Request, call_next):
    if os.getenv("ENVIRONMENT") == "production":
        if request.url.scheme == "http":
            url = request.url.replace(scheme="https")
            raise HTTPException(status_code=301, headers={"Location": str(url)})
    return await call_next(request)

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)

async def get_current_user(
    token: str = Security(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        wallet_address: str = payload.get("sub")
        if wallet_address is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.wallet_address == wallet_address).first()
    if user is None:
        raise credentials_exception
    return user

async def verify_hcaptcha(token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://hcaptcha.com/siteverify",
                data={"secret": settings.hcaptcha_secret, "response": token}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"hCaptcha verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify captcha"
        )

class WalletAuthRequest(BaseModel):
    wallet_address: str = Field(..., min_length=32, max_length=44)
    signed_message: List[int]
    message: str = Field(..., min_length=10)

    @validator('wallet_address')
    def validate_wallet_address(cls, v):
        try:
            Pubkey.from_string(v)
        except ValueError as e:
            raise ValueError("Invalid Solana wallet address") from e
        return v

class PostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=280)
    author: str = Field(..., min_length=32, max_length=44)

class PostResponse(BaseModel):
    id: int
    content: str
    author_wallet: str
    created_at: datetime

    class Config:
        from_attributes = True

@app.get("/", tags=["Root"])
async def root():
    return {"status": "SolSocial API running", "version": "1.0.0"}

@app.get("/health", tags=["Health"])
async def health_check():
    try:
        async with httpx.AsyncClient() as client:
            solana_client = Client(settings.solana_rpc_url)
            solana_client.get_block_height()
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "services": ["solana_rpc"]
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.post("/verify-captcha", tags=["Auth"])
async def verify_captcha(token: str = Form(...)):
    result = await verify_hcaptcha(token)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captcha verification failed"
        )
    return {"success": True}

@app.post("/auth/wallet", tags=["Auth"])
async def wallet_auth(
    auth: WalletAuthRequest,
    hcaptcha_token: str = Form(...),
    db: Session = Depends(get_db)
):
    captcha_result = await verify_hcaptcha(hcaptcha_token)
    if not captcha_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captcha verification failed"
        )
    pubkey = Pubkey.from_string(auth.wallet_address)
    msg = Message.new(bytes(auth.message, 'utf-8'))
    if not pubkey.verify(msg, bytes(auth.signed_message)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )
    user = db.query(User).filter(User.wallet_address == auth.wallet_address).first()
    if not user:
        user = User(wallet_address=auth.wallet_address)
        db.add(user)
        db.commit()
        db.refresh(user)
    access_token = create_access_token({"sub": auth.wallet_address})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "wallet_address": auth.wallet_address
    }

@app.get("/posts", response_model=List[PostResponse], tags=["Posts"])
async def get_posts(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    posts = db.query(Post).order_by(Post.created_at.desc()).offset(skip).limit(limit).all()
    return posts

@app.post("/posts", response_model=PostResponse, tags=["Posts"])
async def create_post(
    post: PostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_post = Post(
        content=post.content,
        author_wallet=current_user.wallet_address
    )
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={"message": "Endpoint not found"},
        headers={"Access-Control-Allow-Origin": "*"}
    )