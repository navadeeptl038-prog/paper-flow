# PAPERFLOW AI

**Stop Searching. Start Finding.**

PaperFlow AI is a full-stack AI document search and workflow assistant. Authenticated users search and understand their documents with natural language across uploaded files, Google Drive, and Gmail.

## Purpose

Help users find information, locate original documents, and check document requirements without manually digging through folders, Drive, or email.

## Architecture

```
Browser
  → Supabase Auth + private Supabase Storage
  → FastAPI (processing, retrieval, RAG, connectors)
  → text extraction / OCR → chunks → embeddings
  → PostgreSQL + pgvector
  → Gemini (backend only) → grounded answers + sources
```

- Original documents stay in private Supabase Storage (user-scoped paths).
- Extracted text, chunks, embeddings, and metadata live in PostgreSQL/pgvector.
- Render local disk is not permanent document storage; temporary processing may use `/tmp`.
- Secrets (Gemini, Google OAuth client secret, service-role keys, connector tokens) stay on the backend — never in the frontend or Git.

### High-level layout

| Area | Role |
|------|------|
| `frontend/` | React + Vite UI |
| `backend/` | FastAPI API, RAG, OCR, connectors |
| `supabase/` | SQL migrations, RLS, storage policies, seed |
| `data/sample_documents/` | Demo/sample files (non-secret) |
| `tests/` | Backend/API test suite |
| `render.yaml` | Render deployment config |

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React, Vite, JavaScript/JSX, CSS/Tailwind where appropriate |
| Backend | Python, FastAPI, Pydantic |
| Database | Supabase PostgreSQL |
| File storage | Private Supabase Storage |
| Vectors | PostgreSQL + pgvector |
| Auth | Supabase Auth (JWT validated on backend) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (384-dim) |
| LLM | Gemini (backend only; model via `GEMINI_MODEL`) |
| OCR | Python + pytesseract/Tesseract where appropriate |
| Deployment | Render |

### Supported document formats

PDF, DOCX, JPG, JPEG, PNG, WEBP, HEIC, HEIF

## Three Core Workflows

### 1. Information Query

Example: *"What is my passport expiry date?"*

Intent detection → retrieve relevant content → RAG → Gemini → grounded answer with sources.

- Do not invent facts; say when evidence is insufficient.
- Do not show View/Download unless the user asks for the original document.

### 2. Document Query

Example: *"Find my passport."*

Document-search intent → search indexed sources → return matching **original** document (filename/source, View, Download).

- View/Download use the original file from private storage.
- Never generate a replacement document.

### 3. Requirement Checker

Example: *"What documents do I need for a visa?"*

Requirement intent → extract required categories → match against user sources → Present / Missing.

- Present items: filename, source, View, Download.
- Missing items: no View/Download.
- Ask for destination/country/purpose when needed.
- Do not treat an LLM-only list as authoritative legal/immigration advice without a reliable source.

## Search Sources

1. **Local Storage** — user uploads in Supabase Storage (not files on the laptop)
2. **Google Drive** — connected via backend OAuth
3. **Gmail** — read/search oriented connector

Google Photos is out of scope.

## Security Principles

- Authenticated identity from JWT — never trust a client-sent `user_id` for authorization
- User ownership checks, PostgreSQL RLS, private storage, path traversal protection
- File type/size validation and filename sanitization
- No service-role key, Gemini key, or OAuth client secret in the frontend
- No secrets committed to Git

## Getting Started

This repository is built incrementally. Follow stage prompts for setup, schema, auth, and features.

1. Copy `.env.example` to `.env` (and later frontend/backend env files as directed).
2. Fill values locally — never commit real secrets.
3. Wait for stage-specific setup instructions before running services.

## Status

Stage 1 — Project blueprint (structure + docs only). Application functionality is not implemented yet.
