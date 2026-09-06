# Local classroom demo

Use the regular local repositories on `main`. Discuss the
change here, edit/check locally, and review the iPad app in Xcode. Pull incoming
team changes before work and push checked milestones regularly so Jóhannes can
use them. Merge checked milestones into `main` and keep unfinished device review explicit.
Notion remains the place for product decisions and meeting materials.

## Start on this computer

From the backend repository:

```sh
bash scripts/dev_classroom.sh
```

The teacher website is `http://127.0.0.1:3000`; the backend is
`http://127.0.0.1:8000`. Leave the terminal running. Control-C stops both.
On a new computer, install Python 3.12, Node.js 22.13+ and pnpm first. The launcher
also detects the Codex bundled runtimes when present.

The first launch creates `backend/.env` and `.local/classroom.db`. These files
stay outside Git. It creates no accounts and does not invent AI responses.
The launcher also applies the known additive assignment-policy upgrade to an
existing local classroom database, preserving its accounts and assignments.
It refuses unrelated incomplete schemas. PostgreSQL uses Alembic migrations.

Provision the teacher once, using their chosen email and name:

```sh
.venv/bin/python scripts/create_teacher.py --email YOUR_EMAIL --name 'YOUR_NAME'
```

The helper asks for a password without displaying it and adds the account to
`TEACHER_EMAILS`. Restart the launcher afterward. Existing passwords are preserved.
The website has teacher login; ordinary student registration remains in the app.
Teacher registration is restricted because the existing account system has no
email verification.

Add the existing `GEMINI_API_KEY` privately to `backend/.env` and restart before
demonstrating hints or checks. With no key, class creation, uploads, joining and
notebook preparation work; AI requests return a configuration error. Real AI
responses require internet access even though the backend runs locally.

## Use an actual iPad

Connect the laptop and iPad to the same reachable Wi-Fi network, then run:

```sh
bash scripts/dev_classroom.sh --lan
```

The launcher prints two addresses: the teacher website and the iPad backend.
Open the teacher website in Safari on either computer or iPad. In the student
app's login-screen backend settings, use the printed backend address. The
launcher uses that address for assignment and handwriting image links too.
If automatic address detection fails, supply the laptop's Wi-Fi IP explicitly:

```sh
DEMO_HOST=192.168.1.20 bash scripts/dev_classroom.sh --lan
```

The address above is only an example. On a different network or Jóhannes's
computer, use the address printed there. Allow the laptop's incoming connection
and the iPad's local-network prompt when needed. Some guest Wi-Fi networks prevent
devices from reaching one another.

Open `ratatoskur_ios/ratatoskur.xcodeproj`, select the iPad and your development
team in Xcode, and Run the Debug configuration. The Debug configuration permits
the local HTTP connection. A backend address change clears that app's existing
credentials before reconnecting. Each laptop has its own local database and
accounts unless explicitly configured to share a backend.

## Demonstration sequence

1. Teacher signs in, creates one class and shares the class code.
2. Teacher uploads a named exercise set: one problem per image, PNG/JPEG,
   1–12 images, up to 7 MB each and 30 MB combined (16 million pixels per image).
   New sets in the website default to hints and checks. Enable **Leyfa fullar
   lausnir** to permit full worked solutions. The set becomes available
   immediately after successful upload.
3. Student signs in to the iPad app, opens **Bekkurinn minn**, joins by code and
   opens an exercise. The teacher's image is loaded into the existing notebook.
4. Student writes with Apple Pencil and asks for a hint or check. This step needs
   the real AI key and has to be rehearsed on the actual iPad.
5. Teacher opens the set and chooses **Uppfæra**, then inspects that student's
   submitted handwriting and AI replies. Draft strokes become visible only after
   submission; the teacher is not watching the canvas live.
6. Reopen the assigned exercise to confirm the same notebook and saved ink remain.

Progress counts only fully correct `check_solution` responses. Hints, partial
answers and revealed solutions do not count as completed exercises. **Skoða nánar**
is a review cue based on unresolved incorrect/unclear feedback, not a diagnosis
or grade. Common-error summaries use recorded classifications and retain the
existing analytics consent rules; an empty summary does not mean no mistakes.
Image links expire after 15 minutes; **Uppfæra** obtains fresh links.

## Teacher control of full solutions

On an assignment overview, change **Leyfa fullar lausnir** and choose **Vista
stillingu**. The displayed current policy changes only after a successful save.
Only that class's teacher can change it. Disabling full solutions blocks future
`reveal` requests on the backend, including requests from older apps and already
open notebooks. Hints and checks remain available; personal notebooks and prior
responses are unchanged. This controls the full-solution action, not every answer
that an AI response might contain.

The iPad respects the policy on ordinary and classroom notebook opens, refreshes
it when returning to the app, and changes a saved blocked Reveal selection to
Hint without losing ink. A server rejection also stops repeated Reveal retries.
Existing assignments retain their previous enabled setting after the migration.
Older API clients that omit `allow_reveal` retain the previous creation behavior.

## What is verified, and what still needs review

Automated backend tests cover classroom ownership, membership, image validation,
teacher access to assigned attempts only, canonical problem images, progress,
fresh setup, signed artifacts, deleted notebooks and concurrent reopening. AI
integration tests use an explicit test double; those are not live model results.
The website has auth/proxy tests, TypeScript checks, authored-source lint and a
production build. A real HTTP check exercised the browser server-to-backend
connection with disposable synthetic accounts and images.

The native iPad changes have simulator tests for assignment decoding, request
routing, credential separation and draft preservation. A real iOS client also
completed login, joining, exercise opening, image download and notebook reopening
against a disposable local backend without an AI call.

Checks for the classroom workflow and teacher solution control on 5–6 September
2026: **55 backend tests, 7 website tests and 25 iOS tests passed**, along with
website type/lint checks, the website production build and the iOS Release
simulator build. Tests cover ownership, updated policy enforcement, migration
preservation, restored handwriting and recovery from a blocked request, including
older responses with no policy metadata. A real HTTP check through the teacher
website saved and reloaded the policy, preserved exercises and restored the
original setting. The existing local database upgrade preserved stored accounts
and assignments. These checks made no live AI calls.

The combined launcher served both endpoints through this laptop's Wi-Fi address;
another device has not yet checked that path. The address can change between
sessions; use the addresses printed by the launcher.

Saved handwriting is now separated by backend address and account. Older,
unscoped drafts are preserved, but cannot be safely assigned to an account
automatically. The notebook shows a notice when one exists. Recovering one needs
manual identification and copying; see the iOS README before changing old files.

Check actual Apple Pencil
input, physical iPad signing, Safari layout and the complete live-AI flow before
either meeting. PostgreSQL production migration execution and R2 were not tested
against a live deployment during this local setup.

This is the first classroom workflow for review. Municipality-wide account
administration, roster imports, reusable shared libraries, assessment policies,
teacher correction of AI labels and school deployment operations remain future
work. The meeting ask is a supported classroom trial with a teacher and clear
evaluation questions; no measured learning or time-saving benefit is claimed.

## Checks for development

```sh
.venv/bin/python -m pytest backend/tests
cd teacher_portal
pnpm check
pnpm lint
pnpm test
pnpm build
```

`pnpm lint` checks authored `app` and `lib` code. Generated UI catalog source is
kept unchanged; the starter's whole-catalog lint has pre-existing findings.
The optional read-only WebMCP class-list tool has not been validated in a supported
browser context and is not required for this demo.
