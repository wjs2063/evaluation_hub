import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, AsyncIterator, Literal, cast
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, status
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20_000)]


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    thread_id: Annotated[str, Field(min_length=1, max_length=200)] = "default"
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


def checkpoint_database_url() -> str:
    if database_url := os.getenv("CHECKPOINT_DATABASE_URL"):
        return database_url
    values = {
        "server": os.getenv("POSTGRES_SERVER"),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "database": os.getenv("POSTGRES_DB"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "CHECKPOINT_DATABASE_URL or POSTGRES_* settings are not configured"
        )
    return (
        f"postgresql://{quote(cast(str, values['user']), safe='')}:"
        f"{quote(cast(str, values['password']), safe='')}@{values['server']}:"
        f"{values['port']}/{quote(cast(str, values['database']), safe='')}"
        "?sslmode=disable"
    )


async def call_model(state: MessagesState, config: RunnableConfig) -> MessagesState:
    messages: list[BaseMessage] = list(state["messages"])
    system_prompt = config.get("configurable", {}).get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip():
        messages.insert(0, SystemMessage(content=system_prompt))
    response = await chat_model().ainvoke(messages)
    return {"messages": [response]}


def build_graph(checkpointer: AsyncPostgresSaver) -> CompiledStateGraph:
    builder = StateGraph(MessagesState)
    builder.add_node("chat", call_model)
    builder.add_edge(START, "chat")
    return builder.compile(checkpointer=checkpointer)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_database_url()
    ) as checkpointer:
        await checkpointer.setup()
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="ChatOpenAI example server", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    graph = cast(CompiledStateGraph, app.state.graph)
    config: RunnableConfig = {
        "configurable": {
            "thread_id": request.thread_id,
            "system_prompt": request.system_prompt,
        }
    }
    try:
        snapshot = await graph.aget_state(config)
        messages: list[BaseMessage] = []
        if not snapshot.values.get("messages"):
            messages.extend(
                HumanMessage(content=message.content)
                if message.role == "user"
                else AIMessage(content=message.content)
                for message in request.history
            )
        messages.append(HumanMessage(content=request.message))
        result = await graph.ainvoke({"messages": messages}, config)
        response = result["messages"][-1]
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The chat request failed",
        ) from exc
    return ChatResponse(answer=response_text(response.content))
