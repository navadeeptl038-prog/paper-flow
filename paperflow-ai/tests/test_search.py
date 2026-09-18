"""Search tests — reserved until search/RAG is implemented."""

import pytest

pytestmark = pytest.mark.skip(
	reason="Search features not implemented yet (Stage 6 foundation only)"
)


def test_search_placeholder() -> None:
	"""Will cover information and document query flows in a later stage."""
	raise AssertionError("Search tests are not implemented yet")
