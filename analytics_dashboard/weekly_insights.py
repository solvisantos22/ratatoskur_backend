from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass
class Trigger:
    name: str
    title: str
    description: str
    current_value: float
    threshold_text: str


def get_db_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute weekly insights and optionally create GitHub issues.")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD). Defaults to previous full week.")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD). Defaults to previous full week.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print insights without creating issues.")
    return parser.parse_args()


def default_week_window(today: date) -> tuple[date, date]:
    # Previous full ISO week: Monday..Sunday
    weekday = today.weekday()  # Monday=0
    this_monday = today - timedelta(days=weekday)
    prev_monday = this_monday - timedelta(days=7)
    prev_sunday = this_monday - timedelta(days=1)
    return prev_monday, prev_sunday


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def ensure_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS insights_weekly (
                id BIGSERIAL PRIMARY KEY,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                total_attempts INTEGER NOT NULL,
                unclear_attempts INTEGER NOT NULL,
                unclear_ratio DOUBLE PRECISION NOT NULL,
                useful_hint_ratio DOUBLE PRECISION NOT NULL,
                unclear_fix_rate DOUBLE PRECISION NOT NULL,
                finished_problem_ratio DOUBLE PRECISION NOT NULL,
                mean_satisfaction DOUBLE PRECISION NOT NULL,
                trigger_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                UNIQUE (week_start, week_end)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_issues (
                id BIGSERIAL PRIMARY KEY,
                dedupe_key TEXT NOT NULL UNIQUE,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                trigger_name TEXT NOT NULL,
                issue_number INTEGER,
                issue_url TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    conn.commit()


def compute_metrics(conn: psycopg.Connection, start_date: date, end_date: date) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH attempts_in_range AS (
                SELECT id, problem_id, mode, verdict, created_at
                FROM attempts
                WHERE DATE(created_at) BETWEEN %s AND %s
            ),
            hint_attempts AS (
                SELECT * FROM attempts_in_range WHERE mode = 'hint'
            ),
            unclear_attempts AS (
                SELECT * FROM attempts_in_range WHERE verdict = 'unclear'
            ),
            problem_attempt_stats AS (
                SELECT
                    problem_id,
                    COUNT(*) AS attempt_count,
                    COUNT(*) FILTER (WHERE verdict = 'fully_solved') AS solved_count
                FROM attempts_in_range
                GROUP BY problem_id
            ),
            feedback_stats AS (
                SELECT
                    COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_up') AS up_count,
                    COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_down') AS down_count
                FROM attempt_feedback af
                JOIN attempts a ON a.id = af.attempt_id
                WHERE DATE(a.created_at) BETWEEN %s AND %s
            )
            SELECT
                (SELECT COUNT(*) FROM attempts_in_range) AS total_attempts,
                (SELECT COUNT(*) FROM unclear_attempts) AS unclear_attempts,
                COALESCE(
                    (
                        SELECT
                            COUNT(*) FILTER (
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM attempts_in_range later
                                    WHERE later.problem_id = h.problem_id
                                      AND later.created_at > h.created_at
                                      AND later.verdict IN ('fully_correct', 'fully_solved', 'correct_so_far')
                                )
                            )::float
                            / NULLIF(COUNT(*), 0)::float
                        FROM hint_attempts h
                    ),
                    0
                ) AS useful_hint_ratio,
                COALESCE(
                    (
                        SELECT
                            COUNT(*) FILTER (
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM attempts_in_range later
                                    WHERE later.problem_id = u.problem_id
                                      AND later.created_at > u.created_at
                                      AND later.verdict IS NOT NULL
                                      AND later.verdict <> 'unclear'
                                )
                            )::float
                            / NULLIF(COUNT(*), 0)::float
                        FROM unclear_attempts u
                    ),
                    0
                ) AS unclear_fix_rate,
                COALESCE(
                    (
                        SELECT
                            COUNT(*) FILTER (WHERE attempt_count > 0 AND solved_count > 0)::float
                            / NULLIF(COUNT(*) FILTER (WHERE attempt_count > 0), 0)::float
                        FROM problem_attempt_stats
                    ),
                    0
                ) AS finished_problem_ratio,
                COALESCE(
                    (
                        SELECT
                            (up_count - down_count)::float / NULLIF((up_count + down_count)::float, 0)
                        FROM feedback_stats
                    ),
                    0
                ) AS mean_satisfaction
            """,
            (start_date, end_date, start_date, end_date),
        )
        row = cur.fetchone()

    total_attempts = int(row[0] or 0)
    unclear_attempts = int(row[1] or 0)
    unclear_ratio = float(unclear_attempts / total_attempts) if total_attempts > 0 else 0.0

    return {
        "total_attempts": total_attempts,
        "unclear_attempts": unclear_attempts,
        "unclear_ratio": unclear_ratio,
        "useful_hint_ratio": float(row[2] or 0),
        "unclear_fix_rate": float(row[3] or 0),
        "finished_problem_ratio": float(row[4] or 0),
        "mean_satisfaction": float(row[5] or 0),
    }


def previous_week(start_date: date, end_date: date) -> tuple[date, date]:
    days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start, prev_end


def evaluate_triggers(current: dict[str, float], previous: dict[str, float] | None) -> list[Trigger]:
    triggers: list[Trigger] = []

    if current["unclear_ratio"] > 0.15:
        triggers.append(
            Trigger(
                name="unclear_ratio_high",
                title="High unclear ratio",
                description="Too many attempts end as unclear; ambiguity handling likely needs improvement.",
                current_value=current["unclear_ratio"],
                threshold_text="> 15%",
            )
        )

    if current["useful_hint_ratio"] < 0.40:
        triggers.append(
            Trigger(
                name="useful_hint_ratio_low",
                title="Low useful hint ratio",
                description="Hints are not frequently followed by improved later attempts.",
                current_value=current["useful_hint_ratio"],
                threshold_text="< 40%",
            )
        )

    if current["unclear_fix_rate"] < 0.50:
        triggers.append(
            Trigger(
                name="unclear_fix_rate_low",
                title="Low fix rate after unclear verdicts",
                description="Unclear attempts are not being successfully resolved by follow-up attempts.",
                current_value=current["unclear_fix_rate"],
                threshold_text="< 50%",
            )
        )

    if current["mean_satisfaction"] < 0:
        triggers.append(
            Trigger(
                name="negative_satisfaction",
                title="Negative mean user satisfaction",
                description="Feedback sentiment is net negative for this week.",
                current_value=current["mean_satisfaction"],
                threshold_text="< 0",
            )
        )

    if previous and previous.get("unclear_ratio") is not None:
        if current["unclear_ratio"] - previous["unclear_ratio"] >= 0.05:
            triggers.append(
                Trigger(
                    name="unclear_ratio_regression",
                    title="Unclear ratio regressed week-over-week",
                    description="Unclear ratio increased by at least 5 percentage points versus previous week.",
                    current_value=current["unclear_ratio"],
                    threshold_text="delta >= +5pp",
                )
            )

    return triggers


def upsert_insight_weekly(conn: psycopg.Connection, start_date: date, end_date: date, metrics: dict[str, float], triggers: list[Trigger]) -> None:
    payload = {
        "trigger_names": [t.name for t in triggers],
        "trigger_count": len(triggers),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insights_weekly (
                week_start,
                week_end,
                computed_at,
                total_attempts,
                unclear_attempts,
                unclear_ratio,
                useful_hint_ratio,
                unclear_fix_rate,
                finished_problem_ratio,
                mean_satisfaction,
                trigger_payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (week_start, week_end)
            DO UPDATE SET
                computed_at = EXCLUDED.computed_at,
                total_attempts = EXCLUDED.total_attempts,
                unclear_attempts = EXCLUDED.unclear_attempts,
                unclear_ratio = EXCLUDED.unclear_ratio,
                useful_hint_ratio = EXCLUDED.useful_hint_ratio,
                unclear_fix_rate = EXCLUDED.unclear_fix_rate,
                finished_problem_ratio = EXCLUDED.finished_problem_ratio,
                mean_satisfaction = EXCLUDED.mean_satisfaction,
                trigger_payload = EXCLUDED.trigger_payload
            """,
            (
                start_date,
                end_date,
                datetime.now(timezone.utc),
                int(metrics["total_attempts"]),
                int(metrics["unclear_attempts"]),
                float(metrics["unclear_ratio"]),
                float(metrics["useful_hint_ratio"]),
                float(metrics["unclear_fix_rate"]),
                float(metrics["finished_problem_ratio"]),
                float(metrics["mean_satisfaction"]),
                json.dumps(payload),
            ),
        )
    conn.commit()


def build_dedupe_key(trigger_name: str, start_date: date, end_date: date) -> str:
    return f"{trigger_name}|{start_date.isoformat()}|{end_date.isoformat()}"


def issue_already_recorded(conn: psycopg.Connection, dedupe_key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM insight_issues WHERE dedupe_key = %s", (dedupe_key,))
        return cur.fetchone() is not None


def insert_issue_record(
    conn: psycopg.Connection,
    *,
    dedupe_key: str,
    start_date: date,
    end_date: date,
    trigger_name: str,
    issue_number: int | None,
    issue_url: str | None,
    status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insight_issues (
                dedupe_key, week_start, week_end, trigger_name, issue_number, issue_url, status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (dedupe_key, start_date, end_date, trigger_name, issue_number, issue_url, status),
        )
    conn.commit()


def create_github_issue(title: str, body: str) -> tuple[int, str]:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPO must be in 'owner/repo' format")

    url = f"https://api.github.com/repos/{repo}/issues"
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = Request(
        url=url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ratatoskur-weekly-insights",
        },
    )

    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return int(data["number"]), str(data["html_url"])
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub network error: {exc}") from exc


def format_issue(trigger: Trigger, start_date: date, end_date: date, current: dict[str, float]) -> tuple[str, str]:
    dedupe_key = build_dedupe_key(trigger.name, start_date, end_date)
    title = f"[Insights] {trigger.title} ({start_date} to {end_date})"
    body = (
        f"Automated weekly insight trigger fired.\n\n"
        f"- Trigger: `{trigger.name}`\n"
        f"- Week: `{start_date}` to `{end_date}`\n"
        f"- Dedupe key: `{dedupe_key}`\n"
        f"- Current value: `{trigger.current_value:.4f}`\n"
        f"- Threshold: `{trigger.threshold_text}`\n\n"
        f"### Context\n"
        f"{trigger.description}\n\n"
        f"### Weekly Metrics\n"
        f"- total_attempts: `{current['total_attempts']}`\n"
        f"- unclear_attempts: `{current['unclear_attempts']}`\n"
        f"- unclear_ratio: `{current['unclear_ratio']:.4f}`\n"
        f"- useful_hint_ratio: `{current['useful_hint_ratio']:.4f}`\n"
        f"- unclear_fix_rate: `{current['unclear_fix_rate']:.4f}`\n"
        f"- finished_problem_ratio: `{current['finished_problem_ratio']:.4f}`\n"
        f"- mean_satisfaction: `{current['mean_satisfaction']:.4f}`\n"
    )
    return title, body


def main() -> None:
    args = parse_args()

    today = date.today()
    if args.start_date and args.end_date:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
    elif args.start_date or args.end_date:
        raise SystemExit("Provide both --start-date and --end-date, or neither.")
    else:
        start_date, end_date = default_week_window(today)

    if start_date > end_date:
        raise SystemExit("start_date must be <= end_date")

    conn = psycopg.connect(get_db_url())
    try:
        ensure_tables(conn)

        current = compute_metrics(conn, start_date, end_date)

        prev_start, prev_end = previous_week(start_date, end_date)
        previous = compute_metrics(conn, prev_start, prev_end)

        triggers = evaluate_triggers(current=current, previous=previous)
        upsert_insight_weekly(conn, start_date, end_date, current, triggers)

        print(f"Computed insights for {start_date}..{end_date}")
        print(json.dumps(current, indent=2))
        if not triggers:
            print("No triggers fired.")
            return

        print("Triggers fired:")
        for t in triggers:
            print(f"- {t.name} ({t.current_value:.4f}, {t.threshold_text})")

        for trigger in triggers:
            dedupe_key = build_dedupe_key(trigger.name, start_date, end_date)
            if issue_already_recorded(conn, dedupe_key):
                print(f"Skip existing dedupe key: {dedupe_key}")
                continue

            title, body = format_issue(trigger, start_date, end_date, current)

            if args.dry_run:
                print(f"[DRY RUN] Would create issue: {title}")
                insert_issue_record(
                    conn,
                    dedupe_key=dedupe_key,
                    start_date=start_date,
                    end_date=end_date,
                    trigger_name=trigger.name,
                    issue_number=None,
                    issue_url=None,
                    status="dry_run",
                )
                continue

            try:
                issue_number, issue_url = create_github_issue(title, body)
                insert_issue_record(
                    conn,
                    dedupe_key=dedupe_key,
                    start_date=start_date,
                    end_date=end_date,
                    trigger_name=trigger.name,
                    issue_number=issue_number,
                    issue_url=issue_url,
                    status="open",
                )
                print(f"Created issue #{issue_number}: {issue_url}")
            except Exception as exc:
                insert_issue_record(
                    conn,
                    dedupe_key=dedupe_key,
                    start_date=start_date,
                    end_date=end_date,
                    trigger_name=trigger.name,
                    issue_number=None,
                    issue_url=None,
                    status=f"error: {exc}",
                )
                print(f"Failed creating issue for {trigger.name}: {exc}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
