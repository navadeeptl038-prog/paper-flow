"""Intent detection service for PaperFlow AI Stage 15.

Detects user intent and categorizes queries:
- information_query (personal documents, study PDFs, general documents)
- document_action (explicit request to download or view the original file)
- ambiguous_query (too vague, underspecified, or single pronoun)
- unsupported_query (weather, web automation, external commands, out of scope)
- greeting (casual conversational salutations)

Enforces strict rules:
- Do NOT show View/Download automatically.
- Only flag explicit_document_request=True if the user explicitly asks to view/download/open the file.
- If ambiguous, prompt for clarification without guessing.
- If unsupported, decline gracefully without hallucinating.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

logger = logging.getLogger("paperflow.intent_service")


class QueryIntent(str, Enum):
    INFORMATION_QUERY = "information_query"
    DOCUMENT_ACTION = "document_action"
    AMBIGUOUS_QUERY = "ambiguous_query"
    UNSUPPORTED_QUERY = "unsupported_query"
    GREETING = "greeting"


class QueryCategory(str, Enum):
    PERSONAL_DOCUMENT = "personal_document"
    STUDY_MATERIAL = "study_material"
    GENERAL_DOCUMENT = "general_document"
    UNSPECIFIED = "unspecified"


class IntentResult(BaseModel):
    """Result of user intent analysis."""

    query: str
    intent: QueryIntent
    category: QueryCategory = QueryCategory.UNSPECIFIED
    explicit_document_request: bool = False
    target_document_hint: str | None = None
    target_sources: list[str] | None = None
    clarification_message: str | None = None
    confidence: float = 1.0
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Heuristic Patterns
# ---------------------------------------------------------------------------

DRIVE_SOURCE_PATTERNS = [
    r"\b(google\s*drive|gdrive|on\s+drive|in\s+drive|drive\s+file|drive\s+folder)\b",
]

GMAIL_SOURCE_PATTERNS = [
    r"\b(gmail|email|emails|e-mail|mail|inbox|sent\s+mail|email\s+attachment)\b",
]

LOCAL_SOURCE_PATTERNS = [
    r"\b(supabase|local|uploaded|paperflow|my\s+uploads|uploaded\s+document|local\s+storage)\b",
]

def determine_query_sources(query: str) -> list[str] | None:
    """Detect if query specifically targets certain sources.

    Returns:
        List of matching source names (e.g. ['Google Drive'], ['Gmail'], ['Supabase Storage']),
        or None if general (searches all authorized sources).
    """
    lower = query.lower()
    sources = []
    if any(re.search(p, lower) for p in DRIVE_SOURCE_PATTERNS):
        sources.append("Google Drive")
    if any(re.search(p, lower) for p in GMAIL_SOURCE_PATTERNS):
        sources.append("Gmail")
    if any(re.search(p, lower) for p in LOCAL_SOURCE_PATTERNS):
        sources.append("Supabase Storage")
    return sources if sources else None


GREETING_PATTERNS = [
    r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening|day))\b",
    r"^(who\s+are\s+you|what\s+can\s+you\s+do)\??$",
]

# Queries lacking context, pronouns with no antecedent, single punctuation, vague prompts
AMBIGUOUS_PATTERNS = [
    r"^\s*(\?|\.|\!|\.\.\.)\s*$",
    r"^\s*(tell\s+me|what\s+is\s+it|what\s+about\s+it|show\s+it|find\s+it|explain\s+it|details|information|document|file)\s*\??\s*$",
    r"^\s*(what|why|how|where|when|who)\s*\??\s*$",
    r"^\s*(give\s+me\s+info|more\s+details|check\s+this|look\s+at\s+that)\s*\??\s*$",
]

# Queries clearly out of scope for personal document Q&A
UNSUPPORTED_PATTERNS = [
    r"\b(weather|forecast|temperature|rain|humidity)\b",
    r"\b(order\s+pizza|order\s+food|delivery|book\s+(flight|hotel|cab|uber|taxi))\b",
    r"\b(play\s+(music|song|video|youtube)|turn\s+on|turn\s+off|smart\s+home)\b",
    r"\b(stock\s+price|bitcoin\s+price|crypto\s+price|live\s+score|cricket\s+score)\b",
    r"\b(execute|run\s+(command|script|shell|terminal|rm\s+-rf))\b",
]

# Attribute/field lookup indicators (these request specific information, NOT the file itself)
ATTRIBUTE_PATTERNS = [
    r"\b(number|no\b|num\b|expiry|expiration|validity|date\s+of\s+birth|dob|address|name|status|balance|pin|cvv|photo|details|summary|summarize)\b",
]

# Explicit file operations: Only these trigger original-file actions!
EXPLICIT_FILE_ACTION_PATTERNS = [
    r"\b(download|view|open|get)\s+(the\s+|my\s+|this\s+)?(original\s+)?(file|document|pdf|copy)\b",
    r"\bdownload\s+(the\s+|my\s+)?(passport|aadhaar|pan|atm\s*card|license|certificate|statement|pdf|file|document)\b",
    r"\bview\s+(the\s+|my\s+)?(passport|aadhaar|pan|atm\s*card|license|certificate|statement|pdf|file|document)\b",
    r"\bopen\s+(the\s+|my\s+)?(passport|aadhaar|pan|atm\s*card|license|certificate|statement|pdf|file|document)\b",
    r"\b(give\s+me\s+the\s+(original\s+)?(file|pdf|document|copy))\b",
    r"\b(show\s+me\s+the\s+(original\s+)?(file|pdf|copy))\b",
]

# Direct document lookup queries (e.g. "Find my passport.", "Find my ATM card.")
DOCUMENT_QUERY_PATTERNS = [
    r"^(find|where\s+is|show|locate|get|give\s+me)\s+(my\s+|the\s+)?([a-zA-Z0-9_\s-]+?\b(passport|atm\s*card|credit\s*card|debit\s*card|aadhaar|pan\s*card|pan|license|id\s*card|resume|document|file))\s*[\.\?!]*$",
    r"^(find|where\s+is|show|locate|get|give\s+me)\s+(my\s+|the\s+)?([a-zA-Z0-9_\s-]+\.(pdf|docx|png|jpg|jpeg|webp))\s*[\.\?!]*$",
]

# Personal document indicators
PERSONAL_DOCUMENT_PATTERNS = [
    r"\b(aadhaar|aadhar|uidai|passport|atm\s*card|credit\s*card|debit\s*card|pan\s*card|pan|driving\s*license|driver'?s\s*license|voter\s*id)\b",
    r"\b(ssn|social\s+security|tax\s+return|w-?2|1099|itr|form\s+16)\b",
    r"\b(birth\s+certificate|marriage\s+certificate|degree\s+certificate|marksheet|diploma)\b",
    r"\b(bank\s+statement|salary\s+slip|pay\s+slip|insurance\s+policy|mediclaim)\b",
    r"\b(expiry\s+date|date\s+of\s+birth|dob|id\s+number|account\s+number)\b",
]


# Study material / textbook / academic indicators
STUDY_PATTERNS = [
    r"\b(chapter\s+\d+|unit\s+\d+|section\s+\d+|module\s+\d+)\b",
    r"\b(summarize|summary|syllabus|textbook|lecture\s+notes|study\s+guide)\b",
    r"\b(explain\s+(the\s+concept|theorem|law|mechanism|process|chapter))\b",
    r"\b(key\s+(takeaways|points|concepts|definitions|formulas))\b",
    r"\b(homework|assignment|coursework|exam|revision)\b",
]


def detect_intent(query: str) -> IntentResult:
    """Analyze user query and return structured intent and category.

    Args:
        query: Raw query text submitted by the user.

    Returns:
        IntentResult containing classification, category, and flags.
    """
    clean_query = query.strip()
    lower_query = clean_query.lower()

    if not clean_query:
        return IntentResult(
            query=clean_query,
            intent=QueryIntent.AMBIGUOUS_QUERY,
            category=QueryCategory.UNSPECIFIED,
            explicit_document_request=False,
            clarification_message="Your query is empty. Please enter a question about your documents.",
            confidence=1.0,
            reasoning="Empty query string.",
        )

    # 1. Check for Greeting
    for pattern in GREETING_PATTERNS:
        if re.search(pattern, lower_query):
            return IntentResult(
                query=clean_query,
                intent=QueryIntent.GREETING,
                category=QueryCategory.UNSPECIFIED,
                explicit_document_request=False,
                confidence=0.95,
                reasoning="Matched casual greeting or system introduction request.",
            )

    # 2. Check for Ambiguous / Vague queries
    if len(clean_query) <= 2 or any(re.match(p, lower_query) for p in AMBIGUOUS_PATTERNS):
        return IntentResult(
            query=clean_query,
            intent=QueryIntent.AMBIGUOUS_QUERY,
            category=QueryCategory.UNSPECIFIED,
            explicit_document_request=False,
            clarification_message=(
                "Your query is too ambiguous. Could you please specify which document, "
                "chapter, or specific detail you are looking for?"
            ),
            confidence=0.95,
            reasoning="Query lacks specific subject, topic, or context.",
        )

    # 3. Check for Unsupported Queries
    for pattern in UNSUPPORTED_PATTERNS:
        if re.search(pattern, lower_query):
            return IntentResult(
                query=clean_query,
                intent=QueryIntent.UNSUPPORTED_QUERY,
                category=QueryCategory.UNSPECIFIED,
                explicit_document_request=False,
                clarification_message=(
                    "PaperFlow AI is designed to search, retrieve, and summarize information "
                    "from your uploaded documents. External operations (such as live weather, "
                    "external booking, or automation) are not supported."
                ),
                confidence=0.95,
                reasoning="Query asks for external unsupported service.",
            )

    # Check if query asks for a specific attribute/field (e.g. number, expiry date)
    has_attribute_indicator = any(re.search(p, lower_query) for p in ATTRIBUTE_PATTERNS)

    # 4. Check for Explicit Document Actions (View / Download original file)
    explicit_file_action = False
    for pattern in EXPLICIT_FILE_ACTION_PATTERNS:
        if re.search(pattern, lower_query):
            explicit_file_action = True
            break

    # 4b. Check for Direct Document Queries (e.g. "Find my passport.", "Find my ATM card.")
    direct_doc_query = False
    if not has_attribute_indicator:
        for pattern in DOCUMENT_QUERY_PATTERNS:
            if re.search(pattern, lower_query):
                direct_doc_query = True
                break

    # Extract potential document hints
    target_hint = None
    for pattern in PERSONAL_DOCUMENT_PATTERNS:
        match = re.search(pattern, lower_query)
        if match:
            target_hint = match.group(0)
            break

    if not target_hint:
        for pattern in STUDY_PATTERNS:
            match = re.search(pattern, lower_query)
            if match:
                target_hint = match.group(0)
                break

    detected_sources = determine_query_sources(clean_query)

    if explicit_file_action or direct_doc_query:
        # Determine category for the requested document
        category = QueryCategory.GENERAL_DOCUMENT
        if any(re.search(p, lower_query) for p in PERSONAL_DOCUMENT_PATTERNS):
            category = QueryCategory.PERSONAL_DOCUMENT
        elif any(re.search(p, lower_query) for p in STUDY_PATTERNS):
            category = QueryCategory.STUDY_MATERIAL

        return IntentResult(
            query=clean_query,
            intent=QueryIntent.DOCUMENT_ACTION,
            category=category,
            explicit_document_request=True,
            target_document_hint=target_hint,
            target_sources=detected_sources,
            confidence=0.95,
            reasoning=(
                "User explicitly requested original document file access or direct document location."
            ),
        )

    # 5. Information Query (Default workflow for knowledge lookup)
    category = QueryCategory.GENERAL_DOCUMENT
    if any(re.search(p, lower_query) for p in PERSONAL_DOCUMENT_PATTERNS):
        category = QueryCategory.PERSONAL_DOCUMENT
    elif any(re.search(p, lower_query) for p in STUDY_PATTERNS):
        category = QueryCategory.STUDY_MATERIAL

    return IntentResult(
        query=clean_query,
        intent=QueryIntent.INFORMATION_QUERY,
        category=category,
        explicit_document_request=False,  # DO NOT show View/Download automatically!
        target_document_hint=target_hint,
        target_sources=detected_sources,
        confidence=0.90,
        reasoning=f"Information query targeting {category.value} knowledge.",
    )
