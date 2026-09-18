"""FastAPI application foundation for PaperFlow AI."""

import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


load_dotenv()
logger = logging.getLogger("paperflow")


def _configured_origins() -> list[str]:
	value = os.getenv("CORS_ORIGINS", "http://localhost:5173")
	return [origin.strip() for origin in value.split(",") if origin.strip()]


class HealthResponse(BaseModel):
	status: str


app = FastAPI(
	title=os.getenv("APP_NAME", "PaperFlow AI"),
	version=os.getenv("APP_VERSION", "0.1.0"),
)

origins = _configured_origins()
allow_all_origins = "*" in origins
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"] if allow_all_origins else origins,
	allow_credentials=not allow_all_origins,
	allow_methods=["GET"],
	allow_headers=["Content-Type", "Authorization"],
)


api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
	return HealthResponse(status="ok")


app.include_router(api_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
	_request: Request, _exception: RequestValidationError
) -> JSONResponse:
	return JSONResponse(status_code=422, content={"detail": "Invalid request"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(
	_request: Request, exception: Exception
) -> JSONResponse:
	logger.exception("Unhandled application error: %s", exception)
	return JSONResponse(status_code=500, content={"detail": "Internal server error"})
