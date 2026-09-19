"""Vision agent for PaperFlow AI.

This agent is responsible for image and visual-document extraction using the
existing OCR and image preprocessing pipeline. It never bypasses the
authenticated user identity and is only used when the orchestrator decides that
visual understanding is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from document_processing.image_processor import process_image


@dataclass
class VisionResult:
    """Structured OCR output returned by the vision agent."""

    user_id: str
    filename: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)
    source: str = "vision"

    def model_dump(self) -> dict[str, Any]:
        """Compatibility helper for structured serialization."""
        return {
            "user_id": self.user_id,
            "filename": self.filename,
            "text": self.text,
            "metadata": self.metadata,
            "pages": self.pages,
            "source": self.source,
        }


class VisionAgent:
    """Runs image preprocessing and OCR for user-owned visual content."""

    @staticmethod
    def extract_from_bytes(
        *,
        image_bytes: bytes,
        filename: str,
        user_id: str,
    ) -> VisionResult:
        """Extract text from raw image bytes while preserving the authenticated user."""
        if not user_id:
            raise ValueError("user_id is required and must come from the authenticated identity.")
        if not image_bytes:
            raise ValueError("image_bytes must not be empty.")

        result = process_image(image_bytes, filename=filename)
        return VisionResult(
            user_id=user_id,
            filename=filename,
            text=result.get("text", ""),
            metadata=result.get("metadata", {}),
            pages=result.get("pages", []),
            source="vision",
        )

    @staticmethod
    def extract_from_attachment(
        *,
        attachment: dict[str, Any],
        user_id: str,
    ) -> VisionResult | None:
        """Extract text from an attachment dictionary when it contains image bytes."""
        if not attachment:
            return None

        mime_type = str(attachment.get("mime_type") or "").lower()
        filename = str(attachment.get("filename") or "image.png")
        image_bytes = attachment.get("content") or attachment.get("bytes") or attachment.get("data")

        if not image_bytes:
            if not (mime_type.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))):
                return None
            return None

        if not isinstance(image_bytes, (bytes, bytearray)):
            try:
                image_bytes = bytes(image_bytes)
            except Exception:
                return None

        return VisionAgent.extract_from_bytes(
            image_bytes=bytes(image_bytes),
            filename=filename,
            user_id=user_id,
        )
