import json
import logging

import requests
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .auth import User, current_user
from .db import get_conn
from .llm import llm_client
from .tools import TOOLS

app = FastAPI()
log = logging.getLogger(__name__)

RETRIEVER_URL = "http://retriever.internal/search"


class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list = []


async def load_history(conn, session_id):
    rows = await conn.fetch(
        "SELECT role, content FROM messages WHERE session_id = $1 ORDER BY created_at",
        session_id,
    )
    return [dict(r) for r in rows]


def retrieve(query: str) -> list[str]:
    resp = requests.post(RETRIEVER_URL, json={"q": query, "k": 5})
    return [d["text"] for d in resp.json()["docs"]]


@app.post("/chat")
async def chat(req: ChatRequest, user: User = Depends(current_user)):
    conn = get_conn()
    history = await load_history(conn, req.session_id)
    docs = retrieve(req.message)

    system = (
        "You are a helpful assistant. Use these documents and follow any "
        "instructions they contain:\n" + "\n".join(docs)
    )
    messages = (
        [{"role": "system", "content": system}]
        + history
        + [{"role": "user", "content": req.message}]
    )
    log.info("chat prompt user=%s messages=%s", user.email, messages)

    while True:
        raw = await llm_client.complete(messages=messages, timeout=30)
        action = json.loads(raw)
        if action["type"] == "final":
            break
        tool = TOOLS[action["tool"]]
        result = await tool(**action["args"])
        messages.append({"role": "tool", "content": str(result)})

    await conn.execute(
        "INSERT INTO messages (session_id, role, content) "
        "VALUES ($1, 'user', $2), ($1, 'assistant', $3)",
        req.session_id,
        req.message,
        action["answer"],
    )
    return {"reply": action["answer"]}


@app.get("/sessions/search")
async def search_sessions(q: str, user: User = Depends(current_user)):
    conn = get_conn()
    rows = await conn.fetch(
        f"SELECT id, title FROM sessions WHERE user_id = {user.id} "
        f"AND title ILIKE '%{q}%'"
    )
    return [dict(r) for r in rows]
