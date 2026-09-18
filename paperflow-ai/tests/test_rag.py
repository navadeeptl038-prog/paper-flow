"""RAG tests — reserved until Gemini/RAG is implemented."""

import pytest

pytestmark = pytest.mark.skip(
	reason="RAG features not implemented yet (Stage 6 foundation only)"
)


def test_rag_placeholder() -> None:
	"""Will cover grounded answers and source citations in a later stage."""
	raise AssertionError("RAG tests are not implemented yet")
