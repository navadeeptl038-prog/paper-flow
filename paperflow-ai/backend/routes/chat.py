"""Chat and conversation routes for PaperFlow AI."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from auth.authorization import require_user
from models.search import (
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    InformationQueryRequest,
    MessageCreate,
    MessageResponse,
)
from models.user import AuthenticatedUser
from services import intent_service
from services.rag_service import execute_information_query
from services.supabase_client import get_supabase_client
from storage import document_repository

logger = logging.getLogger("paperflow.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])
_bearer = HTTPBearer(auto_error=False)

_mem_conversations: dict[str, dict[str, Any]] = {}


class ChatQueryRequest(BaseModel):
    """Minimal body for a direct chat query."""

    query: str = Field(..., min_length=1, max_length=2000)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation_key(user_id: str) -> dict[str, Any]:
    return _mem_conversations.setdefault(user_id, {})


def _get_conversation_for_user(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    return _conversation_key(user_id).get(conversation_id)


def generate_short_title(query: str) -> str:
    """Create a short, human-readable conversation title from a query."""
    words = [part for part in (query or "").strip().split() if part][:5]
    if not words:
        return "New chat"
    title = " ".join(words)
    if len(title) > 40:
        title = title[:37].rstrip() + "..."
    return title


def _get_client_with_auth(credentials: HTTPAuthorizationCredentials | None):
    """Return a Supabase client when available; otherwise use in-memory fallback storage."""
    if credentials is None:
        return None
    try:
        return get_supabase_client()
    except Exception as exc:  # pragma: no cover - fallback path
        logger.debug("Supabase unavailable for chat route: %s", exc)
        return
        None


def _message_to_response(message: dict[str, Any]) -> MessageResponse:
    return MessageResponse(
        id=str(message["id"]),
        conversation_id=str(message["conversation_id"]),
        role=str(message.get("role", "user")),
        content=str(message.get("content", "")),
        created_at=message.get("created_at") or _now(),
        sources=message.get("sources") or None,
    )


def _conversation_to_response(conversation: dict[str, Any]) -> ConversationResponse:
    messages = conversation.get("messages") or []
    last_message = messages[-1]["content"] if messages else None
    return ConversationResponse(
        id=str(conversation["id"]),
        owner_id=str(conversation["owner_id"]),
        title=str(conversation.get("title") or "New chat"),
        created_at=conversation.get("created_at") or _now(),
        updated_at=conversation.get("updated_at") or _now(),
        last_message=last_message,
    )


async def _append_message_to_conv(
    conv_id: str,
    user_id: str,
    role: str,
    content: str,
    credentials: HTTPAuthorizationCredentials | None,
    sources: list[dict[str, Any]] | None = None,
) -> MessageResponse:
    """Persist a message in the in-memory conversation store; falls back to Supabase when configured."""
    conversation = _get_conversation_for_user(user_id, conv_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    message = {
        "id": str(uuid.uuid4()),
        "conversation_id": conv_id,
        "role": role,
        "content": content,
        "created_at": _now(),
        "sources": sources or [],
    }
    conversation.setdefault("messages", []).append(message)
    conversation["updated_at"] = message["created_at"]

    client = _get_client_with_auth(credentials)
    if client is not None:
        try:
            client.table("messages").insert({
                "id": message["id"],
                "conversation_id": conv_id,
                "owner_id": user_id,
                "role": role,
                "content": content,
                "sources": sources or [],
            }).execute()
        except Exception as exc:  # pragma: no cover - optional backend persistence
            logger.warning("Supabase message persistence failed: %s", exc)

    return _message_to_response(message)


async def _process_chat_query(
    request: InformationQueryRequest,
    user_id: str,
    token: str | None,
):
    """Run the PaperFlow AI information query pipeline."""
    return await execute_information_query(
        request=request,
        user_id=user_id,
        token=token,
    )


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="List conversations",
)
async def list_conversations(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[ConversationResponse]:
    """Return all conversations owned by the authenticated user."""
    del credentials
    conversations = _conversation_key(user.user_id)
    return [
        _conversation_to_response(conv)
        for conv in sorted(
            conversations.values(),
            key=lambda item: item.get("updated_at") or item.get("created_at") or _now(),
            reverse=True,
        )
    ]


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
    payload: ConversationCreate,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConversationResponse:
    """Create a new conversation for the authenticated user."""
    del credentials
    now = _now()
    conv_id = str(uuid.uuid4())
    title = (payload.title or "").strip() or "New chat"
    conversation = {
        "id": conv_id,
        "owner_id": user.user_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    _conversation_key(user.user_id)[conv_id] = conversation
    return _conversation_to_response(conversation)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get a single conversation",
)
async def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConversationDetailResponse:
    """Return one conversation plus its messages, enforcing owner isolation."""
    del credentials
    conversations = _conversation_key(user.user_id)
    conversation = conversations.get(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return ConversationDetailResponse(
        id=str(conversation["id"]),
        owner_id=str(conversation["owner_id"]),
        title=str(conversation.get("title") or "New chat"),
        created_at=conversation.get("created_at") or _now(),
        updated_at=conversation.get("updated_at") or _now(),
        messages=[_message_to_response(message) for message in (conversation.get("messages") or [])],
    )


@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete a conversation",
)
async def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Delete a user-owned conversation."""
    del credentials
    conversations = _conversation_key(user.user_id)
    if conversation_id not in conversations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    del conversations[conversation_id]
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send message to conversation",
)
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> MessageResponse:
    """Append a user message, auto-title the conversation, and return the AI answer."""
    conversation = _get_conversation_for_user(user.user_id, conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    user_query = (payload.content or "").strip()
    if not user_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty.",
        )

    user_message = await _append_message_to_conv(
        conv_id=conversation_id,
        user_id=user.user_id,
        role="user",
        content=user_query,
        credentials=credentials,
    )

    if len(conversation.get("messages") or []) <= 1:
        conversation["title"] = generate_short_title(user_query)

    token = credentials.credentials if credentials else None
    try:
        ai_result = await _process_chat_query(
            request=InformationQueryRequest(
                query=user_query,
                conversation_id=conversation_id,
            ),
            user_id=user.user_id,
            token=token,
        )
    except Exception as exc:  # pragma: no cover - route-level error handling
        logger.exception("PaperFlow AI pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PaperFlow AI could not process your message.",
        ) from exc

    await _append_message_to_conv(
        conv_id=conversation_id,
        user_id=user.user_id,
        role="assistant",
        content=ai_result.answer,
        sources=[
            source.model_dump() if hasattr(source, "model_dump") else source
            for source in (ai_result.sources or [])
        ],
        credentials=credentials,
    )
    return user_message


@router.post(
    "/query",
    summary="Run a direct document or information query",
)
async def chat_query(
    payload: ChatQueryRequest,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Answer a user question using the same document-aware intent and retrieval pipeline."""
    token = credentials.credentials if credentials else None
    query_text = payload.query.strip()

    intent_result = intent_service.detect_intent(query_text)
    matching_docs = document_repository.search_documents_by_keyword(
        owner_id=user.user_id,
        query=query_text,
        target_hint=intent_result.target_document_hint,
        token=token,
    )

    file_actions: list[dict[str, Any]] = []
    for doc in matching_docs:
        file_actions.append(
            {
                "document_id": doc.id,
                "filename": doc.original_filename,
                "view_url": f"/api/documents/{doc.id}/view",
                "download_url": f"/api/documents/{doc.id}/download",
                "action_type": "view",
                "source": doc.source,
            }
        )

    return {
        "query": query_text,
        "intent": intent_result.intent.value,
        "category": intent_result.category.value,
        "explicit_document_request": bool(intent_result.explicit_document_request),
        "target_document_hint": intent_result.target_document_hint,
        "found": bool(matching_docs),
        "count": len(matching_docs),
        "show_file_actions": bool(file_actions),
        "file_actions": file_actions,
        "message": (
            f"Found {len(matching_docs)} matching document(s)."
            if matching_docs
            else f"No document matching '{query_text}' found."
        ),
    }
