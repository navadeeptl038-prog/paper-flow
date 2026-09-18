"""Retrieval tests — reserved until retrieval is implemented."""

import pytest

pytestmark = pytest.mark.skip(
	reason="Retrieval features not implemented yet (Stage 6 foundation only)"
)


def test_retrieval_placeholder() -> None:
	"""Will cover chunk retrieval and ranking in a later stage."""
	raise AssertionError("Retrieval tests are not implemented yet")
