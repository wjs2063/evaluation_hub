import os
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20_000)]


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    system_prompt: str | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=100)


class ChatResponse(BaseModel):
    answer: str


@lru_cache
def chat_model() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return ChatOpenAI(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    )


def response_text(content: str | list[str | dict[str, object]]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        item if isinstance(item, str) else str(item.get("text", ""))
        for item in content
    )


app = FastAPI(title="ChatOpenAI example server")


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    messages = [
        HumanMessage(content=message.content)
        if message.role == "user"
        else AIMessage(content=message.content)
        for message in request.history
    ]
    messages.append(HumanMessage(content=request.message))
    if request.system_prompt:
        messages.insert(0, SystemMessage(content=request.system_prompt))
    try:
        response = await chat_model().ainvoke(messages)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The OpenAI request failed",
        ) from exc
    return ChatResponse(answer=response_text(response.content))
