"""Requirement-checker tests — reserved until that workflow is implemented."""

import pytest

pytestmark = pytest.mark.skip(
	reason="Requirement checker not implemented yet (Stage 6 foundation only)"
)


def test_requirements_placeholder() -> None:
	"""Will cover present/missing document matching in a later stage."""
	raise AssertionError("Requirement tests are not implemented yet")
