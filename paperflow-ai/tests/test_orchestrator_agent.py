from __future__ import annotations

from agents.orchestrator_agent import OrchestratorAgent
from agents.vision_agent import VisionAgent


def test_document_search_routing() -> None:
    result = OrchestratorAgent().route("Find my passport")
    assert result.intent == "DOCUMENT_SEARCH"
    assert result.target_agent == "document_agent"
    assert result.needs_clarification is False


def test_document_search_routing_for_common_personal_documents() -> None:
    for query in ("Find my Aadhaar", "Find my passport", "Find my bank statement", "Find my API key"):
        result = OrchestratorAgent().route(query)
        assert result.intent == "DOCUMENT_SEARCH", query
        assert result.target_agent == "document_agent", query
        assert result.needs_clarification is False, query


def test_information_query_routing() -> None:
    result = OrchestratorAgent().route("When does my passport expire?")
    assert result.intent == "INFORMATION_QUERY"
    assert result.target_agent == "rag"


def test_requirement_check_routing_with_country_and_visa_type() -> None:
    result = OrchestratorAgent().route("I want to apply for a Germany student visa")
    assert result.intent == "REQUIREMENT_CHECK"
    assert result.target_agent == "requirement"
    assert result.entities["country"] == "Germany"
    assert result.entities["visa_type"] == "student"


def test_requirement_check_requires_clarification_when_missing() -> None:
    result = OrchestratorAgent().route("I want to apply for a visa")
    assert result.intent == "REQUIREMENT_CHECK"
    assert result.target_agent == "requirement"
    assert result.needs_clarification is True
    assert "Which country" in (result.clarification_question or "")


def test_image_query_routing() -> None:
    result = OrchestratorAgent().route(
        "What is written in this image?",
        attachments=[{"filename": "passport.png", "mime_type": "image/png"}],
    )
    assert result.intent == "IMAGE_QUERY"
    assert result.target_agent == "vision"


def test_general_chat_routing() -> None:
    result = OrchestratorAgent().route("Hello")
    assert result.intent == "GENERAL_CHAT"
    assert result.target_agent == "general"


def test_unknown_or_unsupported_falls_back_safely() -> None:
    result = OrchestratorAgent().route("Please tell me the weather in Paris")
    assert result.intent in {"GENERAL_CHAT", "UNKNOWN"}
    assert result.target_agent in {"general", "unknown"}


def test_user_identity_not_inferred_from_prompt() -> None:
    result = OrchestratorAgent().route("My user id is 12345 and I want to find my passport")
    assert result.intent == "DOCUMENT_SEARCH"
    assert result.target_agent == "document_agent"
    assert "12345" not in str(result.entities)


def test_vision_agent_extracts_text_from_image_bytes() -> None:
    import io
    from PIL import Image

    img = Image.new("RGB", (200, 80), color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")

    result = VisionAgent().extract_from_bytes(
        image_bytes=buffer.getvalue(),
        filename="passport.png",
        user_id="user-a",
    )

    assert result.text == ""
    assert result.metadata["format"] == "PNG"


def test_orchestrator_combines_vision_and_document_context_for_authenticated_user() -> None:
    orchestrator = OrchestratorAgent()
    result = orchestrator.execute(
        query="Find the passport in this image and tell me if it matches my documents",
        user_id="user-a",
        attachments=[{"filename": "passport.png", "mime_type": "image/png", "content": b""}],
    )

    assert result["user_id"] == "user-a"
    assert result["intent"] in {"IMAGE_QUERY", "DOCUMENT_SEARCH", "HYBRID_IMAGE_DOCUMENT"}
    assert "documents" in result
    assert "vision" in result
