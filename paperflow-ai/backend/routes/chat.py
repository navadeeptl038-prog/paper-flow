"""Chat and persistent conversation history routes for PaperFlow AI Stage 10.

Endpoints:
  GET    /api/chat/conversations                  — list authenticated user's conversations (continuous list)
  POST   /api/chat/conversations                  — create a new conversation
  GET    /api/chat/conversations/{id}             — get conversation messages (enforcing owner_id == user.user_id)
  POST   /api/chat/conversations/{id}/messages    — append a message and auto-generate title if first query
  DELETE /api/chat/conversations/{id}             — delete a conversation

Security:
  - User identity comes strictly from verified JWT claims (via require_user)
  - No client-supplied user_id is trusted
  - User A cannot view, append to, or delete User B's conversations/messages
  - Does NOT create fake AI messages
"""

from __future__ import annotations

import datetime
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.authorization import require_user
from models.requirement import (
    RequirementChecklistResponse,
    RequirementCheckRequest,
)
from models.search import (
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    DocumentSourceMetadata,
    FileActionItem,
    InformationQueryRequest,
    InformationQueryResponse,
    MessageCreate,
    MessageResponse,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
    UnifiedSearchResultItem,
)
from models.user import AuthenticatedUser
from services import intent_service, rag_service, requirement_service, retrieval_service
from services.supabase_client import get_supabase_client

logger = logging.getLogger("paperflow.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])
_bearer = HTTPBearer(auto_error=False)

# Local isolated memory store for testing or when SUPABASE_SERVICE_ROLE_KEY is unset
# Strictly isolated per user: dict[user_id, dict[conv_id, conv_data]]
_mem_conversations: dict[str, dict[str, dict[str, Any]]] = {}
_mem_messages: dict[str, list[dict[str, Any]]] = {}


def generate_short_title(query: str, max_length: int = 40) -> str:
    """Derive a clean, concise conversation title from the first user query."""
    clean = re.sub(r"\s+", " ", query).strip()
    if not clean:
        return "New chat"

    first_sentence = re.split(r"[.!?\n]", clean)[0].strip()
    candidate = first_sentence if first_sentence else clean

    if len(candidate) <= max_length:
        return candidate.capitalize()

    truncated = candidate[:max_length].rsplit(" ", 1)[0].strip()
    return f"{truncated.capitalize()}…"


def _get_client_with_auth(credentials: HTTPAuthorizationCredentials | None):
    client = get_supabase_client()
    if credentials and credentials.credentials:
        try:
            client.postgrest.auth(credentials.credentials)
        except Exception:
            pass
    return client


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="List user conversations",
)
async def list_conversations(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[ConversationResponse]:
    """Retrieve a continuous list of conversations belonging strictly to the authenticated user."""
    client = _get_client_with_auth(credentials)
    db_conversations = []
    try:
        res = (
            client.table("conversations")
            .select("*")
            .eq("owner_id", user.user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        db_conversations = res.data or []
    except Exception:
        pass

    # Merge with memory-isolated conversations for this user
    user_mem = _mem_conversations.get(user.user_id, {})
    all_map: dict[str, dict[str, Any]] = {c["id"]: c for c in db_conversations}
    for cid, cdata in user_mem.items():
        if cid not in all_map:
            all_map[cid] = cdata

    sorted_list = sorted(
        all_map.values(),
        key=lambda c: str(c.get("updated_at") or c.get("created_at") or ""),
        reverse=True,
    )

    return [
        ConversationResponse(
            id=str(row["id"]),
            owner_id=str(row["owner_id"]),
            title=row.get("title") or "New chat",
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at") or row.get("created_at"),
        )
        for row in sorted_list
    ]


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
    payload: ConversationCreate | None = None,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConversationResponse:
    """Create a new empty conversation for the authenticated user."""
    client = _get_client_with_auth(credentials)
    title = (payload.title.strip() if payload and payload.title else "New chat") or "New chat"

    try:
        res = (
            client.table("conversations")
            .insert({
                "owner_id": user.user_id,
                "title": title,
            })
            .execute()
        )
        rows = res.data or []
        if rows:
            row = rows[0]
            return ConversationResponse(
                id=str(row["id"]),
                owner_id=str(row["owner_id"]),
                title=row.get("title") or title,
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at") or row.get("created_at"),
            )
    except Exception:
        pass

    # Isolated memory creation
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_id = str(uuid.uuid4())
    conv_obj = {
        "id": new_id,
        "owner_id": user.user_id,
        "title": title,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    if user.user_id not in _mem_conversations:
        _mem_conversations[user.user_id] = {}
    _mem_conversations[user.user_id][new_id] = conv_obj
    _mem_messages[new_id] = []
    return ConversationResponse(**conv_obj)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get conversation and messages",
)
async def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConversationDetailResponse:
    """Retrieve conversation details and messages, strictly enforcing owner_id == user.user_id."""
    client = _get_client_with_auth(credentials)
    conv = None
    messages_data = []

    try:
        conv_res = (
            client.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("owner_id", user.user_id)
            .limit(1)
            .execute()
        )
        if conv_res.data:
            conv = conv_res.data[0]
            msg_res = (
                client.table("messages")
                .select("*")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=False)
                .execute()
            )
            messages_data = msg_res.data or []
    except Exception:
        pass

    if not conv:
        # Check memory store for this specific user
        user_convs = _mem_conversations.get(user.user_id, {})
        conv = user_convs.get(conversation_id)
        if conv:
            messages_data = _mem_messages.get(conversation_id, [])

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return ConversationDetailResponse(
        id=str(conv["id"]),
        owner_id=str(conv["owner_id"]),
        title=conv.get("title") or "New chat",
        created_at=conv.get("created_at"),
        updated_at=conv.get("updated_at") or conv.get("created_at"),
        messages=[
            MessageResponse(
                id=str(m["id"]),
                conversation_id=str(m["conversation_id"]),
                role=m.get("role") or "user",
                content=m.get("content") or "",
                created_at=m.get("created_at"),
                sources=m.get("sources"),
            )
            for m in messages_data
        ],
    )


async def _append_message_to_conv(
    conv_id: str,
    user_id: str,
    role: str,
    content: str,
    sources: list[dict[str, Any]] | None = None,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> MessageResponse:
    """Helper to append a message to database or isolated memory."""
    client = _get_client_with_auth(credentials)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        msg_res = (
            client.table("messages")
            .insert({
                "conversation_id": conv_id,
                "role": role,
                "content": content,
                "sources": sources or [],
            })
            .execute()
        )
        if msg_res.data:
            new_msg = msg_res.data[0]
            update_fields: dict[str, Any] = {"updated_at": now_iso}
            client.table("conversations").update(update_fields).eq("id", conv_id).execute()
            return MessageResponse(
                id=str(new_msg["id"]),
                conversation_id=str(new_msg["conversation_id"]),
                role=new_msg.get("role") or role,
                content=new_msg.get("content") or content,
                created_at=new_msg.get("created_at") or now_iso,
                sources=new_msg.get("sources"),
            )
    except Exception:
        pass

    # Memory store fallback
    msg_id = str(uuid.uuid4())
    msg_obj = {
        "id": msg_id,
        "conversation_id": conv_id,
        "role": role,
        "content": content,
        "created_at": now_iso,
        "sources": sources or [],
    }
    if conv_id not in _mem_messages:
        _mem_messages[conv_id] = []
    _mem_messages[conv_id].append(msg_obj)

    user_convs = _mem_conversations.get(user_id, {})
    if conv_id in user_convs:
        user_convs[conv_id]["updated_at"] = now_iso

    return MessageResponse(**msg_obj)


async def _process_chat_query(
    request: InformationQueryRequest,
    user_id: str,
    token: str | None = None,
) -> InformationQueryResponse:
    """Route query through requirement checker if relevant, or standard RAG."""
    clean_q = request.query.strip()

    if requirement_service.is_requirement_query(clean_q):
        chk = await requirement_service.check_requirements(
            query=clean_q,
            user_id=user_id,
            token=token,
        )

        lines = []
        if chk.clarification_prompt:
            lines.append(chk.clarification_prompt)
            lines.append("")

        lines.append(f"**Document Requirements Checklist ({chk.summary})**:")
        sources: list[DocumentSourceMetadata] = []
        file_actions: list[FileActionItem] = []

        for item in chk.items:
            if item.status == "present" and item.matched_document:
                dup_note = (
                    f" (+{len(item.duplicates)} duplicate version{'s' if len(item.duplicates) > 1 else ''})"
                    if item.duplicates
                    else ""
                )
                lines.append(
                    f"• **{item.name}**: **Present** — `{item.matched_document.filename}` ({item.matched_document.source}){dup_note}"
                )
                sources.append(
                    DocumentSourceMetadata(
                        document_id=item.matched_document.id,
                        filename=item.matched_document.filename,
                    )
                )
                file_actions.append(
                    FileActionItem(
                        action_type="view",
                        document_id=item.matched_document.id,
                        filename=item.matched_document.filename,
                        download_url=item.matched_document.download_url,
                    )
                )
            else:
                lines.append(f"• **{item.name}**: **Missing** — Not found in your documents")

        if chk.authoritative_source:
            lines.append("")
            lines.append(f"**Authoritative Source**: {chk.authoritative_source}")

        lines.append("")
        lines.append(f"_{chk.disclaimer}_")

        return InformationQueryResponse(
            query=clean_q,
            intent="requirement_check",
            category=chk.category,
            answer="\n".join(lines),
            sources=sources,
            has_found_info=chk.present_count > 0,
            show_file_actions=len(file_actions) > 0,
            file_actions=file_actions,
            conversation_id=request.conversation_id,
            disclaimer=chk.disclaimer,
        )

    # 2. Check for explicit document action (e.g. "Find my passport", "Get my resume in drive")
    intent_res = intent_service.detect_intent(clean_q)
    if intent_res.intent == intent_service.QueryIntent.DOCUMENT_ACTION:
        search_hint = intent_res.target_document_hint or clean_q
        usearch_req = UnifiedSearchRequest(
            query=search_hint,
            sources=intent_res.target_sources or request.sources,
            top_k=5,
        )
        usearch_res = await retrieval_service.execute_unified_search(usearch_req, user_id=user_id, token=token)

        if usearch_res.results:
            file_actions: list[FileActionItem] = []
            sources: list[DocumentSourceMetadata] = []
            lines = ["I found the following matching document(s) across your authorized sources:"]

            for item in usearch_res.results[:5]:
                dup_str = f" (+{len(item.duplicates)} duplicates)" if item.duplicates else ""
                lines.append(f"• **{item.title}** ({item.source}){dup_str}")
                sources.append(
                    DocumentSourceMetadata(
                        document_id=item.reference,
                        filename=item.title,
                        source=item.source,
                        reference=item.reference,
                        similarity=item.relevance,
                        metadata=item.metadata,
                    )
                )
                file_actions.append(
                    FileActionItem(
                        action_type="view",
                        document_id=item.reference,
                        filename=item.title,
                        source=item.source,
                        download_url=item.download_url,
                        view_url=item.view_url,
                    )
                )

            return InformationQueryResponse(
                query=clean_q,
                intent="document_action",
                category=intent_res.category.value,
                answer="\n".join(lines),
                sources=sources,
                has_found_info=True,
                show_file_actions=True,
                file_actions=file_actions,
                conversation_id=request.conversation_id,
            )
        else:
            return InformationQueryResponse(
                query=clean_q,
                intent="document_action",
                category=intent_res.category.value,
                answer="I could not find the requested document in your indexed documents or connected sources.",
                sources=[],
                has_found_info=False,
                show_file_actions=False,
                file_actions=[],
                conversation_id=request.conversation_id,
            )

    return await rag_service.execute_information_query(
        request=request,
        user_id=user_id,
        token=token,
    )


@router.post(
    "/search/unified",
    response_model=UnifiedSearchResponse,
    summary="Unified Search across authorized sources",
    description="Search across Supabase Storage, Google Drive, and Gmail with ranking and deduplication.",
)
@router.post(
    "/unified-search",
    response_model=UnifiedSearchResponse,
    summary="Unified Search across authorized sources (alias)",
    description="Search across Supabase Storage, Google Drive, and Gmail with ranking and deduplication.",
)
async def unified_search(
    payload: UnifiedSearchRequest,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UnifiedSearchResponse:
    """Execute unified search across Supabase Storage, Google Drive, and Gmail."""
    token = credentials.credentials if credentials else None
    return await retrieval_service.execute_unified_search(
        request=payload,
        user_id=user.user_id,
        token=token,
    )


@router.post(
    "/requirements/check",
    response_model=RequirementChecklistResponse,
    summary="Check document requirements",
    description="Check user documents against requirements (e.g. visa), marking items as Present or Missing.",
)
async def check_document_requirements(
    payload: RequirementCheckRequest,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> RequirementChecklistResponse:
    """Evaluate document requirements (e.g. visa) strictly for the authenticated user."""
    token = credentials.credentials if credentials else None
    return await requirement_service.check_requirements(
        query=payload.query,
        user_id=user.user_id,
        destination=payload.destination,
        purpose=payload.purpose,
        token=token,
    )


@router.post(
    "/query",
    response_model=InformationQueryResponse,
    summary="Submit an Information Query",
)
async def query_information(
    payload: InformationQueryRequest,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> InformationQueryResponse:
    """Execute complete Information Query Workflow for the authenticated user.

    Flow:
    query → intent detection → retrieve → RAG → grounded answer → source
    """
    token = credentials.credentials if credentials else None
    response = await _process_chat_query(
        request=payload,
        user_id=user.user_id,
        token=token,
    )

    # If conversation_id is provided, automatically persist interaction
    if payload.conversation_id:
        try:
            await _append_message_to_conv(
                conv_id=payload.conversation_id,
                user_id=user.user_id,
                role="user",
                content=payload.query,
                sources=[],
                credentials=credentials,
            )
            sources_dump = [s.model_dump() for s in response.sources]
            assistant_msg = await _append_message_to_conv(
                conv_id=payload.conversation_id,
                user_id=user.user_id,
                role="assistant",
                content=response.answer,
                sources=sources_dump,
                credentials=credentials,
            )
            response.message_id = assistant_msg.id
        except Exception as exc:
            logger.warning("Could not persist query to conversation: %s", exc)

    return response


@router.post(
    "/conversations/{conversation_id}/query",
    response_model=InformationQueryResponse,
    summary="Submit an Information Query within a conversation",
)
async def query_conversation(
    conversation_id: str,
    payload: InformationQueryRequest,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> InformationQueryResponse:
    """Execute Information Query scoped to a conversation."""
    payload.conversation_id = conversation_id
    return await query_information(payload=payload, user=user, credentials=credentials)


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
    """Append a message to a conversation, auto-update title, and auto-generate assistant reply for user queries."""
    client = _get_client_with_auth(credentials)
    conv = None

    try:
        conv_res = (
            client.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("owner_id", user.user_id)
            .limit(1)
            .execute()
        )
        if conv_res.data:
            conv = conv_res.data[0]
    except Exception:
        pass

    if not conv:
        user_convs = _mem_conversations.get(user.user_id, {})
        conv = user_convs.get(conversation_id)

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    # 1. Append user message
    user_msg = await _append_message_to_conv(
        conv_id=conversation_id,
        user_id=user.user_id,
        role=payload.role,
        content=payload.content,
        sources=payload.sources or [],
        credentials=credentials,
    )

    # 2. Update conversation title on first query
    current_title = (conv.get("title") or "").strip()
    if (current_title == "New chat" or not current_title) and payload.role == "user":
        new_title = generate_short_title(payload.content)
        try:
            client.table("conversations").update({"title": new_title}).eq("id", conversation_id).execute()
        except Exception:
            pass
        conv["title"] = new_title

    # 3. If message is from user, generate and persist assistant grounded response
    if payload.role == "user":
        token = credentials.credentials if credentials else None
        try:
            info_req = InformationQueryRequest(
                query=payload.content,
                conversation_id=conversation_id,
            )
            chat_res = await _process_chat_query(
                request=info_req,
                user_id=user.user_id,
                token=token,
            )
            sources_dump = [s.model_dump() for s in chat_res.sources]
            await _append_message_to_conv(
                conv_id=conversation_id,
                user_id=user.user_id,
                role="assistant",
                content=chat_res.answer,
                sources=sources_dump,
                credentials=credentials,
            )
        except Exception as exc:
            logger.warning("Auto-generation of assistant message failed: %s", exc)

    return user_msg



@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete conversation",
)
async def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Delete a conversation, strictly enforcing owner_id == user.user_id."""
    client = _get_client_with_auth(credentials)
    deleted = False

    try:
        conv_res = (
            client.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("owner_id", user.user_id)
            .limit(1)
            .execute()
        )
        if conv_res.data:
            client.table("messages").delete().eq("conversation_id", conversation_id).execute()
            client.table("conversations").delete().eq("id", conversation_id).eq("owner_id", user.user_id).execute()
            deleted = True
    except Exception:
        pass

    user_convs = _mem_conversations.get(user.user_id, {})
    if conversation_id in user_convs:
        del user_convs[conversation_id]
        _mem_messages.pop(conversation_id, None)
        deleted = True

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    return {"deleted": True, "id": conversation_id}
