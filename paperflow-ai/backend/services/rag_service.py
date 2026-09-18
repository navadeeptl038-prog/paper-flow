"""RAG (Retrieval-Augmented Generation) and Information Query service for PaperFlow AI.

FLOW:
query
→ intent detection
→ retrieve
→ RAG
→ grounded answer
→ source

Key Guarantees:
- Answer strictly grounded in retrieved evidence.
- Do NOT show View/Download automatically.
- Only show original-file actions if the user explicitly asks for the document.
- For study PDFs: retrieve relevant study content → answer → source.
- If information isn't found: say that it wasn't found. Never guess.
- Handle ambiguous and unsupported queries gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from pydantic import BaseModel, Field

from models.search import (
    DocumentSourceMetadata,
    FileActionItem,
    InformationQueryRequest,
    InformationQueryResponse,
)
from services import intent_service, llm_service, retrieval_service
from services.intent_service import IntentResult, QueryCategory, QueryIntent
from services.llm_service import (
    LLMAuthError,
    LLMError,
    LLMQuotaExceededError,
    LLMTimeoutError,
)
from services.retrieval_service import SourceReference

logger = logging.getLogger("paperflow.rag_service")

RAG_DISCLAIMER = (
    "Answers are grounded strictly in your retrieved documents. "
    "While RAG significantly reduces inaccuracies, it does not eliminate hallucinations completely."
)


# ---------------------------------------------------------------------------
# Legacy Models (Maintained for backward-compatibility)
# ---------------------------------------------------------------------------


class RAGRequest(BaseModel):
    """Request payload for answering a question with RAG."""

    query: str = Field(..., min_length=1, description="Question to answer using document knowledge")
    document_id: str | None = Field(None, description="Optional document UUID constraint")
    top_k: int = Field(default=5, ge=1, le=20, description="Max context chunks to retrieve")
    similarity_threshold: float = Field(
        default=0.25, ge=0.0, le=1.0, description="Minimum similarity score for relevant chunks"
    )


class RAGResponse(BaseModel):
    """Grounded answer with source citations and diagnostic metadata."""

    query: str
    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    has_context: bool
    grounded: bool
    disclaimer: str = RAG_DISCLAIMER


# ---------------------------------------------------------------------------
# Stage 15 — Information Query Workflow
# ---------------------------------------------------------------------------


async def execute_information_query(
    request: InformationQueryRequest,
    user_id: str,
    token: str | None = None,
) -> InformationQueryResponse:
    """Execute complete Information Query Workflow for an authenticated user.

    Flow:
    query → intent detection → retrieve → RAG → grounded answer → source

    Rules:
    - Return answer + source document + useful page/source metadata.
    - Do NOT show View/Download automatically.
    - Only show original-file actions if user explicitly asks for the document.
    - For study PDFs: retrieve relevant study content → answer → source.
    - If information isn't found: state clearly that it was not found. Never guess.

    Args:
        request: InformationQueryRequest with query, filters, and limits.
        user_id: Authenticated user UUID (strict isolation).
        token: User auth token.

    Returns:
        InformationQueryResponse with answer, metadata, and conditional actions.
    """
    clean_query = request.query.strip()
    if not clean_query:
        return InformationQueryResponse(
            query=request.query,
            intent=QueryIntent.AMBIGUOUS_QUERY.value,
            category=QueryCategory.UNSPECIFIED.value,
            answer="Your query is empty. Please enter a question about your documents.",
            sources=[],
            has_found_info=False,
            show_file_actions=False,
            file_actions=[],
            conversation_id=request.conversation_id,
        )

    # 1. Intent Detection
    intent_result = intent_service.detect_intent(clean_query)
    logger.info(
        "Detected intent '%s' (category: %s) for query: '%s'",
        intent_result.intent.value,
        intent_result.category.value,
        clean_query[:60],
    )

    # 2. Handle Ambiguous Queries: Prompt user for clarification without guessing
    if intent_result.intent == QueryIntent.AMBIGUOUS_QUERY:
        return InformationQueryResponse(
            query=clean_query,
            intent=intent_result.intent.value,
            category=intent_result.category.value,
            answer=intent_result.clarification_message or (
                "Your query is too ambiguous. Could you please specify which document, "
                "chapter, or specific detail you are looking for?"
            ),
            sources=[],
            has_found_info=False,
            show_file_actions=False,
            file_actions=[],
            conversation_id=request.conversation_id,
        )

    # 3. Handle Unsupported Queries: Decline gracefully
    if intent_result.intent == QueryIntent.UNSUPPORTED_QUERY:
        return InformationQueryResponse(
            query=clean_query,
            intent=intent_result.intent.value,
            category=intent_result.category.value,
            answer=intent_result.clarification_message or (
                "PaperFlow AI is designed to search, retrieve, and summarize information "
                "from your uploaded documents. External tasks such as live weather, "
                "external bookings, or web automation are not supported."
            ),
            sources=[],
            has_found_info=False,
            show_file_actions=False,
            file_actions=[],
            conversation_id=request.conversation_id,
        )

    # 4. Handle Greeting
    if intent_result.intent == QueryIntent.GREETING:
        return InformationQueryResponse(
            query=clean_query,
            intent=intent_result.intent.value,
            category=intent_result.category.value,
            answer=(
                "Hello! I am PaperFlow AI. You can ask me questions about your uploaded personal "
                "records (such as passport, Aadhaar, IDs), study materials, notes, or policies, "
                "and I will provide accurate answers grounded in your documents."
            ),
            sources=[],
            has_found_info=True,
            show_file_actions=False,
            file_actions=[],
            conversation_id=request.conversation_id,
        )

    # For study material or broad summary queries, use adaptive threshold
    effective_threshold = request.similarity_threshold
    if intent_result.category == QueryCategory.STUDY_MATERIAL and request.similarity_threshold == 0.25:
        effective_threshold = 0.10

    # 5. Retrieve Relevant Chunks (scoped strictly to user_id)
    retrieval = await retrieval_service.retrieve_context(
        query=clean_query,
        user_id=user_id,
        top_k=request.top_k,
        similarity_threshold=effective_threshold,
        document_id=request.document_id,
        target_document_hint=intent_result.target_document_hint,
        token=token,
    )


    # Convert retrieval sources to DocumentSourceMetadata
    source_metadata_list: list[DocumentSourceMetadata] = [
        DocumentSourceMetadata(
            document_id=src.document_id,
            filename=src.filename,
            page_number=src.page_number,
            chunk_index=src.chunk_index,
            similarity=src.similarity,
        )
        for src in retrieval.source_references
    ]

    # 6. Handle Missing Information: State clearly that info was not found. NEVER GUESS.
    if not retrieval.has_relevant_context or not retrieval.grounded_context:
        topic_desc = f" regarding '{clean_query}'" if len(clean_query) < 40 else ""
        return InformationQueryResponse(
            query=clean_query,
            intent=intent_result.intent.value,
            category=intent_result.category.value,
            answer=(
                f"I could not find any relevant information{topic_desc} in your uploaded documents. "
                "Please make sure the relevant document has been uploaded and processed."
            ),
            sources=[],
            has_found_info=False,
            show_file_actions=False,
            file_actions=[],
            conversation_id=request.conversation_id,
        )

    # 7. Determine File Actions:
    # RULE: Do NOT show View/Download automatically.
    # Only show original-file actions if the user explicitly asks for the document.
    show_file_actions = intent_result.explicit_document_request
    file_actions: list[FileActionItem] = []
    if show_file_actions and source_metadata_list:
        seen_doc_ids: set[str] = set()
        for src in source_metadata_list:
            if src.document_id not in seen_doc_ids:
                seen_doc_ids.add(src.document_id)
                file_actions.append(
                    FileActionItem(
                        action_type="view",
                        document_id=src.document_id,
                        filename=src.filename,
                    )
                )
                file_actions.append(
                    FileActionItem(
                        action_type="download",
                        document_id=src.document_id,
                        filename=src.filename,
                    )
                )

    # 8. Call Gemini to synthesize grounded answer (with automatic backoff retry on temporary 429)
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            answer_text = await llm_service.generate_grounded_answer(
                prompt=clean_query,
                grounded_context=retrieval.grounded_context,
            )

            lower_ans = answer_text.lower()
            not_found_markers = [
                "cannot find",
                "could not find",
                "insufficient evidence",
                "no mention of",
                "no information regarding",
                "not found in",
                "does not contain",
                "no vehicle registration",
            ]
            has_found_info = not any(marker in lower_ans for marker in not_found_markers)

            return InformationQueryResponse(
                query=clean_query,
                intent=intent_result.intent.value,
                category=intent_result.category.value,
                answer=answer_text,
                sources=source_metadata_list if has_found_info else [],
                has_found_info=has_found_info,
                show_file_actions=show_file_actions if has_found_info else False,
                file_actions=file_actions if has_found_info else [],
                conversation_id=request.conversation_id,
            )


        except LLMQuotaExceededError as exc:
            if attempt < max_retries:
                logger.info(
                    "Rate limited by Gemini, retrying after backoff (attempt %d/%d)...",
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(2.5)
                continue
            logger.warning("LLM quota exceeded during query: %s", exc)
            return InformationQueryResponse(
                query=clean_query,
                intent=intent_result.intent.value,
                category=intent_result.category.value,
                answer="The AI service is temporarily experiencing high demand. Please wait a moment and try again.",
                sources=source_metadata_list,
                has_found_info=True,
                show_file_actions=show_file_actions,
                file_actions=file_actions,
                conversation_id=request.conversation_id,
            )

        except LLMTimeoutError as exc:
            logger.warning("LLM request timed out during query: %s", exc)
            return InformationQueryResponse(
                query=clean_query,
                intent=intent_result.intent.value,
                category=intent_result.category.value,
                answer="The AI service took too long to respond. Please try asking again.",
                sources=source_metadata_list,
                has_found_info=True,
                show_file_actions=show_file_actions,
                file_actions=file_actions,
                conversation_id=request.conversation_id,
            )

        except LLMAuthError as exc:
            logger.warning("LLM authentication error during query: %s", exc)
            return InformationQueryResponse(
                query=clean_query,
                intent=intent_result.intent.value,
                category=intent_result.category.value,
                answer="AI answering is currently unavailable because the Gemini API key is not configured on the server.",
                sources=source_metadata_list,
                has_found_info=True,
                show_file_actions=show_file_actions,
                file_actions=file_actions,
                conversation_id=request.conversation_id,
            )

        except LLMError as exc:
            logger.exception("LLM generation failed: %s", exc)
            return InformationQueryResponse(
                query=clean_query,
                intent=intent_result.intent.value,
                category=intent_result.category.value,
                answer="An error occurred while generating the answer from your documents. Please try again.",
                sources=source_metadata_list,
                has_found_info=True,
                show_file_actions=show_file_actions,
                file_actions=file_actions,
                conversation_id=request.conversation_id,
            )



# ---------------------------------------------------------------------------
# Backward Compatibility Wrapper
# ---------------------------------------------------------------------------


async def answer_question(
    request: RAGRequest,
    user_id: str,
    token: str | None = None,
) -> RAGResponse:
    """Legacy RAG endpoint wrapper maintained for backward-compatibility."""
    info_req = InformationQueryRequest(
        query=request.query,
        document_id=request.document_id,
        top_k=request.top_k,
        similarity_threshold=request.similarity_threshold,
    )
    res = await execute_information_query(info_req, user_id, token)

    sources = [
        SourceReference(
            document_id=s.document_id,
            filename=s.filename,
            page_number=s.page_number,
            chunk_index=s.chunk_index or 0,
            similarity=s.similarity or 0.0,
        )
        for s in res.sources
    ]

    return RAGResponse(
        query=res.query,
        answer=res.answer,
        sources=sources,
        has_context=res.has_found_info,
        grounded=res.has_found_info,
    )
