"""Configuration validation tests (no production secrets required)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _parse_env_example(path: Path) -> dict[str, str]:
	assert path.is_file(), f"Missing env example file: {path}"
	values: dict[str, str] = {}
	for line in path.read_text(encoding="utf-8").splitlines():
		stripped = line.strip()
		if not stripped or stripped.startswith("#") or "=" not in stripped:
			continue
		key, value = stripped.split("=", 1)
		key = key.strip()
		value = value.strip().strip('"').strip("'")
		assert ENV_KEY_PATTERN.match(key), f"Invalid env key format: {key}"
		values[key] = value
	return values


def test_root_env_example_exists_and_lists_expected_keys(project_root: Path) -> None:
	env_path = project_root / ".env.example"
	values = _parse_env_example(env_path)
	required_keys = {
		"APP_NAME",
		"CORS_ORIGINS",
		"VITE_SUPABASE_URL",
		"VITE_SUPABASE_ANON_KEY",
		"SUPABASE_URL",
		"SUPABASE_ANON_KEY",
		"SUPABASE_SERVICE_ROLE_KEY",
		"GEMINI_API_KEY",
		"GEMINI_MODEL",
	}
	missing = required_keys - set(values)
	assert not missing, f"Root .env.example missing keys: {sorted(missing)}"


def test_env_example_files_do_not_contain_secret_values(project_root: Path) -> None:
	"""Foundation guard: committed env examples must stay names-only."""
	paths = [
		project_root / ".env.example",
		project_root / "backend" / ".env.example",
		project_root / "frontend" / ".env.example",
	]
	suspicious = re.compile(
		r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{20,}|"
		r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
	)
	for path in paths:
		if not path.is_file():
			continue
		values = _parse_env_example(path)
		for key, value in values.items():
			assert value == "", f"{path.name} has non-empty value for {key}"
			assert not suspicious.search(value), f"{path.name} looks like it contains a secret for {key}"


def test_backend_env_example_documents_core_backend_keys(backend_root: Path) -> None:
	values = _parse_env_example(backend_root / ".env.example")
	for key in ("APP_NAME", "CORS_ORIGINS", "FRONTEND_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
		assert key in values, f"backend/.env.example missing {key}"


def test_cors_origins_parser_splits_and_trims(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("CORS_ORIGINS", " http://localhost:5173 , https://example.com ")
	from main import _configured_origins

	assert _configured_origins() == [
		"http://localhost:5173",
		"https://example.com",
	]


def test_cors_origins_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("CORS_ORIGINS", raising=False)
	monkeypatch.delenv("FRONTEND_URL", raising=False)
	from main import _configured_origins

	assert _configured_origins() == [
		"http://localhost:5173",
		"http://127.0.0.1:5173",
	]


def test_cors_origins_accepts_loopback_aliases_when_using_default_host(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("CORS_ORIGINS", raising=False)
	monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
	from main import _configured_origins

	assert _configured_origins() == [
		"http://localhost:5173",
		"http://127.0.0.1:5173",
	]


def test_cors_origins_accepts_loopback_aliases_for_vite_port_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("CORS_ORIGINS", raising=False)
	monkeypatch.setenv("FRONTEND_URL", "http://127.0.0.1:5178")
	from main import _configured_origins

	assert _configured_origins() == [
		"http://127.0.0.1:5178",
		"http://localhost:5178",
	]


def test_openapi_documents_health_and_app_title(client) -> None:
	response = client.get("/openapi.json")
	assert response.status_code == 200
	payload = response.json()
	assert "PaperFlow" in payload["info"]["title"]
	assert "/health" in payload["paths"]


@pytest.mark.requires_config
def test_supabase_url_format_when_configured(require_supabase_url: str) -> None:
	"""Only runs when SUPABASE_URL is present; does not call the network."""
	assert require_supabase_url.startswith("https://"), "SUPABASE_URL should use https"
	assert " " not in require_supabase_url
