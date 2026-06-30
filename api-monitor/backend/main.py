import asyncio
import os
from datetime import datetime, timedelta
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

# ============================================================================
# Configuration & Database
# ============================================================================

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "monitor_db")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

app = FastAPI(title="API Performance Monitor", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mongo_client: AsyncIOMotorClient | None = None
urls_collection = None
logs_collection = None
users_collection = None
security = HTTPBearer()
password_context = CryptContext(schemes=["argon2"], deprecated="auto")

# ============================================================================
# Request Models
# ============================================================================

class URLRequest(BaseModel):
    """Schema for POST /track endpoint"""
    url: str


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ============================================================================
# Database Helpers
# ============================================================================

async def init_db() -> None:
    global mongo_client, urls_collection, logs_collection, users_collection

    mongo_client = AsyncIOMotorClient(MONGODB_URI)
    database = mongo_client[MONGODB_DB]
    users_collection = database["users"]
    urls_collection = database["urls"]
    logs_collection = database["logs"]

    await users_collection.create_index("email", unique=True)

    existing_indexes = {index["name"] async for index in urls_collection.list_indexes()}
    if "url_1" in existing_indexes:
        await urls_collection.drop_index("url_1")

    await urls_collection.create_index([("user_id", 1), ("url", 1)], unique=True)
    await logs_collection.create_index([("user_id", 1), ("checked_at", -1)])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload.update({"exp": expire})
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise JWTError("Missing user_id claim")
        return str(user_id)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(token: HTTPAuthorizationCredentials = Depends(security)) -> str:
    return decode_access_token(token.credentials)


async def get_tracked_urls_list(user_id: str) -> list[str]:
    cursor = urls_collection.find({"user_id": user_id}, {"_id": 0, "url": 1})
    return [doc["url"] async for doc in cursor]


async def get_tracked_urls_to_monitor() -> list[dict]:
    cursor = urls_collection.find({}, {"_id": 0, "url": 1, "user_id": 1})
    return [doc async for doc in cursor]


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/auth/register")
async def register_user(request: AuthRequest):
    existing_user = await users_collection.find_one({"email": request.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )

    await users_collection.insert_one(
        {
            "email": request.email,
            "password_hash": get_password_hash(request.password),
            "created_at": datetime.utcnow(),
        }
    )

    return {"message": "Registration successful. Please log in."}


@app.post("/auth/login", response_model=TokenResponse)
async def login_user(request: AuthRequest):
    user = await users_collection.find_one({"email": request.email})
    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token({"user_id": str(user["_id"])})
    return {"access_token": access_token}


@app.post("/track")
async def track_url(request: URLRequest, user_id: str = Depends(get_current_user)):
    """
    Store a unique URL in MongoDB for tracking.
    """
    raw_url = request.url.strip()
    normalized_url = raw_url if raw_url.startswith(("http://", "https://")) else f"https://{raw_url}"

    result = await urls_collection.update_one(
        {"url": normalized_url, "user_id": user_id},
        {
            "$setOnInsert": {
                "url": normalized_url,
                "created_at": datetime.utcnow(),
                "user_id": user_id,
            }
        },
        upsert=True,
    )

    already_tracked = result.matched_count > 0 and result.upserted_id is None
    message = (
        f"URL '{normalized_url}' is already being tracked"
        if already_tracked
        else f"URL '{normalized_url}' is now being tracked"
    )

    urls = await get_tracked_urls_list(user_id)
    return {
        "message": message,
        "tracked_urls": urls,
        "total": len(urls),
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    current_count = await urls_collection.count_documents({})
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "tracked_urls_count": current_count,
    }


@app.get("/tracked-urls")
async def get_tracked_urls(user_id: str = Depends(get_current_user)):
    """Get all currently tracked URLs for the authenticated user"""
    urls = await get_tracked_urls_list(user_id)
    return {
        "urls": urls,
        "count": len(urls),
    }


@app.get("/logs")
async def get_logs(user_id: str = Depends(get_current_user)):
    """Fetch the 50 most recent ping logs for the authenticated user."""
    cursor = logs_collection.find({"user_id": user_id}, {"_id": 0}).sort("checked_at", -1).limit(50)
    logs = [
        {
            **doc,
            "checked_at": doc["checked_at"].isoformat(),
        }
        async for doc in cursor
    ]
    return {"logs": logs}


# ============================================================================
# Background Monitoring Worker
# ============================================================================

async def ping_and_log(url: str, user_id: str | None, client: httpx.AsyncClient):
    """Ping one URL and write a log entry to MongoDB."""
    checked_at = datetime.utcnow()
    log_document = {
        "url": url,
        "checked_at": checked_at,
        "user_id": user_id,
    }

    try:
        response = await client.get(url, follow_redirects=True)
        status_code = response.status_code
        log_document["status_code"] = status_code

        if 200 <= status_code < 300:
            status = "UP"
            indicator = "✓"
        elif 300 <= status_code < 400:
            status = "REDIRECT"
            indicator = "→"
        elif 400 <= status_code < 500:
            status = "CLIENT_ERROR"
            indicator = "⚠"
        else:
            status = "SERVER_ERROR"
            indicator = "✗"

        log_document["status"] = status
        log_document["message"] = response.reason_phrase
        print(f"[{indicator}] [{status}] {url} - {status_code} {response.reason_phrase}")

    except httpx.TimeoutException:
        log_document.update({"status": "DOWN", "status_code": None, "message": "Timeout"})
        print(f"[✗] [DOWN] {url} - Request Timeout")
    except httpx.ConnectError as exc:
        log_document.update({"status": "DOWN", "status_code": None, "message": f"Connection Error: {exc}"})
        print(f"[✗] [DOWN] {url} - Connection Error: {exc}")
    except Exception as exc:
        log_document.update({"status": "DOWN", "status_code": None, "message": f"Error: {type(exc).__name__}: {exc}"})
        print(f"[✗] [DOWN] {url} - Error: {type(exc).__name__}: {exc}")

    await logs_collection.insert_one(log_document)


async def monitor_urls():
    """Infinite background worker that checks all tracked URLs every 60 seconds."""
    print("[MONITOR] Background worker started...")

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            await asyncio.sleep(60)
            tracked_urls = await get_tracked_urls_to_monitor()

            if not tracked_urls:
                print(f"[MONITOR] {datetime.utcnow().isoformat()} - No URLs to monitor")
                continue

            print(f"\n[MONITOR] Starting health check at {datetime.utcnow().isoformat()}")
            tasks = [ping_and_log(item["url"], item.get("user_id"), client) for item in tracked_urls]
            await asyncio.gather(*tasks)
            print(f"[MONITOR] Health check completed at {datetime.utcnow().isoformat()}\n")


@app.on_event("startup")
async def startup_event():
    """Initialize MongoDB and start the background worker."""
    await init_db()
    asyncio.create_task(monitor_urls())
    print("[APP] API Performance Monitor started successfully!")


@app.on_event("shutdown")
async def shutdown_event():
    """Close the MongoDB client on shutdown."""
    if mongo_client is not None:
        mongo_client.close()
    print("[APP] API Performance Monitor shutting down...")


# ============================================================================
# Server Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
