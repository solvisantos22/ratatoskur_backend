# Teacher Solution Controls Implementation Plan

**Goal:** Let teachers allow hints and checks while disabling full worked solutions for an assignment.

**Architecture:** Store `Assignment.allow_reveal` on the server. Return it on assignment summaries and as optional `assignment_allow_reveal` on linked problem responses. The teacher website edits it; the iPad removes the full-solution action when disabled. The query route checks the current stored value on every request before model or artifact calls.

**Tech stack:** Existing FastAPI/SQLModel, React teacher portal and SwiftUI notebook.

## Accepted behavior

- New teacher website sets default to full solutions off; existing assignments and older API clients retain their prior behavior (true when omitted).
- Creation accepts multipart `allow_reveal`. An owner-only `PATCH /teacher/assignments/{id}` accepts `{"allow_reveal": false}` and returns `AssignmentSummary`. Other teachers receive 404; students receive 403.
- Existing hints, checks, personal notebooks and earlier responses remain unchanged. The setting controls future full-solution requests in assigned notebooks; it is not a promise to prevent all answer disclosure by AI.
- Disabled `reveal` requests receive 403 with a readable Icelandic reason, even from an old app or if the teacher changed the setting after the notebook opened. No model call, artifact write or attempt is created by denial.
- The iPad uses refreshed start metadata, falls back to allowed when older backend fields are absent, and switches a saved disabled reveal selection to hint without losing ink.
- Add a forward/backward Alembic migration with existing rows true. Existing local SQLite databases receive only this known additive column upgrade, preserving accounts, assignments and ink associations. Other incomplete schemas remain rejected.

## Tasks and checks

- [x] Backend: add tests in `backend/tests/test_assignment_policy.py` for create/read/update ownership, linked problem metadata, dynamic query denial, allowed hints/checks and personal notebooks. Run failing tests before modifying `backend/models/classroom_models.py`, `backend/schemas/{classroom,problem}.py`, `backend/routes/{classroom,problem,query}.py`.
- [x] Migration/local setup: add `backend/alembic/versions/a6d4e2f1b9c0_add_assignment_solution_control.py`; test migration upgrade/downgrade and repeated local setup with existing rows in `backend/tests/test_assignment_policy.py` and `backend/tests/test_local_setup.py`. Update `scripts/setup_local.py` to apply the known additive upgrade only.
- [x] Website: add the creation toggle and a separately saved setting on the assignment overview. Use existing accessible Switch/Label primitives, report save failures, and preserve the previous effective value until save succeeds. Extend the typed assignment contract and verify PATCH forwarding in `teacher_portal/lib/api.test.ts`.
- [x] iOS: independently implement optional policy decoding, filtered ModePicker, refreshed policy application and blocked-selection recovery with persistent unit tests. Preserve ordinary notebooks, existing drafts and API compatibility. Run simulator suite and Release build.
- [x] Review spec compliance, then code quality. Run backend tests, website types/lint/tests/build and meaningful iOS checks. Check the real local database upgrade and teacher HTTP setting changes without invoking AI.
Team handoff: update workflow documentation and Notion, fetch incoming team work, merge checked milestones to `main` and push both repositories. Record the resulting shared status in Notion and keep physical-device review pending.

User approved the feature and regular merges to main in this conversation. Physical iPad/Safari testing is deferred by the user until tomorrow; the AI key awaits discussion with Jóhannes. No further feature expansion is included.

Verification: 55 backend tests, 7 website tests and 25 iOS tests passed. Website types, lint and production build passed; the iOS Release simulator build passed. Local database preservation and policy save/readback through the website proxy passed without live AI. Review fixes cover legacy missing policy metadata on a denied request and conditional rendering of the live notebook Reveal action.
