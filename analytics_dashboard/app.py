from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()

THEME = {
    "background": "#E8D8C2",
    "logo": "#6C3F22",
    "primary": "#8C5A2E",
    "primary_pressed": "#6E4422",
    "surface": "#F4EBDD",
    "surface_muted": "#EDE1CD",
    "text_primary": "#2B1E14",
    "text_secondary": "#6C5848",
    "error": "#B63A2F",
    "border": "rgba(108, 63, 34, 0.18)",
    "logo_dark": "#5A3018",
    "logo_mid": "#83502A",
    "logo_light": "#A96835",
}

MODE_ORDER = ["hint", "check_solution", "reveal"]
MODE_COLORS = {
    "hint": THEME["logo_light"],
    "check_solution": THEME["logo_mid"],
    "reveal": THEME["logo_dark"],
}
LOGO_PATH = Path(__file__).resolve().parent / "ratatoskur_logo.svg"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "prompt.txt"


@st.cache_resource
def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to your environment or .env file.")
    return create_engine(database_url, pool_pre_ping=True)


@st.cache_data(show_spinner=False, ttl=30)
def get_date_bounds() -> tuple[date | None, date | None]:
    engine = get_engine()
    query = text(
        """
        SELECT
            MIN(DATE(created_at)) AS min_date,
            MAX(DATE(created_at)) AS max_date
        FROM attempts
        """
    )
    with engine.connect() as conn:
        row = conn.execute(query).mappings().first()

    min_date = row["min_date"] if row else None
    max_date = row["max_date"] if row else None
    return min_date, max_date


@st.cache_data(show_spinner=False, ttl=30)
def get_daily_active_users(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(DISTINCT user_id) AS dau
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        GROUP BY DATE(created_at)
        ORDER BY day
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    full_days = pd.date_range(start=start_date, end=end_date, freq="D")
    if df.empty:
        return pd.DataFrame({"day": full_days, "dau": 0})

    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df = df.set_index("day").reindex(full_days, fill_value=0)
    df.index.name = "day"
    df = df.reset_index()
    df["dau"] = df["dau"].astype(int)
    return df


@st.cache_data(show_spinner=False, ttl=30)
def get_daily_attempt_activity(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            DATE(created_at) AS day,
            mode,
            COUNT(*) AS attempts
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        GROUP BY DATE(created_at), mode
        ORDER BY day, mode
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    full_days = pd.date_range(start=start_date, end=end_date, freq="D")
    mode_index = pd.MultiIndex.from_product([full_days, MODE_ORDER], names=["day", "mode"])

    if df.empty:
        by_mode = pd.DataFrame(index=mode_index).reset_index()
        by_mode["attempts"] = 0
    else:
        df["day"] = pd.to_datetime(df["day"]).dt.normalize()
        by_mode = (
            df.set_index(["day", "mode"])
            .reindex(mode_index, fill_value=0)
            .reset_index()
        )
        by_mode["attempts"] = by_mode["attempts"].astype(int)

    totals = (
        by_mode.groupby("day", as_index=False)["attempts"]
        .sum()
        .assign(mode="total")
    )
    combined = pd.concat([by_mode, totals], ignore_index=True)
    return combined


@st.cache_data(show_spinner=False, ttl=30)
def get_unique_active_users(start_date: date, end_date: date) -> int:
    engine = get_engine()
    query = text(
        """
        SELECT COUNT(DISTINCT user_id) AS active_users
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        """
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"start_date": start_date, "end_date": end_date}).mappings().first()
    return int(row["active_users"] or 0)


@st.cache_data(show_spinner=False, ttl=30)
def get_attempt_distribution_by_mode(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            mode,
            COUNT(*) AS attempts
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        GROUP BY mode
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    if df.empty:
        return pd.DataFrame({"mode": MODE_ORDER, "attempts": [0, 0, 0]})

    grouped = df.set_index("mode").reindex(MODE_ORDER, fill_value=0).reset_index()
    grouped["attempts"] = grouped["attempts"].astype(int)
    return grouped


@st.cache_data(show_spinner=False, ttl=30)
def get_feedback_trend(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            DATE(a.created_at) AS day,
            COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_up') AS ups,
            COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_down') AS downs
        FROM attempt_feedback af
        JOIN attempts a ON a.id = af.attempt_id
        WHERE DATE(a.created_at) BETWEEN :start_date AND :end_date
        GROUP BY DATE(a.created_at)
        ORDER BY day
        """
    )

    full_days = pd.date_range(start=start_date, end=end_date, freq="D")
    full_df = pd.DataFrame({"day": full_days})

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})
    except Exception:
        return full_df.assign(ups=0, downs=0, net_score=0, sign="zero")

    if df.empty:
        return full_df.assign(ups=0, downs=0, net_score=0, sign="zero")

    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    merged = full_df.merge(df, on="day", how="left")
    merged["ups"] = merged["ups"].fillna(0).astype(int)
    merged["downs"] = merged["downs"].fillna(0).astype(int)
    merged["ups_cum"] = merged["ups"].cumsum()
    merged["downs_cum"] = merged["downs"].cumsum()
    merged["net_score"] = merged["ups_cum"] - merged["downs_cum"]
    merged["sign"] = merged["net_score"].apply(
        lambda v: "positive" if v > 0 else ("negative" if v < 0 else "zero")
    )
    return merged


@st.cache_data(show_spinner=False, ttl=30)
def get_feedback_comments(start_date: date, end_date: date) -> list[str]:
    engine = get_engine()
    query = text(
        """
        SELECT af.comment
        FROM attempt_feedback af
        JOIN attempts a ON a.id = af.attempt_id
        WHERE DATE(a.created_at) BETWEEN :start_date AND :end_date
          AND af.comment IS NOT NULL
          AND btrim(af.comment) <> ''
        ORDER BY a.created_at DESC, af.created_at DESC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"start_date": start_date, "end_date": end_date}).fetchall()
    return [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]


def load_comment_summary_prompt() -> str:
    fallback = (
        "You are analyzing student feedback comments from an AI math tutoring app. "
        "Summarize the comments and extract the most useful product insights.\n\n"
        "Return:\n"
        "1) Top 3 recurring themes\n"
        "2) Top 3 actionable improvements for the product team\n"
        "3) One short summary paragraph\n"
        "Keep it concise and concrete."
    )
    try:
        prompt_text = PROMPT_PATH.read_text(encoding="utf-8").strip()
        return prompt_text or fallback
    except Exception:
        return fallback


def run_review_summary(prompt: str, comments: list[str]) -> str:
    # Import lazily so dashboard still runs if LLM deps/env are missing.
    from llm import summarize_review

    comment_block = "\n".join(f"- {c}" for c in comments)
    result = summarize_review(prompt, comment_block)
    if result is None:
        return ""
    return str(result)


@st.cache_data(show_spinner=False, ttl=30)
def get_avg_attempts_by_problem_order(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        WITH ranked_problems AS (
            SELECT
                p.id AS problem_id,
                p.user_id,
                ROW_NUMBER() OVER (
                    PARTITION BY p.user_id
                    ORDER BY p.created_at, p.id
                ) AS problem_order
            FROM problems p
            WHERE DATE(p.created_at) BETWEEN :start_date AND :end_date
        ),
        attempt_counts AS (
            SELECT
                a.problem_id,
                COUNT(*) AS attempts
            FROM attempts a
            GROUP BY a.problem_id
        )
        SELECT
            rp.problem_order,
            AVG(COALESCE(ac.attempts, 0))::float AS avg_attempts
        FROM ranked_problems rp
        LEFT JOIN attempt_counts ac ON ac.problem_id = rp.problem_id
        GROUP BY rp.problem_order
        ORDER BY rp.problem_order
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    if df.empty:
        return pd.DataFrame({"problem_order": [], "avg_attempts": []})

    df["problem_order"] = df["problem_order"].astype(int)
    df["avg_attempts"] = df["avg_attempts"].astype(float)
    return df


@st.cache_data(show_spinner=False, ttl=30)
def get_avg_attempts_by_problem_order_and_mode(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        WITH ranked_problems AS (
            SELECT
                p.id AS problem_id,
                p.user_id,
                ROW_NUMBER() OVER (
                    PARTITION BY p.user_id
                    ORDER BY p.created_at, p.id
                ) AS problem_order
            FROM problems p
            WHERE DATE(p.created_at) BETWEEN :start_date AND :end_date
        ),
        attempt_counts_by_mode AS (
            SELECT
                a.problem_id,
                a.mode,
                COUNT(*) AS attempts
            FROM attempts a
            GROUP BY a.problem_id, a.mode
        )
        SELECT
            rp.problem_order,
            ac.mode,
            AVG(ac.attempts)::float AS avg_attempts
        FROM ranked_problems rp
        JOIN attempt_counts_by_mode ac ON ac.problem_id = rp.problem_id
        GROUP BY rp.problem_order, ac.mode
        ORDER BY rp.problem_order, ac.mode
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    if df.empty:
        return pd.DataFrame({"problem_order": [], "mode": [], "avg_attempts": []})

    df["problem_order"] = df["problem_order"].astype(int)
    df["mode"] = df["mode"].astype(str)
    df["avg_attempts"] = df["avg_attempts"].astype(float)
    return df


@st.cache_data(show_spinner=False, ttl=30)
def get_problem_level_kpis(start_date: date, end_date: date) -> dict[str, float]:
    engine = get_engine()
    query = text(
        """
        WITH problem_set AS (
            SELECT p.id
            FROM problems p
            WHERE DATE(p.created_at) BETWEEN :start_date AND :end_date
        ),
        attempt_counts AS (
            SELECT
                p.id AS problem_id,
                COUNT(a.id) AS total_attempts,
                COUNT(a.id) FILTER (WHERE a.verdict = 'incorrect') AS incorrect_attempts,
                COUNT(a.id) FILTER (WHERE a.mode = 'hint') AS hint_attempts,
                COUNT(a.id) FILTER (WHERE a.mode = 'check_solution') AS check_solution_attempts,
                COUNT(a.id) FILTER (WHERE a.mode = 'reveal') AS reveal_attempts
            FROM problem_set p
            LEFT JOIN attempts a
              ON a.problem_id = p.id
             AND DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY p.id
        )
        SELECT
            COALESCE(AVG(total_attempts)::float, 0) AS avg_attempts_overall,
            COALESCE(AVG(hint_attempts)::float, 0) AS avg_attempts_hint,
            COALESCE(AVG(check_solution_attempts)::float, 0) AS avg_attempts_check_solution,
            COALESCE(AVG(reveal_attempts)::float, 0) AS avg_attempts_reveal,
            COALESCE(AVG(incorrect_attempts)::float, 0) AS avg_incorrect_overall,
            COALESCE(
                (
                    COUNT(*) FILTER (
                        WHERE total_attempts > 0
                          AND EXISTS (
                              SELECT 1
                              FROM attempts ax
                              WHERE ax.problem_id = attempt_counts.problem_id
                                AND DATE(ax.created_at) BETWEEN :start_date AND :end_date
                                AND ax.verdict = 'fully_solved'
                          )
                    )::float
                    /
                    NULLIF(COUNT(*) FILTER (WHERE total_attempts > 0), 0)::float
                ),
                0
            ) AS finished_problem_ratio
        FROM attempt_counts
        """
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"start_date": start_date, "end_date": end_date}).mappings().first()

    if not row:
        return {
            "avg_attempts_overall": 0.0,
            "avg_attempts_hint": 0.0,
            "avg_attempts_check_solution": 0.0,
            "avg_attempts_reveal": 0.0,
            "avg_incorrect_overall": 0.0,
            "finished_problem_ratio": 0.0,
        }

    return {
        "avg_attempts_overall": float(row["avg_attempts_overall"] or 0),
        "avg_attempts_hint": float(row["avg_attempts_hint"] or 0),
        "avg_attempts_check_solution": float(row["avg_attempts_check_solution"] or 0),
        "avg_attempts_reveal": float(row["avg_attempts_reveal"] or 0),
        "avg_incorrect_overall": float(row["avg_incorrect_overall"] or 0),
        "finished_problem_ratio": float(row["finished_problem_ratio"] or 0),
    }


@st.cache_data(show_spinner=False, ttl=30)
def get_finished_problem_ratio_by_ordinal(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        WITH ranked_problems AS (
            SELECT
                p.id AS problem_id,
                p.user_id,
                ROW_NUMBER() OVER (
                    PARTITION BY p.user_id
                    ORDER BY p.created_at, p.id
                ) AS problem_order
            FROM problems p
            WHERE DATE(p.created_at) BETWEEN :start_date AND :end_date
        ),
        problem_outcomes AS (
            SELECT
                rp.problem_order,
                rp.problem_id,
                CASE WHEN COUNT(a.id) > 0 THEN 1 ELSE 0 END AS has_attempt,
                CASE WHEN COUNT(a.id) FILTER (WHERE a.verdict = 'fully_solved') > 0 THEN 1 ELSE 0 END AS is_finished
            FROM ranked_problems rp
            LEFT JOIN attempts a
              ON a.problem_id = rp.problem_id
             AND DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY rp.problem_order, rp.problem_id
        )
        SELECT
            problem_order,
            COALESCE(
                SUM(is_finished)::float / NULLIF(SUM(has_attempt), 0)::float,
                0
            ) AS finished_ratio
        FROM problem_outcomes
        GROUP BY problem_order
        ORDER BY problem_order
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    if df.empty:
        return pd.DataFrame({"problem_order": [], "finished_ratio": []})
    df["problem_order"] = df["problem_order"].astype(int)
    df["finished_ratio"] = df["finished_ratio"].astype(float)
    return df


@st.cache_data(show_spinner=False, ttl=30)
def get_finished_problem_ratio_by_day(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        WITH attempt_day_problem AS (
            SELECT
                DATE(a.created_at) AS day,
                a.problem_id,
                MAX(CASE WHEN a.verdict = 'fully_solved' THEN 1 ELSE 0 END) AS is_finished
            FROM attempts a
            WHERE DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY DATE(a.created_at), a.problem_id
        )
        SELECT
            day,
            COALESCE(
                SUM(is_finished)::float / NULLIF(COUNT(*), 0)::float,
                0
            ) AS finished_ratio
        FROM attempt_day_problem
        GROUP BY day
        ORDER BY day
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    full_days = pd.date_range(start=start_date, end=end_date, freq="D")
    full_df = pd.DataFrame({"day": full_days})
    if df.empty:
        return full_df.assign(finished_ratio=0.0)

    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    merged = full_df.merge(df, on="day", how="left")
    merged["finished_ratio"] = merged["finished_ratio"].fillna(0.0).astype(float)
    return merged


@st.cache_data(show_spinner=False, ttl=30)
def get_first_solve_kpis(start_date: date, end_date: date) -> dict[str, float]:
    engine = get_engine()
    query = text(
        """
        WITH all_problems AS (
            SELECT id, user_id, created_at
            FROM problems
        ),
        first_problem_all_time AS (
            SELECT
                p.id,
                p.user_id,
                p.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY p.user_id
                    ORDER BY p.created_at, p.id
                ) AS rn
            FROM all_problems p
        ),
        first_problems_in_range AS (
            SELECT id, user_id, created_at
            FROM first_problem_all_time
            WHERE rn = 1
              AND DATE(created_at) BETWEEN :start_date AND :end_date
        ),
        problems_in_range AS (
            SELECT id, user_id, created_at
            FROM problems
            WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        ),
        first_solve AS (
            SELECT
                p.id AS problem_id,
                p.created_at AS problem_created_at,
                MIN(a.created_at) FILTER (WHERE a.verdict = 'fully_solved') AS first_solved_at
            FROM problems_in_range p
            LEFT JOIN attempts a
              ON a.problem_id = p.id
             AND DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY p.id, p.created_at
        ),
        attempts_before_first_solve AS (
            SELECT
                fs.problem_id,
                COUNT(a.id) AS attempts_to_first_solve
            FROM first_solve fs
            JOIN attempts a
              ON a.problem_id = fs.problem_id
             AND fs.first_solved_at IS NOT NULL
             AND a.created_at <= fs.first_solved_at
             AND DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY fs.problem_id
        ),
        minutes_to_solve AS (
            SELECT
                fs.problem_id,
                EXTRACT(EPOCH FROM (fs.first_solved_at - fs.problem_created_at)) / 60.0 AS minutes_to_first_solve
            FROM first_solve fs
            WHERE fs.first_solved_at IS NOT NULL
        ),
        first_problem_candidates AS (
            SELECT
                fp.id AS problem_id
            FROM first_problems_in_range fp
        ),
        first_problem_attempt_stats AS (
            SELECT
                fp.problem_id AS problem_id,
                COUNT(a.id) AS attempt_count,
                COUNT(a.id) FILTER (WHERE a.verdict = 'fully_solved') AS fully_solved_count
            FROM first_problem_candidates fp
            LEFT JOIN attempts a
              ON a.problem_id = fp.problem_id
             AND DATE(a.created_at) BETWEEN :start_date AND :end_date
            GROUP BY fp.problem_id
        ),
        first_problem_feedback_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_up') AS up_count,
                COUNT(*) FILTER (WHERE LOWER(af.rating) = 'thumbs_down') AS down_count
            FROM first_problem_candidates fp
            JOIN attempts a ON a.problem_id = fp.problem_id
            JOIN attempt_feedback af ON af.attempt_id = a.id
            WHERE DATE(a.created_at) BETWEEN :start_date AND :end_date
        )
        SELECT
            COALESCE(
                (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY attempts_to_first_solve) FROM attempts_before_first_solve),
                0
            ) AS median_attempts_to_first_solve,
            COALESCE(
                (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY minutes_to_first_solve) FROM minutes_to_solve),
                0
            ) AS median_minutes_to_first_solve,
            COALESCE(
                (
                    SELECT
                        COUNT(*) FILTER (WHERE attempt_count > 0 AND fully_solved_count > 0)::float
                        / NULLIF(COUNT(*) FILTER (WHERE attempt_count > 0), 0)::float
                    FROM first_problem_attempt_stats
                ),
                0
            ) AS first_problem_completion_rate,
            COALESCE(
                (
                    SELECT
                        (up_count - down_count)::float / NULLIF((up_count + down_count)::float, 0)
                    FROM first_problem_feedback_stats
                ),
                0
            ) AS first_problem_mean_satisfaction
        """
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"start_date": start_date, "end_date": end_date}).mappings().first()

    if not row:
        return {
            "median_attempts_to_first_solve": 0.0,
            "median_minutes_to_first_solve": 0.0,
            "first_problem_completion_rate": 0.0,
            "first_problem_mean_satisfaction": 0.0,
        }
    return {
        "median_attempts_to_first_solve": float(row["median_attempts_to_first_solve"] or 0),
        "median_minutes_to_first_solve": float(row["median_minutes_to_first_solve"] or 0),
        "first_problem_completion_rate": float(row["first_problem_completion_rate"] or 0),
        "first_problem_mean_satisfaction": float(row["first_problem_mean_satisfaction"] or 0),
    }


@st.cache_data(show_spinner=False, ttl=30)
def get_top_error_types(start_date: date, end_date: date, top_n: int = 8) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            TRIM(ee.error_type) AS error_type,
            COUNT(*) AS count
        FROM error_events ee
        JOIN attempts a ON a.id = ee.attempt_id
        WHERE DATE(a.created_at) BETWEEN :start_date AND :end_date
          AND ee.error_type IS NOT NULL
          AND TRIM(ee.error_type) <> ''
          AND LOWER(TRIM(ee.error_type)) <> 'unknown'
        GROUP BY 1
        ORDER BY count DESC
        LIMIT :top_n
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date, "top_n": top_n})
    if df.empty:
        return pd.DataFrame({"error_type": [], "count": []})
    df["count"] = df["count"].astype(int)
    return df


@st.cache_data(show_spinner=False, ttl=30)
def get_unclear_attempts_by_day(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(*) FILTER (WHERE verdict = 'unclear') AS unclear_attempts,
            COUNT(*) AS total_attempts
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        GROUP BY DATE(created_at)
        ORDER BY day
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    full_days = pd.date_range(start=start_date, end=end_date, freq="D")
    full_df = pd.DataFrame({"day": full_days})
    if df.empty:
        return full_df.assign(unclear_attempts=0, total_attempts=0, unclear_ratio=0.0)
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    merged = full_df.merge(df, on="day", how="left")
    merged["unclear_attempts"] = merged["unclear_attempts"].fillna(0).astype(int)
    merged["total_attempts"] = merged["total_attempts"].fillna(0).astype(int)
    merged["unclear_ratio"] = merged.apply(
        lambda r: (r["unclear_attempts"] / r["total_attempts"]) if r["total_attempts"] > 0 else 0.0,
        axis=1,
    )
    return merged


@st.cache_data(show_spinner=False, ttl=30)
def get_hint_and_fix_rates(start_date: date, end_date: date) -> dict[str, float]:
    engine = get_engine()
    query = text(
        """
        WITH attempts_in_range AS (
            SELECT
                id,
                problem_id,
                mode,
                verdict,
                created_at
            FROM attempts
            WHERE DATE(created_at) BETWEEN :start_date AND :end_date
        ),
        hint_attempts AS (
            SELECT *
            FROM attempts_in_range
            WHERE mode = 'hint'
        ),
        unclear_attempts AS (
            SELECT *
            FROM attempts_in_range
            WHERE verdict = 'unclear'
        )
        SELECT
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
                        /
                        NULLIF(COUNT(*), 0)::float
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
                        /
                        NULLIF(COUNT(*), 0)::float
                    FROM unclear_attempts u
                ),
                0
            ) AS unclear_fix_rate
        """
    )
    with engine.connect() as conn:
        row = conn.execute(query, {"start_date": start_date, "end_date": end_date}).mappings().first()

    if not row:
        return {"useful_hint_ratio": 0.0, "unclear_fix_rate": 0.0}

    return {
        "useful_hint_ratio": float(row["useful_hint_ratio"] or 0),
        "unclear_fix_rate": float(row["unclear_fix_rate"] or 0),
    }


def get_previous_window(start_date: date, end_date: date) -> tuple[date, date]:
    window_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window_days - 1)
    return prev_start, prev_end


def classify_delta(current: float, previous: float, tolerance: float = 1e-9) -> tuple[str, float]:
    delta = current - previous
    if abs(delta) <= tolerance:
        return "EQUAL ▬", 0.0
    if delta > 0:
        return "UP ▲", delta
    return "DOWN ▼", delta


def metric_delta_text(current: float, previous: float) -> tuple[str, str]:
    signal, delta = classify_delta(current, previous)
    return f"{delta:+.2f}", signal


@st.cache_data(show_spinner=False, ttl=30)
def get_latency_events(start_date: date, end_date: date) -> pd.DataFrame:
    engine = get_engine()
    query = text(
        """
        SELECT
            DATE(created_at) AS day,
            mode,
            latency_ms,
            tokens_total
        FROM attempts
        WHERE DATE(created_at) BETWEEN :start_date AND :end_date
          AND latency_ms IS NOT NULL
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"start_date": start_date, "end_date": end_date})

    if df.empty:
        return pd.DataFrame({"day": [], "mode": [], "latency_ms": [], "tokens_total": []})

    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["mode"] = df["mode"].astype(str)
    df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
    df["tokens_total"] = pd.to_numeric(df["tokens_total"], errors="coerce")
    df = df.dropna(subset=["latency_ms"])
    return df


def latency_percentiles_by_day_and_mode(latency_df: pd.DataFrame) -> pd.DataFrame:
    if latency_df.empty:
        return pd.DataFrame({"day": [], "mode": [], "p50_ms": [], "p95_ms": []})

    grouped = (
        latency_df.groupby(["day", "mode"])["latency_ms"]
        .agg(
            p50_ms=lambda s: float(s.quantile(0.5)),
            p95_ms=lambda s: float(s.quantile(0.95)),
        )
        .reset_index()
    )
    return grouped


def build_slo_df(latency_df: pd.DataFrame) -> pd.DataFrame:
    thresholds = [10000, 20000, 30000]
    labels = ["<=10s", "<=20s", "<=30s"]

    if latency_df.empty:
        rows = []
        for mode in MODE_ORDER:
            for label in labels:
                rows.append({"mode": mode, "threshold": label, "pct": 0.0})
        return pd.DataFrame(rows)

    rows = []
    for mode in MODE_ORDER:
        mode_df = latency_df[latency_df["mode"] == mode]
        n = len(mode_df)
        for threshold, label in zip(thresholds, labels):
            pct = 0.0 if n == 0 else float((mode_df["latency_ms"] <= threshold).mean() * 100)
            rows.append({"mode": mode, "threshold": label, "pct": pct})
    return pd.DataFrame(rows)


def apply_custom_style() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: radial-gradient(1200px 500px at 10% -20%, {THEME["surface"]} 0%, transparent 60%),
                        radial-gradient(1000px 500px at 90% -30%, {THEME["surface_muted"]} 0%, transparent 55%),
                        {THEME["background"]};
            color: {THEME["text_primary"]};
        }}
        .block-container {{
            max-width: 1250px;
            padding-top: 1.2rem;
            padding-bottom: 2rem;
        }}
        .panel {{
            background: {THEME["surface"]};
            border: 1px solid {THEME["border"]};
            border-radius: 14px;
            padding: 0.8rem 1rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.04);
            margin-bottom: 1rem;
        }}
        .panel h3 {{
            margin-top: 0;
            color: {THEME["text_primary"]};
        }}
        [data-testid="stMarkdownContainer"], .stCaption, .stMetric {{
            color: {THEME["text_primary"]};
        }}
        .stCaption {{
            color: {THEME["text_secondary"]} !important;
        }}
        [data-testid="stMetricValue"] {{
            color: {THEME["logo"]};
        }}
        [data-testid="stDateInput"] input,
        [data-testid="stDateInput"] button,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
            background: {THEME["surface"]} !important;
            color: {THEME["text_primary"]} !important;
            border-color: {THEME["border"]} !important;
        }}
        [data-testid="stDateInput"] input:focus,
        [data-testid="stDateInput"] button:focus,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within {{
            border-color: {THEME["logo"]} !important;
            box-shadow: 0 0 0 1px {THEME["logo"]} !important;
        }}
        [data-testid="stMultiSelect"] [data-baseweb="tag"] {{
            background: {THEME["logo"]} !important;
            color: {THEME["surface"]} !important;
        }}
        [data-testid="stDateInput"],
        [data-testid="stMultiSelect"],
        [data-testid="stDateInput"] *,
        [data-testid="stMultiSelect"] * {{
            accent-color: {THEME["logo"]} !important;
        }}
        [class*="st-key-section-"] {{
            background: {THEME["surface"]} !important;
            border: 1px solid {THEME["border"]} !important;
            border-radius: 12px !important;
            padding: 0.55rem 0.7rem !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def themed_chart(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure(background=THEME["surface"])
        .configure_view(fill=THEME["surface"], stroke=THEME["border"])
        .configure_axis(
            labelColor=THEME["text_secondary"],
            titleColor=THEME["text_primary"],
            gridColor=THEME["border"],
            domainColor=THEME["border"],
            tickColor=THEME["border"],
        )
        .configure_legend(
            labelColor=THEME["text_secondary"],
            titleColor=THEME["text_primary"],
        )
    )


st.set_page_config(page_title="Ratatoskur Tölfræðiborð", page_icon="📈", layout="wide")
apply_custom_style()

header_logo_col, header_text_col = st.columns([1, 9], vertical_alignment="center")
with header_logo_col:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=72)
with header_text_col:
    st.title("Ratatoskur Tölfræðiborð")
    st.caption("Ýmiss tölfræði")

try:
    min_date, max_date = get_date_bounds()
except Exception as exc:
    st.error(f"Gat ekki lesið úr gagnagrunni: {exc}")
    st.stop()

if min_date is None or max_date is None:
    st.info("No attempts data found yet. Submit some attempts first.")
    st.stop()

default_start = max(min_date, date.today() - timedelta(days=30))
default_end = date.today()#min(max_date, date.today())

selected_range = st.date_input(
    "Tímabil",
    value=(default_start, default_end),
    min_value=min_date,
    max_value=date.today(),
)

if not isinstance(selected_range, tuple) or len(selected_range) != 2:
    st.warning("Veldu bæði upphafs- og endadagsetningu")
    st.stop()

start_date, end_date = selected_range
if start_date > end_date:
    st.warning("Upphafdagsetning verður að vera á undan endadagsteningu")
    st.stop()

try:
    dau_df = get_daily_active_users(start_date, end_date)
    daily_activity_df = get_daily_attempt_activity(start_date, end_date)
    unique_users = get_unique_active_users(start_date, end_date)
    mode_df = get_attempt_distribution_by_mode(start_date, end_date)
    feedback_df = get_feedback_trend(start_date, end_date)
    feedback_comments = get_feedback_comments(start_date, end_date)
    attempts_trend_df = get_avg_attempts_by_problem_order(start_date, end_date)
    attempts_trend_mode_df = get_avg_attempts_by_problem_order_and_mode(start_date, end_date)
    finished_ratio_ordinal_df = get_finished_problem_ratio_by_ordinal(start_date, end_date)
    finished_ratio_day_df = get_finished_problem_ratio_by_day(start_date, end_date)
    first_solve_kpis = get_first_solve_kpis(start_date, end_date)
    hint_fix_kpis = get_hint_and_fix_rates(start_date, end_date)
    top_error_types_df = get_top_error_types(start_date, end_date)
    unclear_attempts_df = get_unclear_attempts_by_day(start_date, end_date)
    problem_kpis = get_problem_level_kpis(start_date, end_date)
    prev_start_date, prev_end_date = get_previous_window(start_date, end_date)
    problem_kpis_prev = get_problem_level_kpis(prev_start_date, prev_end_date)
    latency_df = get_latency_events(start_date, end_date)
except Exception as exc:
    st.error(f"Tölfræðireikningar misheppnuðust: {exc}")
    st.stop()

# Always generate comment summary in background on each rerun/date change,
# but keep it hidden unless explicitly requested by the user.
comment_summary_text = ""
comment_summary_error = ""
if feedback_comments:
    try:
        prompt_text = load_comment_summary_prompt()
        comment_summary_text = run_review_summary(prompt_text, feedback_comments).strip()
    except Exception as exc:
        comment_summary_error = str(exc)

# Top metrics
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Einstakir virkir notendur (EVN)", unique_users)
with m2:
    st.metric("Hámarks EVN", int(dau_df["dau"].max()) if not dau_df.empty else 0)
with m3:
    st.metric("Meðalfjöldi fyrirspurna á hvert dæmi", f"{problem_kpis['avg_attempts_overall']:.2f}")
with m4:
    p95_overall = float(latency_df["latency_ms"].quantile(0.95)) if not latency_df.empty else 0.0
    st.metric("P95 Biðtími", f"{p95_overall/1000:.1f}s")

# DAU chart
with st.container(border=True, key="section-dau"):
    st.subheader("Virkir daglegir notendur")
    dau_chart = (
        alt.Chart(dau_df)
        .mark_line(point=True, color=THEME["logo"])
        .encode(
            x=alt.X("day:T", title="Dagsetning"),
            y=alt.Y("dau:Q", title="EVN", scale=alt.Scale(domainMin=0)),
            tooltip=[alt.Tooltip("day:T", title="Dagsetning"), alt.Tooltip("dau:Q", title="EVN")],
        )
    )
    st.altair_chart(themed_chart(dau_chart), use_container_width=True)

with st.container(border=True, key="section-daily-activity"):
    st.markdown("**Dagleg virkni**")
    activity_color_domain = ["total", "hint", "check_solution", "reveal"]
    activity_color_range = [
        THEME["logo"],
        MODE_COLORS["hint"],
        MODE_COLORS["check_solution"],
        MODE_COLORS["reveal"],
    ]
    activity_chart = (
        alt.Chart(daily_activity_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("day:T", title="Dagsetning"),
            y=alt.Y("attempts:Q", title="Fyrirspurnir", scale=alt.Scale(domainMin=0)),
            color=alt.Color(
                "mode:N",
                title="Tegund",
                scale=alt.Scale(domain=activity_color_domain, range=activity_color_range),
            ),
            strokeDash=alt.StrokeDash(
                "mode:N",
                title="Series",
                scale=alt.Scale(
                    domain=activity_color_domain,
                    range=[
                        [1, 0],  # total
                        [4, 2],  # hint
                        [4, 2],  # check_solution
                        [4, 2],  # reveal
                    ],
                ),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Dagsetning"),
                alt.Tooltip("mode:N", title="Tegund"),
                alt.Tooltip("attempts:Q", title="Fyrirspurnir"),
            ],
        )
    )
    st.altair_chart(themed_chart(activity_chart), use_container_width=True)

left_col, right_col = st.columns(2)

with left_col:
    with st.container(border=True, key="section-attempts-mode"):
        st.subheader("Fjöldi fyrirspurna eftir tegund")
        mode_chart = (
            alt.Chart(mode_df)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
            .encode(
                x=alt.X("mode:N", title="Tegund", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("attempts:Q", title="Fyrirspurnir", scale=alt.Scale(domainMin=0)),
                color=alt.Color(
                    "mode:N",
                    title="Mode",
                    scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                ),
                tooltip=[alt.Tooltip("mode:N", title="Tegund"), alt.Tooltip("attempts:Q", title="Fyrirspurnir")],
            )
        )
        st.altair_chart(themed_chart(mode_chart), use_container_width=True)

    with st.container(border=True, key="section-avg-attempts-order"):
        st.subheader("Meðalfjöldi fyrirspurna eftir dæmaröðun")
        line_options = ["hint", "check_solution", "reveal", "overall"]
        selected_lines = st.multiselect(
            "Veldu tegundir",
            options=line_options,
            default=line_options,
            key="attempts_trend_line_selector",
        )

        layers = []
        selected_modes = [line for line in selected_lines if line != "overall"]
        if selected_modes:
            filtered_mode_df = attempts_trend_mode_df[attempts_trend_mode_df["mode"].isin(selected_modes)]
            layers.append(
                alt.Chart(filtered_mode_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("problem_order:Q", title="Dæmanúmer (1, 2, 3, ...)", axis=alt.Axis(format="d")),
                    y=alt.Y("avg_attempts:Q", title="Meðalfjöldi fyrirspurna", scale=alt.Scale(domainMin=0)),
                    color=alt.Color(
                        "mode:N",
                        title="Tegund",
                        scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                    ),
                    tooltip=[
                        alt.Tooltip("problem_order:Q", title="Dæmanúmer", format=".0f"),
                        alt.Tooltip("mode:N", title="Tegund"),
                        alt.Tooltip("avg_attempts:Q", title="Meðalfjöldi fyrirspurna", format=".2f"),
                    ],
                )
            )

        if "overall" in selected_lines and not attempts_trend_df.empty:
            layers.append(
                alt.Chart(attempts_trend_df)
                .mark_line(strokeDash=[6, 4], color=THEME["text_secondary"], point=True)
                .encode(
                    x=alt.X("problem_order:Q", axis=alt.Axis(format="d")),
                    y=alt.Y("avg_attempts:Q"),
                    tooltip=[
                        alt.Tooltip("problem_order:Q", title="Dæmanúmer", format=".0f"),
                        alt.Tooltip("avg_attempts:Q", title="Meðafjöldi fyrirspurna", format=".2f"),
                    ],
                )
            )

        if not layers:
            st.info("Veldu að minnsta kosti eina tegund.")
        else:
            combined_chart = layers[0]
            for layer in layers[1:]:
                combined_chart = combined_chart + layer
            st.altair_chart(themed_chart(combined_chart), use_container_width=True)

with right_col:
    with st.container(border=True, key="section-problem-figures"):
        st.subheader("Tölfræði varðandi dæmi")
        st.caption(
            f"Núverandi: {start_date.isoformat()} to {end_date.isoformat()} | "
            f"Undanfarandi: {prev_start_date.isoformat()} to {prev_end_date.isoformat()}"
        )

        delta_overall, signal_overall = metric_delta_text(
            problem_kpis["avg_attempts_overall"],
            problem_kpis_prev["avg_attempts_overall"],
        )
        delta_hint, signal_hint = metric_delta_text(
            problem_kpis["avg_attempts_hint"],
            problem_kpis_prev["avg_attempts_hint"],
        )
        delta_reveal, signal_reveal = metric_delta_text(
            problem_kpis["avg_attempts_reveal"],
            problem_kpis_prev["avg_attempts_reveal"],
        )
        delta_incorrect, signal_incorrect = metric_delta_text(
            problem_kpis["avg_incorrect_overall"],
            problem_kpis_prev["avg_incorrect_overall"],
        )
        delta_check_solution, signal_check_solution = metric_delta_text(
            problem_kpis["avg_attempts_check_solution"],
            problem_kpis_prev["avg_attempts_check_solution"],
        )
        delta_finished_ratio, signal_finished_ratio = metric_delta_text(
            problem_kpis["finished_problem_ratio"] * 100.0,
            problem_kpis_prev["finished_problem_ratio"] * 100.0,
        )

        kpi_col1, kpi_col2 = st.columns(2)
        with kpi_col1:
            st.metric(
                "Meðalfjöldi fyrirspurna á dæmi (Heild)",
                f"{problem_kpis['avg_attempts_overall']:.2f}",
                delta=f"{delta_overall} ({signal_overall})",
                help=(
                    f"Núverandi: {problem_kpis['avg_attempts_overall']:.2f}, "
                    f"Undanfarandi: {problem_kpis_prev['avg_attempts_overall']:.2f}, "
                    f"Breyting: {delta_overall}"
                ),
            )
            st.metric(
                "Meðalfjöldi fyrirspurna á dæmi (Hint)",
                f"{problem_kpis['avg_attempts_hint']:.2f}",
                delta=f"{delta_hint} ({signal_hint})",
                help=(
                    f"Núverandi: {problem_kpis['avg_attempts_hint']:.2f}, "
                    f"Undanfarandi: {problem_kpis_prev['avg_attempts_hint']:.2f}, "
                    f"Breyting: {delta_hint}"
                ),
            )
            st.metric(
                "Meðalfjöldi fyrirspurna á dæmi (Reveal)",
                f"{problem_kpis['avg_attempts_reveal']:.2f}",
                delta=f"{delta_reveal} ({signal_reveal})",
                help=(
                    f"Núverandi: {problem_kpis['avg_attempts_reveal']:.2f}, "
                    f"Undanfarandi: {problem_kpis_prev['avg_attempts_reveal']:.2f}, "
                    f"Breyting: {delta_reveal}"
                ),
            )
        with kpi_col2:
            st.metric(
                "Meðalfjöldi villa á dæmi",
                f"{problem_kpis['avg_incorrect_overall']:.2f}",
                delta=f"{delta_incorrect} ({signal_incorrect})",
                help=(
                    f"Núverandi: {problem_kpis['avg_incorrect_overall']:.2f}, "
                    f"Undanfarandi: {problem_kpis_prev['avg_incorrect_overall']:.2f}, "
                    f"Breyting: {delta_incorrect}"
                ),
            )
            st.metric(
                "Meðalfjöldi fyrirspurna á dæmi (Check Solution)",
                f"{problem_kpis['avg_attempts_check_solution']:.2f}",
                delta=f"{delta_check_solution} ({signal_check_solution})",
                help=(
                    f"Núverandi: {problem_kpis['avg_attempts_check_solution']:.2f}, "
                    f"Undanfarandi: {problem_kpis_prev['avg_attempts_check_solution']:.2f}, "
                    f"Breyting: {delta_check_solution}"
                ),
            )
            st.metric(
                "Hlutfall kláraðra dæma",
                f"{problem_kpis['finished_problem_ratio'] * 100.0:.1f}%",
                delta=f"{delta_finished_ratio} pp ({signal_finished_ratio})",
                help=(
                    f"Hlutfall dæma sem hafa fyrirspurn með niðurstöðunni 'fully_solved'"
                    f"Núverandi: {problem_kpis['finished_problem_ratio'] * 100.0:.1f}%, "
                    f"Undanfarandi: {problem_kpis_prev['finished_problem_ratio'] * 100.0:.1f}%, "
                    f"Breyting: {delta_finished_ratio} percentage points"
                ),
            )

    with st.container(border=True, key="section-feedback-trend"):
        st.subheader("Þróun endurgjafar")
        st.caption("Fjöldi jákvæðra endurgjafa fyrir ofan 0, fjöldi neikvæðra endurgjafa fyrir neðan 0")
        feedback_diverging_df = pd.concat(
            [
                feedback_df[["day", "ups"]].rename(columns={"ups": "count"}).assign(rating="up", signed_count=feedback_df["ups"]),
                feedback_df[["day", "downs"]].rename(columns={"downs": "count"}).assign(rating="down", signed_count=-feedback_df["downs"]),
            ],
            ignore_index=True,
        )
        feedback_chart = (
            alt.Chart(feedback_diverging_df)
            .mark_bar()
            .encode(
                x=alt.X("day:T", title="Dagsetning"),
                y=alt.Y("signed_count:Q", title="Fjöldi endurgjafa"),
                color=alt.Color(
                    "rating:N",
                    title="Endurgjöf",
                    scale=alt.Scale(
                        domain=["up", "down"],
                        range=[THEME["primary"], THEME["error"]],
                    ),
                ),
                xOffset=alt.XOffset("rating:N"),
                tooltip=[
                    alt.Tooltip("day:T", title="Dagsetning"),
                    alt.Tooltip("rating:N", title="Endurgjöf"),
                    alt.Tooltip("count:Q", title="Fjöldi"),
                ],
            )
        )
        zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=THEME["text_secondary"]).encode(y="y:Q")
        st.altair_chart(themed_chart(feedback_chart + zero_rule), use_container_width=True)

        st.markdown("**Skriflegar endurgjafir notenda**")
        if feedback_comments:
            with st.expander(f"Sýna endurgjafir ({len(feedback_comments)})", expanded=False):
                for idx, comment in enumerate(feedback_comments, start=1):
                    st.write(f"{idx}. {comment}")

            show_summary = st.toggle(
                "Sýna samantekt",
                value=False,
                key="show_comment_summary_toggle",
            )
            if show_summary:
                if comment_summary_error:
                    st.error(f"Tókst ekki að taka saman endurgjafir: {comment_summary_error}")
                elif comment_summary_text:
                    st.markdown("**Samantekt**")
                    st.write(comment_summary_text)
                else:
                    st.warning("Engin samantekt fékkst frá summarize_review.")
        else:
            st.info("Engin endurgjöf fannst á tímabili.")

ratio_left, ratio_right = st.columns(2)

with ratio_left:
    with st.container(border=True, key="section-finished-ratio-ordinal"):
        st.subheader("Hlutfall kláraðra dæma eftir dæmanúmeri")
        ordinal_chart = (
            alt.Chart(finished_ratio_ordinal_df)
            .mark_line(point=True, color=THEME["logo_mid"])
            .encode(
                x=alt.X("problem_order:Q", title="Dæmanúmer", axis=alt.Axis(format="d")),
                y=alt.Y("finished_ratio:Q", title="Hlutfall kláraðra", scale=alt.Scale(domain=[0, 1])),
                tooltip=[
                    alt.Tooltip("problem_order:Q", title="Dæmanúmer", format=".0f"),
                    alt.Tooltip("finished_ratio:Q", title="Hlutfall kláraðra", format=".1%"),
                ],
            )
        )
        st.altair_chart(themed_chart(ordinal_chart), use_container_width=True)

with ratio_right:
    with st.container(border=True, key="section-finished-ratio-day"):
        st.subheader("Hlutfall kláraðra dæma eftir degi")
        day_chart = (
            alt.Chart(finished_ratio_day_df)
            .mark_line(point=True, color=THEME["logo_dark"])
            .encode(
                x=alt.X("day:T", title="Dagsetning"),
                y=alt.Y("finished_ratio:Q", title="Hlutfall kláraðra", scale=alt.Scale(domain=[0, 1])),
                tooltip=[
                    alt.Tooltip("day:T", title="Dagsetning"),
                    alt.Tooltip("finished_ratio:Q", title="Hlutfall kláraðra", format=".1%"),
                ],
            )
        )
        st.altair_chart(themed_chart(day_chart), use_container_width=True)

solve_left, errors_right = st.columns(2)

with solve_left:
    with st.container(border=True, key="section-first-solve-kpis"):
        st.subheader("Tölfræði fyrir fyrsta dæmi notenda")
        st.metric(
            "Miðgildi fyrirspurna til þess að leysa dæmi",
            f"{first_solve_kpis['median_attempts_to_first_solve']:.1f}",
            help="Miðgildi fyrirspurna til þess að leysa dæmi, frá fyrstu fyrirspurn þar til fyrirspurn skilar fully_solved",
        )
        st.metric(
            "Miðgildi tíma til þess að leysa dæmi (mínútur)",
            f"{first_solve_kpis['median_minutes_to_first_solve']:.1f}",
            help="Miðgildi tíma frá því að dæmi er búið til þangað til fyrirspurn skilar niðurstöðu fully_solved.",
        )
        st.metric(
            "Hlutfall kláraðra dæma",
            f"{first_solve_kpis['first_problem_completion_rate'] * 100.0:.1f}%",
            help=(
                "Fyrir notenda sem gerðu fyrsta dæmið sitt á þessu "
                "tímabili, hlutfall dæma með fyrirspurn sem vore "
                "kláruð."
            ),
        )
        st.metric(
            "Meðal ánægja með fyrirspurnir á fyrsta dæmi",
            f"{first_solve_kpis['first_problem_mean_satisfaction']:.2f}",
            help=(
                "Skali -1..1 reiknað einungis á fyrstu dæmum notenda "
                "(#up - #down) / (#up + #down)."
            ),
        )

    with st.container(border=True, key="section-hint-fix-rates"):
        st.subheader("Gæði vísbendinga og tíðni lagfæringa")
        st.metric(
            "Hlutfall góðra vísbending",
            f"{hint_fix_kpis['useful_hint_ratio'] * 100.0:.1f}%",
            help=(
                "Góð vísbending ef fyrirspurn seinna í dæmi skilar fully_solved eða correct_so_far"
            ),
        )
        st.metric(
            "Hlutfall lagfærðra dæma",
            f"{hint_fix_kpis['unclear_fix_rate'] * 100.0:.1f}%",
            help=(
                "Ef dæmi unclear hversu oft er það lagað (clear fyrirspurn eftir að fá unclear)"
            ),
        )

with errors_right:
    with st.container(border=True, key="section-top-error-types"):
        st.subheader("Helstu villugerðir")
        error_chart = (
            alt.Chart(top_error_types_df)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, color=THEME["logo_mid"])
            .encode(
                x=alt.X("error_type:N", title="Villugerð", sort="-y", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("count:Q", title="Fyrirspurnir", scale=alt.Scale(domainMin=0)),
                tooltip=[
                    alt.Tooltip("error_type:N", title="Villugerð"),
                    alt.Tooltip("count:Q", title="Fjöldi"),
                ],
            )
        )
        st.altair_chart(themed_chart(error_chart), use_container_width=True)

with st.container(border=True, key="section-unclear-by-day"):
    st.subheader("Hlutfall óskýrra fyrirspurna eftir dagsetningu")
    unclear_chart = (
        alt.Chart(unclear_attempts_df)
        .mark_line(point=True, color=THEME["error"])
        .encode(
            x=alt.X("day:T", title="Dagsetning"),
            y=alt.Y("unclear_ratio:Q", title="Hlutfall óskýrra fyrirspurna", scale=alt.Scale(domain=[0, 1])),
            tooltip=[
                alt.Tooltip("day:T", title="Dagsetning"),
                alt.Tooltip("unclear_attempts:Q", title="Óskýrar fyrirspurnir"),
                alt.Tooltip("total_attempts:Q", title="Heildar fyrirspurnir"),
                alt.Tooltip("unclear_ratio:Q", title="Hlutfall", format=".2%"),
            ],
        )
    )
    st.altair_chart(themed_chart(unclear_chart), use_container_width=True)

#Latency section (all requested views) in one bounding box
with st.container(border=True, key="section-latency"):
    st.subheader("Greining biðtíma")

    if latency_df.empty:
        st.info("Engin gögn fundust um biðtíma.")
    else:
        latency_mode_filter = st.multiselect(
            "Latency modes",
            options=MODE_ORDER,
            default=MODE_ORDER,
            key="latency_mode_filter",
        )

        filtered_latency = latency_df[latency_df["mode"].isin(latency_mode_filter)] if latency_mode_filter else latency_df.iloc[0:0]

        l1, l2 = st.columns(2)

        with l1:
            st.markdown("**Þróun P50 / P95 biðtíma eftir tegund fyrirspurnar**")
            percentiles = latency_percentiles_by_day_and_mode(filtered_latency)
            if percentiles.empty:
                st.info("Enginn biðtími fyrir valda tegund.")
            else:
                p50 = percentiles[["day", "mode", "p50_ms"]].rename(columns={"p50_ms": "latency_ms"})
                p50["percentile"] = "p50"
                p95 = percentiles[["day", "mode", "p95_ms"]].rename(columns={"p95_ms": "latency_ms"})
                p95["percentile"] = "p95"
                trend_df = pd.concat([p50, p95], ignore_index=True)
                trend_chart = (
                    alt.Chart(trend_df)
                    .mark_line(point=False)
                    .encode(
                        x=alt.X("day:T", title="Dagsetning"),
                        y=alt.Y("latency_ms:Q", title="Biðtími (ms)", scale=alt.Scale(domainMin=0)),
                        color=alt.Color(
                            "mode:N",
                            scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                            title="Mode",
                        ),
                        strokeDash=alt.StrokeDash("percentile:N", title="Percentile"),
                        tooltip=[
                            alt.Tooltip("day:T", title="Dagsetning"),
                            alt.Tooltip("mode:N", title="Tegund"),
                            alt.Tooltip("percentile:N", title="Hundraðshlutamark"),
                            alt.Tooltip("latency_ms:Q", title="Biðtími (ms)", format=",.0f"),
                        ],
                    )
                )
                st.altair_chart(themed_chart(trend_chart), use_container_width=True)

        with l2:
            st.markdown("**Dreifing biðtíma**")
            hist_chart = (
                alt.Chart(filtered_latency)
                .mark_bar(opacity=0.75, color=THEME["primary"])
                .encode(
                    x=alt.X("latency_ms:Q", bin=alt.Bin(maxbins=30), title="Biðtími (ms)"),
                    y=alt.Y("count():Q", title="Fjöldi fyrirspurna"),
                    tooltip=[alt.Tooltip("count():Q", title="Fjöldi fyrirspurna")],
                )
            )
            st.altair_chart(themed_chart(hist_chart), use_container_width=True)

        l3, l4 = st.columns(2)

        with l3:
            st.markdown("**Biðtími eftir tegund**")
            box_chart = (
                alt.Chart(filtered_latency)
                .mark_boxplot(size=40)
                .encode(
                    x=alt.X("mode:N", title="Mode", sort=MODE_ORDER, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("latency_ms:Q", title="Biðtími (ms)", scale=alt.Scale(domainMin=0)),
                    color=alt.Color(
                        "mode:N",
                        scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                        title="Tegund",
                    ),
                    tooltip=[alt.Tooltip("mode:N", title="Tegund")],
                )
            )
            st.altair_chart(themed_chart(box_chart), use_container_width=True)

        with l4:
            st.markdown("**Biðtími vs Fjöldi tóka**")
            scatter_base = filtered_latency.dropna(subset=["tokens_total"])
            scatter = (
                alt.Chart(scatter_base)
                .mark_circle(size=55, opacity=0.5)
                .encode(
                    x=alt.X("tokens_total:Q", title="Fjöldi tókas"),
                    y=alt.Y("latency_ms:Q", title="Biðtími (ms)", scale=alt.Scale(domainMin=0)),
                    color=alt.Color(
                        "mode:N",
                        scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                        title="Mode",
                    ),
                    tooltip=[
                        alt.Tooltip("mode:N", title="Tegund"),
                        alt.Tooltip("tokens_total:Q", title="Fjöldi tóka", format=",.0f"),
                        alt.Tooltip("latency_ms:Q", title="Biðtími (ms)", format=",.0f"),
                    ],
                )
            )
            trend = scatter.transform_regression("tokens_total", "latency_ms").mark_line(color=THEME["text_primary"])
            st.altair_chart(themed_chart(scatter + trend), use_container_width=True)

        st.markdown("**SLO compliance (% requests under threshold) by mode**")
        slo_df = build_slo_df(filtered_latency)
        slo_chart = (
            alt.Chart(slo_df)
            .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
            .encode(
                x=alt.X("threshold:N", title="Threshold"),
                y=alt.Y("pct:Q", title="Requests Within Threshold (%)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color(
                    "mode:N",
                    scale=alt.Scale(domain=MODE_ORDER, range=[MODE_COLORS[m] for m in MODE_ORDER]),
                    title="Mode",
                ),
                xOffset="mode:N",
                tooltip=[
                    alt.Tooltip("mode:N", title="Mode"),
                    alt.Tooltip("threshold:N", title="Threshold"),
                    alt.Tooltip("pct:Q", title="Percent", format=".1f"),
                ],
            )
        )
        st.altair_chart(themed_chart(slo_chart), use_container_width=True)
