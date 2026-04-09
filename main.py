import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://kurim.ithope.eu/v1")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://student:heslo123@localhost:5432/detektivka")
PORT = int(os.getenv("PORT", "8000"))
MODEL = "gemma3:27b"
SESSION_TTL = 24 * 60 * 60
MAX_HISTORY_MESSAGES = 20

STRATEGIC_INSTRUCTION = (
    "STRATEGICKÁ INSTRUKCE: Odpověz POUZE přímou řečí postavy. "
    "Nikdy nepiš své jméno na začátek. Nikdy nepoužívej závorky ani popisy akcí. "
    "Pokud porušíš toto pravidlo, hra selže."
)

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY must be set")

# Database setup with retry logic
Base = declarative_base()

def retry_connect_db(max_retries: int = 10, wait_seconds: int = 2) -> str:
    """Retry database connection with exponential backoff"""
    for attempt in range(max_retries):
        try:
            engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                echo=False,
                connect_args={"timeout": 5}
            )
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            print(f"✓ Databáze připojena na {attempt + 1}. pokusu")
            return DATABASE_URL
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"✗ Pokus {attempt + 1}/{max_retries} selhal: {e}")
                print(f"  Čekání {wait_seconds}s...")
                time.sleep(wait_seconds)
            else:
                print(f"✗ Připojení k databázi selhalo po {max_retries} pokusech")
                raise RuntimeError(f"Database connection failed: {e}")
    return DATABASE_URL

# Connect to database
db_url = retry_connect_db()
engine = create_engine(db_url, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Suspect(Base):
    __tablename__ = "suspects"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    charakter = Column(Text, nullable=False)
    tajná_informace = Column(Text, nullable=False)
    pravidla = Column(Text, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True)
    sender = Column(String)  # "user" or suspect id
    content = Column(Text)
    timestamp = Column(String)


# Create tables
Base.metadata.create_all(bind=engine)

# Load prompts from JSON
prompts_path = Path(__file__).parent / "static" / "prompts.json"
if not prompts_path.exists():
    raise FileNotFoundError("prompts.json not found")

with prompts_path.open("r", encoding="utf-8") as f:
    suspects_data = json.load(f)

# Seed database if empty
def seed_database():
    """Seed database with initial suspect data if empty"""
    db = SessionLocal()
    try:
        existing = db.query(Suspect).count()
        if existing == 0:
            print("Seeding database with suspects...")
            for suspect_data in suspects_data:
                suspect = Suspect(
                    id=suspect_data["id"],
                    name=suspect_data["name"],
                    role=suspect_data["role"],
                    charakter=suspect_data["charakter"],
                    tajná_informace=suspect_data["tajná_informace"],
                    pravidla=suspect_data.get("pravidla", "")
                )
                db.add(suspect)
            db.commit()
            print(f"✓ Databáze oseeena - {len(suspects_data)} podezřelých vloženo")
        else:
            print(f"✓ Databáze již obsahuje {existing} podezřelých")
    except Exception as e:
        print(f"✗ Chyba při seedování: {e}")
        db.rollback()
        raise
    finally:
        db.close()

# Seed on startup
seed_database()

suspects_by_id = {suspect["id"]: suspect for suspect in suspects_data}
hidden_murderer_id = "2"

# FastAPI application
app = FastAPI(title="Nekonečná detektivka")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def build_system_prompt(suspect: Dict[str, Any]) -> str:
    return (
        "Jsi podezřelý v případu 'Nekonečná detektivka'. "
        f"Jmenuješ se {suspect['name']} a tvá role je {suspect['role']}. "
        f"Charakterizují tě tato slova: {suspect['charakter']}. "
        f"Tvá tajná informace je: {suspect['tajná_informace']} "
        "Odpovídej jako postava a podílej se na chatové výměně s hráčem."
    )


async def query_openai(messages: List[Dict[str, str]]) -> str:
    """Query OpenAI API with retry and timeout handling"""
    full_messages = list(messages) + [{"role": "system", "content": STRATEGIC_INSTRUCTION}]
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": full_messages,
        "temperature": 0.7,
        "max_tokens": 400,
    }
    
    async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        data = response.json()

    choice = data.get("choices", [{}])[0].get("message", {})
    return choice.get("content", "Omlouvám se, došlo k chybě při zpracování odpovědi.")


class ChatRequest(BaseModel):
    session_id: str
    suspect_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
    suspect: Dict[str, Any]


@app.on_event("startup")
async def startup():
    print(f"✓ Aplikace spuštěna na portu {PORT}")
    print(f"✓ OpenAI API: {OPENAI_BASE_URL}")
    print(f"✓ Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'local'}")


@app.get("/health")
async def health():
    return {"status": "ok", "port": PORT}


@app.post("/api/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    db = SessionLocal()
    try:
        # Get suspect info from DB
        suspect_record = db.query(Suspect).filter(
            Suspect.id == request.suspect_id
        ).first()
        
        if not suspect_record:
            raise HTTPException(status_code=404, detail="Suspect not found")
        
        suspect_data = {
            "id": suspect_record.id,
            "name": suspect_record.name,
            "role": suspect_record.role,
            "charakter": suspect_record.charakter,
            "tajná_informace": suspect_record.tajná_informace,
        }
        
        # Build conversation context
        messages = [
            {"role": "system", "content": build_system_prompt(suspect_data)},
            {"role": "user", "content": request.message}
        ]
        
        # Query AI
        response = await query_openai(messages)
        
        return ChatResponse(
            response=response,
            suspect=suspect_data
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/api/suspects")
async def get_suspects():
    db = SessionLocal()
    try:
        suspects = db.query(Suspect).all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "role": s.role,
                "charakter": s.charakter,
            }
            for s in suspects
        ]
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)



