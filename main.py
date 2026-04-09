import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.future import select

class Base(DeclarativeBase):
    pass

class Suspect(Base):
    __tablename__ = "suspects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    charakter: Mapped[str] = mapped_column(Text)
    tajna_informace: Mapped[str] = mapped_column(Text)
    pravidla: Mapped[str] = mapped_column(Text)

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # user or assistant
    content: Mapped[str] = mapped_column(Text)

app = FastAPI(title="Nekonečná detektivka")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup with retry

# Always enforce asyncpg driver in DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set")
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    # Try to auto-correct if user forgot the prefix
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

async_engine = None
async_session = None

async def init_db():
    global async_engine, async_session
    last_exception = None
    for attempt in range(10):
        try:
            async_engine = create_async_engine(DATABASE_URL, echo=False)
            async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("PostgreSQL is ready!")
            return
        except Exception as e:
            last_exception = e
            print(f"Database connection attempt {attempt + 1} failed: {repr(e)}")
            if attempt < 9:
                time.sleep(2)
    print("Failed to connect to PostgreSQL after 10 attempts. Last error:", repr(last_exception))
    # Do not raise, just log and let FastAPI continue (so logs are visible)

# Run init_db on startup
@app.on_event("startup")
async def startup_event():
    await init_db()
    await seed_suspects()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_BASE_URL", "https://kurim.ithope.eu/v1")
MODEL = "gemma3:27b"
REDIS_URL = os.getenv("REDIS_URL", "redis://cache:6379/0")
SESSION_TTL = 24 * 60 * 60
MAX_HISTORY_MESSAGES = 20
STRATEGIC_INSTRUCTION = (
    "STRATEGICKÁ INSTRUKCE: Odpověz POUZE přímou řečí postavy. "
    "Nikdy nepiš své jméno na začátek. Nikdy nepoužívej závorky ani popisy akcí. "
    "Pokud porušíš toto pravidlo, hra selže."
)

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY must be set")

prompts_path = Path(__file__).parent / "static" / "prompts.json"
if not prompts_path.exists():
    raise FileNotFoundError("prompts.json not found")

with prompts_path.open("r", encoding="utf-8") as f:
    suspects_data = json.load(f)

hidden_murderer_id = "2"

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
app.mount("/static", StaticFiles(directory="."), name="static")

async def seed_suspects():
    async with async_session() as session:
        result = await session.execute(select(Suspect))
        existing = result.scalars().all()
        if not existing:
            for suspect in suspects_data:
                new_suspect = Suspect(
                    id=suspect["id"],
                    name=suspect["name"],
                    role=suspect["role"],
                    charakter=suspect["charakter"],
                    tajna_informace=suspect["tajná_informace"],
                    pravidla=suspect["pravidla"]
                )
                session.add(new_suspect)
            await session.commit()
            print("Suspects seeded successfully")

async def get_suspect_from_db(character_id: str) -> Optional[Dict[str, str]]:
    async with async_session() as session:
        result = await session.execute(select(Suspect).where(Suspect.id == character_id))
        suspect = result.scalar_one_or_none()
        if suspect:
            return {
                "id": suspect.id,
                "name": suspect.name,
                "role": suspect.role,
                "charakter": suspect.charakter,
                "tajná_informace": suspect.tajna_informace,
                "pravidla": suspect.pravidla
            }
        return None

async def get_history_from_db(session_id: str) -> List[Dict[str, str]]:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.id)
        )
        messages = result.scalars().all()
        return [{"role": msg.role, "content": msg.content} for msg in messages]

async def save_message_to_db(session_id: str, role: str, content: str):
    async with async_session() as session:
        message = Message(session_id=session_id, role=role, content=content)
        session.add(message)
        await session.commit()


def build_system_prompt(suspect: Dict[str, str]) -> str:
    return (
        "Jsi podezřelý v případu 'Nekonečná detektivka'. "
        f"Jmenuješ se {suspect['name']} a tvá role je {suspect['role']}. "
        f"Charakterizují tě tato slova: {suspect['charakter']}. "
        f"Tvá tajná informace je: {suspect['tajná_informace']} "
        "Odpovídej jako postava a podílej se na chatové výměně s hráčem."
    )


async def query_openai(messages: List[Dict[str, str]]) -> str:
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
        response = await client.post(f"{OPENAI_API_BASE}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    choice = data.get("choices", [{}])[0].get("message", {})
    return choice.get("content", "Omlouvám se, došlo k chybě při zpracování odpovědi.")


def sanitize_reply(text: str) -> str:
    text = re.sub(r"\(.*?\)", "", text)
    text = text.strip()
    text = re.sub(
        r"^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝ][a-záčďéěíňóřšťúůý]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝ][a-záčďéěíňóřšťúůý]+)*\s*:\s*",
        "",
        text,
    )
    return text.strip()


class ChatRequest(BaseModel):
    character_id: str
    message: str
    session_id: Optional[str] = None


class AccuseRequest(BaseModel):
    character_id: str
    accusation: str
    session_id: Optional[str] = None


def get_suspect(character_id: str) -> Dict[str, str]:
    suspect = asyncio.run(get_suspect_from_db(character_id))
    if suspect is None:
        raise HTTPException(status_code=404, detail="Postava nenalezena")
    return suspect


@app.get("/")
async def root():
    return FileResponse("index.html")


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    suspect = get_suspect(request.character_id)
    session_id = request.session_id or f"session-{request.character_id}"

    history = await get_history_from_db(session_id)
    history.append({"role": "user", "content": request.message})

    messages = [{"role": "system", "content": build_system_prompt(suspect)}] + history
    assistant_reply = await query_openai(messages)
    assistant_reply = sanitize_reply(assistant_reply)
    history.append({"role": "assistant", "content": assistant_reply})
    history = history[-MAX_HISTORY_MESSAGES:]

    # Save to DB
    await save_message_to_db(session_id, "user", request.message)
    await save_message_to_db(session_id, "assistant", assistant_reply)

    return {"reply": assistant_reply, "session_id": session_id}


@app.post("/accuse")
async def accuse(request: AccuseRequest) -> Dict[str, Any]:
    suspect = get_suspect(request.character_id)
    session_id = request.session_id or f"session-{request.character_id}"
    history = await get_history_from_db(session_id)

    prompt = [
        {
            "role": "system",
            "content": (
                "Jsi nestranný soudce v detektivním příběhu. Hodnoť obvinění hráče z hlediska pravdy. "
                "Máš k dispozici seznam podezřelých a víš, kdo je skutečný vrah."
            ),
        },
        {
            "role": "user",
            "content": (
                "Hráč obvinil postavu: "
                f"{suspect['name']} (id {suspect['id']}) s rolí {suspect['role']}. "
                f"Jejich charakter: {suspect['charakter']}. Tajná informace: {suspect['tajná_informace']}. "
                "Tvé tajné vědění: skutečný vrah je postava s id 2. "
                "Napiš stručný verdikt, jestli hráč vyhrál nebo ne, a proč."
            ),
        },
    ]
    verdict = await query_openai(prompt)
    won = request.character_id == hidden_murderer_id
    return {"verdict": verdict.strip(), "won": won, "accused": suspect["name"]}



