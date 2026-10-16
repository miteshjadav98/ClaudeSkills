import logging

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .auth import User, current_user
from .db import get_conn
from .llm import llm_client

app = FastAPI()
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
async def chat(req: ChatRequest, user: User = Depends(current_user)):
    conn = get_conn()
    row = await conn.fetchrow(
        "SELECT id FROM sessions WHERE id = $1 AND user_id = $2",
        req.session_id,
        user.id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")

    reply = await llm_client.complete(
        messages=[{"role": "user", "content": req.message}],
        timeout=30,
    )
    log.info("chat completed session=%s", req.session_id)
    return {"reply": reply}
