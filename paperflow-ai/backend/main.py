"""Minimal FastAPI application for the PaperFlow backend."""

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


logger = logging.getLogger("paperflow")


def _parse_origins(value: str) -> list[str]:
	"""Return normalized CORS origins from a comma-separated setting."""
	return [origin.strip() for origin in value.split(",") if origin.strip()]


class Settings:
	"""Public runtime settings for the foundation API."""

	app_name = os.getenv("APP_NAME", "PaperFlow AI")
	app_version = os.getenv("APP_VERSION", "0.1.0")
	cors_origins = _parse_origins(
		os.getenv("CORS_ORIGINS", "http://localhost:5173")
	)


settings = Settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
	logger.info("Starting %s v%s", settings.app_name, settings.app_version)
	yield
	logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
	title=settings.app_name,
	version=settings.app_version,
	lifespan=lifespan,
)

allow_all_origins = "*" in settings.cors_origins
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"] if allow_all_origins else settings.cors_origins,
	allow_credentials=not allow_all_origins,
	allow_methods=["GET"],
	allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
	_: Request, __: RequestValidationError
) -> JSONResponse:
	return JSONResponse(status_code=422, content={"detail": "Invalid request"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
	logger.exception("Unhandled application error")
	return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health() -> dict[str, str]:
	return {"status": "ok"}
