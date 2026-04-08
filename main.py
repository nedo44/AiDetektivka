import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Nekonečná detektivka")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    suspects = json.load(f)

suspects_by_id = {suspect["id"]: suspect for suspect in suspects}
hidden_murderer_id = "2"

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


def make_history_key(session_id: str) -> str:
    return f"chat_history:{session_id}"


async def get_history(session_id: str) -> List[Dict[str, str]]:
    raw = await redis_client.get(make_history_key(session_id))
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


async def save_history(session_id: str, history: List[Dict[str, str]]) -> None:
    await redis_client.set(make_history_key(session_id), json.dumps(history, ensure_ascii=False), ex=SESSION_TTL)


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
    suspect = suspects_by_id.get(character_id)
    if suspect is None:
        raise HTTPException(status_code=404, detail="Postava nenalezena")
    return suspect


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    suspect = get_suspect(request.character_id)
    session_id = request.session_id or f"session-{request.character_id}"

    history = await get_history(session_id)
    history.append({"role": "user", "content": request.message})

    messages = [{"role": "system", "content": build_system_prompt(suspect)}] + history
    assistant_reply = await query_openai(messages)
    assistant_reply = sanitize_reply(assistant_reply)
    history.append({"role": "assistant", "content": assistant_reply})
    history = history[-MAX_HISTORY_MESSAGES:]
    await save_history(session_id, history)

    return {"reply": assistant_reply, "session_id": session_id}


@app.post("/accuse")
async def accuse(request: AccuseRequest) -> Dict[str, Any]:
    suspect = get_suspect(request.character_id)
    session_id = request.session_id or f"session-{request.character_id}"
    history = await get_history(session_id)

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



