# ADR-001: Modular monolith + one worker + React SPA; uv for Python deps

- Status: Accepted · Date: 2026-11-24

## Context
Small team, single-machine local deployment (16 GB RAM, 6 GB VRAM). Needs a conventional REST backend, background work for slow jobs (later), and a minimal browser UI. Must be easy to run, debug and explain.

## Options
1. **Microservices** (auth, ingest, RAG, agent as separate services) — independent scaling, but network failures, more deploy/ops work and distributed debugging, with no team or scaling need to justify them.
2. **Streamlit app** — fastest UI, but hides the REST/API and frontend engineering the project needs.
3. **Modular monolith (FastAPI) + one RQ worker + React SPA** — one deployable API with internal module boundaries; slow work moved to a worker process.

Dependency manager: **pip + venv** (already installed, universal) vs **uv** (much faster installs, built-in lockfile `uv.lock`, manages Python versions).

## Decision
Option 3. Modules under `backend/app/modules/` talk only through service functions, never each other's tables. Layering: router → service → repository/DB. Python deps managed with **uv** (lockfile committed for reproducible installs in CI).

## Consequences
- One process to run and debug; in-process calls instead of network calls.
- Module boundaries keep a later split possible (the worker is already separate).
- A bug or memory spike in one module can affect the whole API process.
- Contributors need uv installed (one-line install); `pip install -e .` still works from `pyproject.toml`.

## Revisit when
A module needs independent scaling (e.g. LLM inference), a different runtime, stronger fault isolation, or a separate team owns it.
