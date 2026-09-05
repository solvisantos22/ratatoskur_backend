# Teacher classroom implementation

Approved scope: a local browser teacher interface that also works on iPad; classes, uploaded exercise-image sets, assignment progress, and review of submitted handwriting and hints. Students use the existing iPad notebook. Product decisions and meeting materials remain in Notion.

## Implementation sequence

1. Backend: add teacher allowlist, owned classrooms, join-code memberships, assignments and ordered exercise images, student-to-exercise problem links. Reuse existing users and attempts. Test permissions and the full assignment lifecycle before implementation. Add an Alembic migration. New teacher access must never expose unrelated private notebooks.
2. Website: create a local Sites/shadcn frontend under teacher_portal using the existing FastAPI account API. Icelandic interface; class list, assignment creation, progress overview and student work. Responsive grid, touch-sized controls, empty/loading/error states. No fabricated progress or AI outputs. Check types and production build.
3. iPad: class join and assigned-exercise list, open each exercise in the existing notebook with its original image and persistent backend problem ID. Add a local backend address setting. Verify decoder contracts and simulator build/tests.
4. Local demo: an explicit SQLite/local-artifact mode for development with secrets outside Git; retain existing R2/production defaults. Test fresh setup, API authentication, image assignment and review using synthetic test accounts. Real AI requires the user's existing Gemini key. Document start instructions for either laptop and LAN iPad use.
5. Review permission boundaries, error handling, and cross-client contracts; rerun affected checks and record tested versus pending capabilities for meetings.

## HTTP contract (UUIDs are strings; dates ISO 8601)

All endpoints use existing bearer authentication. Teacher permission comes from TEACHER_EMAILS, never client-supplied role. API errors use FastAPI detail.

- GET/POST /teacher/classes: list or create {name}; class response {id,name,join_code,student_count}.
- GET /teacher/classes/{id}/assignments: list {id,class_id,class_name,title,item_count,created_at}.
- POST /teacher/classes/{id}/assignments: multipart title, images (one exercise per image); returns assignment summary. Validate all images before writes, bounded file count/size.
- GET /teacher/assignments/{id}: {assignment,items:[{id,title,position,image_url}],students:[{id,full_name,completed_count,attempt_count,hint_count,needs_attention,last_activity}],common_errors:[{error_type,count}]}.
- GET /teacher/assignments/{id}/students/{user_id}: {student:{id,full_name},assignment,items:[{id,title,position,image_url,problem_id,attempts:[{id,mode,verdict,response_type,message_is,created_at,solution_image_url,solution_page_urls}]}]}.
- POST /student/classes/join: {join_code}, returns class response (idempotent).
- GET /student/classes: joined class responses.
- GET /student/assignments: assignment summaries with items [{id,title,position,image_url,problem_id?}].
- POST /student/assignments/{assignment_id}/items/{item_id}/start: idempotently create/retrieve student's Problem; returns {problem: existing ProblemCreateResponse,image_url}.
- Image URLs: absolute short-lived signed URLs usable by existing URLSession and browser image tags. Local signing must bind path and expiry and prevent traversal. Reuse R2 in configured deployments.

Progress: completed means at least one correct check_solution verdict for an assigned item; hints/reveals never imply mastery. Attention is an explicit heuristic (unresolved incorrect/unclear latest response), presented as a review cue. Common errors derive only from assigned attempts. Personal exercises are excluded.

## Checks

- Backend pytest: unauthenticated/unauthorized teachers, class ownership, wrong/nonmember joins, no personal-attempt leakage, invalid/oversized uploads, repeat start, class-scoped artifact access and progress semantics.
- Migration upgrade/downgrade against supported database where available; local SQLite creates fresh metadata explicitly without pretending old PostgreSQL migrations are SQLite compatible.
- Website: type check, build, auth error/retry and fresh-page HTTP smoke test; no claim of visual/device testing without execution.
- iOS: exercise response decoding, existing unit suite and simulator build. Actual Apple Pencil/LAN walkthrough remains a physical-device check.

## Implementation review — 5 September 2026

Implemented locally on `feature/teacher-classroom` in both repositories. Independent backend, website and iOS reviews passed after correcting timestamp decoding, concurrent notebook reopening, session-refresh/logout ordering and draft separation by account/backend.

Final verification: 46 backend tests, 6 website tests, 16 iOS tests; website type checking, authored-source lint and production build; iOS Release simulator build. A real iOS client exercised the local backend without an AI call. The combined launcher and signed artifacts were checked over HTTP, including custom ports and the laptop's Wi-Fi address.

Remaining rehearsal: provision the chosen teacher account, add the existing AI key privately, inspect Safari layout, and exercise the complete flow on the physical iPad with Apple Pencil. Legacy unscoped drafts remain untouched and require manual recovery. The local prototype has not been deployed to a school; live PostgreSQL migration execution, R2 and production operations remain unverified. See `docs/classroom-demo.md` for the working procedure and limits.
