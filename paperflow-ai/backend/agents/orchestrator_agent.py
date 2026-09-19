"""Simple request router for the PaperFlow multi-agent foundation.

This module provides a lightweight orchestrator that decides which downstream
specialized agent should handle a request. The intent routing is deliberately
conservative: it does not infer account or user identity from user text and it
only routes to specialized agents when the query clearly matches a supported
request class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agents.document_agent import DocumentAgent
from agents.vision_agent import VisionAgent


@dataclass
class OrchestratorRouteResult:
    """Structured routing decision returned by the orchestrator."""

    intent: str
    target_agent: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    entities: dict[str, str] = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 1.0


class OrchestratorAgent:
    """Routes user requests to the correct downstream agent."""

    def __init__(self) -> None:
        self.document_agent = DocumentAgent()
        self.vision_agent = VisionAgent()

    _COUNTRY_HINTS = {
        "germany": "Germany",
        "france": "France",
        "india": "India",
        "canada": "Canada",
        "usa": "United States",
        "us": "United States",
        "united states": "United States",
        "uk": "United Kingdom",
        "australia": "Australia",
        "germany": "Germany",
    }

    _VISA_TYPES = {
        "student": "student",
        "work": "work",
        "tourist": "tourist",
        "business": "business",
        "visitor": "visitor",
        "family": "family",
        "dependent": "dependent",
        "visit": "visit",
    }

    _DOCUMENT_KEYWORDS = (
        "passport",
        "aadhaar",
        "aadhar",
        "pan",
        "id card",
        "license",
        "visa",
        "resume",
        "bank statement",
        "statement",
        "api key",
        "key",
        "document",
        "file",
    )

    def route(self, query: str, attachments: list[dict[str, Any]] | None = None) -> OrchestratorRouteResult:
        """Return the agent selection for the provided user message."""
        clean_query = (query or "").strip()
        lower_query = clean_query.lower()

        if attachments:
            for attachment in attachments:
                mime_type = str(attachment.get("mime_type") or "").lower()
                filename = str(attachment.get("filename") or "").lower()
                if mime_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    if self._looks_like_document_search(lower_query):
                        return OrchestratorRouteResult(
                            intent="HYBRID_IMAGE_DOCUMENT",
                            target_agent="vision",
                            reasoning="Image and document lookup both required; run vision first, then user-owned document retrieval.",
                            confidence=0.99,
                        )
                    return OrchestratorRouteResult(
                        intent="IMAGE_QUERY",
                        target_agent="vision",
                        reasoning="Image payload detected; route to vision pipeline.",
                        confidence=0.98,
                    )

        if self._looks_like_document_search(lower_query):
            if self._requires_vision(lower_query, attachments):
                return OrchestratorRouteResult(
                    intent="HYBRID_IMAGE_DOCUMENT",
                    target_agent="vision",
                    reasoning="The request requires OCR and then user-owned document retrieval.",
                    confidence=0.99,
                )
            return OrchestratorRouteResult(
                intent="DOCUMENT_SEARCH",
                target_agent="document_agent",
                reasoning="The request is an explicit document lookup or retrieval action.",
                confidence=0.97,
            )

        if self._requires_vision(lower_query, attachments):
            return OrchestratorRouteResult(
                intent="IMAGE_QUERY",
                target_agent="vision",
                reasoning="The request requires visual extraction or OCR before document retrieval.",
                confidence=0.98,
            )

        if self._looks_like_requirement_check(lower_query):
            country = self._extract_country(lower_query)
            visa_type = self._extract_visa_type(lower_query)
            missing = []
            entities: dict[str, str] = {}
            if country:
                entities["country"] = country
            else:
                missing.append("country")
            if visa_type:
                entities["visa_type"] = visa_type
            else:
                missing.append("visa_type")

            if missing:
                return OrchestratorRouteResult(
                    intent="REQUIREMENT_CHECK",
                    target_agent="requirement",
                    needs_clarification=True,
                    clarification_question=(
                        "I can help with visa requirements. Which country and visa type are you applying for?"
                    ),
                    entities=entities,
                    reasoning="Requirement queries need a destination and visa type before routing.",
                    confidence=0.90,
                )

            return OrchestratorRouteResult(
                intent="REQUIREMENT_CHECK",
                target_agent="requirement",
                entities=entities,
                reasoning="The request is about visa or immigration requirements.",
                confidence=0.96,
            )

        if self._looks_like_information_query(lower_query):
            return OrchestratorRouteResult(
                intent="INFORMATION_QUERY",
                target_agent="rag",
                reasoning="The question is about the content of a known document or personal record.",
                confidence=0.94,
            )

        if self._is_greeting(lower_query):
            return OrchestratorRouteResult(
                intent="GENERAL_CHAT",
                target_agent="general",
                reasoning="The user is greeting or asking about general app capability.",
                confidence=0.9,
            )

        if self._is_unsupported_external_query(lower_query):
            return OrchestratorRouteResult(
                intent="UNKNOWN",
                target_agent="unknown",
                reasoning="The request is outside the document assistant scope.",
                confidence=0.85,
            )

        return OrchestratorRouteResult(
            intent="GENERAL_CHAT",
            target_agent="general",
            reasoning="The request does not map to a specialized agent; use the general assistant fallback.",
            confidence=0.75,
        )

    def execute(
        self,
        *,
        query: str,
        user_id: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute the agent pipeline for a user request while preserving the authenticated identity."""
        if not user_id:
            raise ValueError("user_id is required and must come from the authenticated identity.")

        lower_query = (query or "").lower()
        route = self.route(query, attachments=attachments)
        vision_result = None
        document_result = None

        if route.target_agent == "vision" or self._requires_vision(lower_query, attachments):
            image_attachment = self._pick_first_image_attachment(attachments)
            if image_attachment is not None:
                vision_result = self.vision_agent.extract_from_attachment(
                    attachment=image_attachment,
                    user_id=user_id,
                )

        if route.target_agent == "document_agent" or self._looks_like_document_search(lower_query):
            document_result = self.document_agent.search_documents(
                user_id=user_id,
                query=query,
                token=None,
            )

        result: dict[str, Any] = {
            "user_id": user_id,
            "intent": route.intent,
            "target_agent": route.target_agent,
            "needs_clarification": route.needs_clarification,
            "clarification_question": route.clarification_question,
            "entities": route.entities,
            "reasoning": route.reasoning,
            "confidence": route.confidence,
            "vision": vision_result.model_dump() if vision_result is not None else None,
            "documents": [doc.__dict__ for doc in (document_result.documents if document_result else [])],
            "agents": [
                agent for agent in ["vision", "document_agent"]
                if (agent == "vision" and vision_result is not None) or (agent == "document_agent" and document_result is not None)
            ],
        }
        return result

    @staticmethod
    def _pick_first_image_attachment(attachments: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        if not attachments:
            return None
        for attachment in attachments:
            mime_type = str(attachment.get("mime_type") or "").lower()
            filename = str(attachment.get("filename") or "")
            if mime_type.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                return attachment
        return None

    @staticmethod
    def _requires_vision(lower_query: str, attachments: list[dict[str, Any]] | None = None) -> bool:
        if attachments:
            for attachment in attachments:
                mime_type = str(attachment.get("mime_type") or "").lower()
                filename = str(attachment.get("filename") or "").lower()
                if mime_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    return True
        if not lower_query:
            return False
        return bool(re.search(r"\b(image|picture|photo|scan|ocr|read this|what is written|extract)\b", lower_query))

    @staticmethod
    def _is_greeting(lower_query: str) -> bool:
        return bool(
            re.search(r"^(hi|hello|hey|good (morning|afternoon|evening)|greetings)\b", lower_query)
            or re.search(r"^(who are you|what can you do)\??$", lower_query)
        )

    @staticmethod
    def _looks_like_document_search(lower_query: str) -> bool:
        if not lower_query:
            return False
        if re.search(r"\b(find|where is|show|locate|get|give me)\b", lower_query):
            return any(keyword in lower_query for keyword in OrchestratorAgent._DOCUMENT_KEYWORDS)
        return bool(re.search(r"\b(find|where is|show|locate|get|give me)\b.*\b(passport|aadhaar|aadhar|pan|id card|resume|document|file)\b", lower_query))

    @staticmethod
    def _looks_like_requirement_check(lower_query: str) -> bool:
        if not lower_query:
            return False
        if re.search(r"\b(visa|permit|immigration|residency|citizenship)\b", lower_query):
            return True
        if re.search(r"\b(apply|requirement|requirements)\b", lower_query):
            return bool(re.search(r"\b(visa|permit|residency|citizenship|country)\b", lower_query))
        return False

    @staticmethod
    def _looks_like_information_query(lower_query: str) -> bool:
        if not lower_query:
            return False
        if "passport" in lower_query and re.search(r"\b(expire|expiry|valid|number|status|name|date of birth|dob)\b", lower_query):
            return True
        return bool(
            re.search(
                r"\b(expire|expiry|valid|status|number|date of birth|dob|summary|details|what is)\b",
                lower_query,
            )
            and any(keyword in lower_query for keyword in OrchestratorAgent._DOCUMENT_KEYWORDS)
        )

    @staticmethod
    def _extract_country(lower_query: str) -> str | None:
        for hint, country in OrchestratorAgent._COUNTRY_HINTS.items():
            if hint in lower_query:
                return country
        return None

    @staticmethod
    def _extract_visa_type(lower_query: str) -> str | None:
        for pattern, visa_type in OrchestratorAgent._VISA_TYPES.items():
            if re.search(rf"\b{pattern}\b", lower_query):
                return visa_type
        return None

    @staticmethod
    def _is_unsupported_external_query(lower_query: str) -> bool:
        return bool(
            re.search(
                r"\b(weather|forecast|temperature|rain|stock price|crypto|pizza|flight|hotel|taxi|youtube|music|news)\b",
                lower_query,
            )
        )
