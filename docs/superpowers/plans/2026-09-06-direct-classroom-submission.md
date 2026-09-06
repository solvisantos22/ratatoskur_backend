# Direct Classroom Submission Implementation Plan

**Goal:** Let a student explicitly submit the current assigned exercise's handwriting to its teacher without calling AI, and receive a truthful submission receipt.

**Architecture:** Store immutable submission snapshots separately from AI attempts. Reuse membership, notebook ownership, image validation and private artifact storage. iOS captures all current notebook pages; the browser shows explicit submissions separately from AI responses and correctness.

**Tech stack:** Existing FastAPI/SQLModel, React teacher portal, SwiftUI/PencilKit.

## Approved scope and contract

Sölvi approved explicit submission on 6 September 2026 and authorized continued Notion updates. Teacher-written feedback is a future candidate, not part of this milestone. Continue checked commits on main and preserve Jóhannes's work.

- POST `/student/assignments/{assignment_id}/items/{item_id}/submissions` accepts multipart `problem_id`, `submission_id` (client UUID for retries), and ordered `solution_pages` files. Require current membership and the student's exact linked notebook; reject personal or another student's notebooks.
- Return `{id, created_at, page_count}` only once the snapshot is stored and committed. Same submission ID and identical content returns the original receipt; a conflicting payload gets 409. Separate intentional resubmission uses a new ID and retains the earlier snapshot.
- Validate 1–12 images using existing size/pixel limits. Store normalized, private images; no AI call, fake answer, grade, completion, hint count or analytics consent dependency.
- StartItemResponse adds nullable `last_submission` with that receipt shape. Student assignment items add nullable `last_submitted_at`. Teacher StudentProgress adds `submission_count` and `submitted_item_count` (explicit submissions only); last_activity includes submissions. StudentWorkItem adds `submissions` containing receipt fields plus ordered `solution_page_urls`.
- iOS action: save current live ink, capture all pages, ask for confirmation of sharing this exercise with its teacher, submit with visible loading and recoverable errors. Preserve drafts and retry identity; show timestamped last-submission receipt, with wording that later edits require another submission. No submission controls in personal notebooks. Retain AppTheme.
- Teacher browser: show explicit submitted-item count separately from correct-item progress and AI attempts. Show immutable snapshots under “Skil til kennara”; no fabricated AI response. Existing signed-image refresh and owner access remain intact.

## Work

- [x] Backend: test no-AI submission, ownership/membership, private images, page validation, idempotent retry/conflict, resubmission, preserved AI counters and setup/migration. Implement model, schema, routes and additive migration in backend; update scripts/setup_local.py safely for old local databases.
- [x] iOS: add receipt/API/model support, tests for authorized multipart routing and failure/retry state; wire notebook and assignment receipt UI and Xcode source membership.
- [x] Teacher portal: extend typed data and render submission counts/snapshots; check types, lint, tests and production build.
- [x] Verify integration with local synthetic student work, inspect the iPad action and browser receipt, preserve saved ink, review spec and code quality.

## Verification on 6 September 2026

84 backend tests passed (26 new submission cases); 47 iOS tests passed (9 new cases). Website type/lint checks, 7 tests and production build passed; Debug and Release iOS simulator builds succeeded. Live simulator submission sent the seven saved synthetic pen strokes without AI, restored the timestamped receipt after reopening, and preserved the notebook. Chrome displayed the exact submitted image and time, one submitted exercise, zero AI requests and zero completed exercises. Server restart preserved the receipt and image.

Code review found PostgreSQL row locks held across awaited upload reads; moved all upload reads before narrow row locking, rechecked authorization, and added a regression verifying lock timing and release. Tests use SQLite and PostgreSQL statement compilation; a live PostgreSQL concurrency run remains unverified. Physical iPad/Apple Pencil and live AI are still pending.

Repository/Notion handoff: update verified status and meeting demo instructions, pull incoming work, push checked main in both repositories, and confirm clean shared status.

## Validation commands

- Backend: `.venv/bin/python -m pytest backend/tests`
- Teacher portal: `pnpm check`, `pnpm lint`, `pnpm test`, `pnpm build`
- iOS: run ratatoskurTests on the existing iPad simulator and build Release; use separate derived-data paths for independent test work.
- Real flow: submit synthetic handwriting without Gemini configured, refresh the teacher website, inspect the submitted images and timestamp, then reopen the notebook and verify its saved ink and receipt.
