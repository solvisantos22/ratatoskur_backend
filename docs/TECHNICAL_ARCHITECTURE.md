# Technical Architecture

## System Overview

Ratatoskur consists of:

- iOS SwiftUI app for the student notebook experience.
- FastAPI backend for auth, problem/attempt storage, LLM orchestration, and analytics events.
- LLM layer for legibility, reasoning, error analysis, and exam answer extraction.
- SQLModel/Postgres database for users, problems, attempts, analytics, error events, and exam prep flows.
- Cloud object storage for problem images, solution images, drawing data, and generated artifacts.
- Streamlit analytics dashboard for product and learning metrics.

## Query Flow

1. Student uploads problem image and handwritten solution pages.
2. iOS app sends multipart request to `POST /query`.
3. Backend validates user, problem, upload sizes, page count, and image dimensions.
4. Optional legibility pass checks whether handwriting is readable.
5. If reading is uncertain, backend returns `confirm_reading` or `ask_clarification`.
6. If readable, reasoning prompt returns mode-specific feedback.
7. Backend stores attempts, artifacts, observability metadata, and analytics events.
8. iOS app displays the response and preserves retry state on failures.

## Reliability Principles

- Structured JSON output from LLM calls.
- Checked-in API contract examples.
- Backend response-shape tests and frontend decoding tests.
- Request IDs, trace IDs, model metadata, prompt versions, retry counts, and latency metrics.
- Consent-aware analytics and dataset boundaries.
