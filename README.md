# Ratatoskur Backend

Ratatoskur is an AI math coach for handwritten student work. Students upload a problem image, write a solution in the iOS app, and receive mode-specific feedback in Icelandic: hints, solution checks, or full worked solutions.

This repository contains the FastAPI backend, analytics dashboard, LLM/prompt infrastructure, database models, and product analytics tooling for the Ratatoskur product prototype.

## Product Direction

Ratatoskur is being developed toward:

- AI-assisted math tutoring for handwritten work.
- A student notebook workflow that preserves the solving process.
- Teacher/researcher-facing analytics around attempts, errors, feedback, and latency.
- Consent-aware evaluation data collection for improving model and product behavior.
- A funding path from Tækniþróunarsjóður Fræ validation work toward a later Sproti development application.

## Team

- Jóhannes Reykdal Einarsson
- Sölvi Santos
- Sævar Breki Snorrason

## Repositories

- Backend + analytics dashboard + product/research artifacts: `ratatoskur_backend`
- Frontend iOS SwiftUI app: `ratatoskur_ios`

## Project Structure

- `backend/`: FastAPI app, auth, query routes, SQLModel models, Alembic migrations, LLM integration.
- `analytics_dashboard/`: Streamlit dashboard, review-summary LLM helper, weekly insights pipeline script.
- `api_contract_examples/`: Checked-in JSON examples used to guard backend/frontend API compatibility.
- `docs/`: Product, funding, architecture, and roadmap notes.

## Backend Setup

1. Create env file:
   - Copy `backend/.env.example` to `backend/.env`
2. Install dependencies:
   - `pip install -r backend/requirements.txt`
3. Run migrations:
   - `cd backend && alembic upgrade head`
4. Start backend:
   - `fastapi dev backend/main.py`

Default backend URL: `http://127.0.0.1:8000`

## Backend Environment Variables

Required from `backend/.env.example`:

- `DATABASE_URL`
- `JWT_SECRET`
- `GEMINI_API_KEY`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`

Optional:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST` / `LANGFUSE_BASE_URL`
- `LLM_ROUTING_ENABLED` (`true` by default)
- `LLM_REASONING_SOFT_TIMEOUT_SECONDS` (`15` by default)
- `LLM_LEGIBILITY_SOFT_TIMEOUT_SECONDS` (`8` by default)
- `LLM_FALLBACK_CHAIN` (optional comma-separated `provider:model:effort` entries)
- `OPENAI_API_KEY` and `LLM_OPENAI_MODEL` for OpenAI fallback
- `ANTHROPIC_API_KEY` and `LLM_ANTHROPIC_MODEL` for Anthropic fallback

Default routing policy:

- Try Gemini with the requested thinking level.
- If configured and useful, retry the same Gemini model with lower thinking.
- If provider keys are available, fall back to OpenAI, then Anthropic.
- Deferred/background error analysis does not use an aggressive soft timeout unless `LLM_DEFERRED_SOFT_TIMEOUT_SECONDS` is set.

## API Contract Examples

The backend and iOS app are separate repositories, so response-shape drift is a real risk. Shared JSON examples live in `api_contract_examples/` and cover:

- `hint`
- `check_solution`
- `reveal`
- `confirm_reading`
- `ask_clarification`

Backend tests and frontend decoding tests should stay aligned with these fixtures.

## Feedback Rating Format

Feedback ratings are expected as:

- `thumbs_up`
- `thumbs_down`

Dashboard and weekly insights metrics are computed using these values.

## Analytics Dashboard

The Streamlit dashboard reads from the same database and includes product/learning KPIs such as:

- Daily active users
- Daily activity by mode
- Attempts by mode
- Feedback trend
- Avg attempts by problem order
- Problem-level figures
- First-solve metrics
- Useful hint ratio and unclear fix rate
- Top error types and unclear-attempt ratio trend
- Optional LLM summary of feedback comments for selected date range

### Run Dashboard

1. Install dependencies:
   - `pip install -r analytics_dashboard/requirements.txt`
2. Create env file:
   - Copy or create `analytics_dashboard/.env` with database + LLM settings
3. Start Streamlit:
   - `streamlit run analytics_dashboard/app.py`

## Weekly Insights Pipeline

Script: `analytics_dashboard/weekly_insights.py`

What it does:

- Computes weekly metrics
- Stores insights in DB tables
- Evaluates trigger rules
- Creates deduplicated GitHub issues when thresholds are breached

Run manually:

- `python analytics_dashboard/weekly_insights.py`

Suggested automation:

- Run weekly via GitHub Actions or cron.

GitHub issue creation env vars:

- `GITHUB_TOKEN`
- `GITHUB_REPO` in `owner/repo` format

## Frontend Setup

In `ratatoskur_ios`:

1. Open project in Xcode.
2. Set backend base URL.
3. Build/run app.

## Notes

- `.env` files are gitignored; keep secrets out of version control.
- For local HTTP development, `COOKIE_SECURE=false` is expected.
- This repository is intended for active product development.
