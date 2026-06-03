# Prompt Versioning

This backend keeps prompt variants on disk so `/query` behavior can be changed with environment
settings instead of route rewrites. The source of truth for prompt resolution is
`backend/routes/query.py`.

## Prompt Sets

- `modes/`
  - Main tutoring prompts for `hint`, `check_solution`, and `reveal`.
  - Current supported variants: `v1`, `v2`, `v3`, `v4`, `v5`, `v6`.
  - Runtime path shape: `modes/{variant}/{mode}/prompt.txt`.
- `modes_expert/`
  - Expert-mode prompts for stricter `check_solution` behavior.
  - Current supported variants: `v2`, `v3`, `v4`.
  - Runtime path shape: `modes_expert/{variant}/{clarity|strict}/check_solution/prompt.txt`.
- `legibility/`
  - Dedicated first-pass prompts for unclear handwriting detection.
  - Current supported variants: `v2`, `v3`, `v4`.
  - Runtime path shape: `legibility/{variant}/prompt.txt`.
- `errors/`
  - Deferred error-categorization prompts used after incorrect attempts.
  - Current route uses `errors/v4/prompt.txt`.
- `exam/`
  - Exam item generation, validation, and grading prompt families.
  - Exam route currently combines prompt files with template/rule-based generation and grading logic.

## Runtime Defaults

Current defaults in `backend/routes/query.py`:

- `QUERY_PROMPT_VARIANT=v6`
- `QUERY_EXPERT_PROMPT_VARIANT=v4`
- `QUERY_LEGIBILITY_PROMPT_VARIANT=v4`
- `QUERY_PIPELINE_MODE=two_pass`

If an unsupported mode prompt variant is configured, the resolver falls back to `v6`.
If an unsupported expert or legibility variant is configured, the resolver falls back to `v4`.

## Query Pipeline

`POST /query` accepts:

- `mode`: `hint`, `check_solution`, or `reveal`
- `pipeline_mode`: `two_pass` or `single_pass`
- `expert_mode`: `off`, `clarity`, or `strict`
- `confirmed_reading_json`: optional corrected reading from the user

Pipeline behavior:

- `two_pass` runs a legibility pass before the tutoring/reasoning pass.
- `single_pass` skips legibility and calls the mode prompt directly.
- If `confirmed_reading_json` is supplied, legibility is skipped and the confirmed text is injected into the reasoning prompt.
- If legibility finds uncertain but interpretable handwriting, the backend returns `response_type=confirm_reading`.
- If handwriting is too ambiguous to build an interpreted reading, the backend returns `response_type=ask_clarification`.

## Expert Mode

Expert prompts only apply when:

- `mode=check_solution`
- `expert_mode` is not `off`
- the resolved expert prompt file exists

Otherwise, the backend uses the normal mode prompt from `modes/{variant}/{mode}/prompt.txt`.

## Response Contracts

The Gemini calls are schema-constrained in `backend/llm.py`.

- Main tutoring response:
  - `verdict`
  - `response_type`
  - `message_is`
- Legibility response:
  - `all_readable`
  - `reading_confidence`
  - `ambiguous_steps`
- Deferred error response:
  - `topic`
  - `subtopic`
  - `wrong_step`
  - `correct_step`
  - `error_type`
  - optional `error_box`
  - `confidence`

The route may add metadata such as `expert_mode` and `observability` before returning to the
frontend.

## Notes

- `two_pass` is safer for unreadable handwriting but adds latency.
- `single_pass` is lower latency but less robust against unreadable-input failure cases.
- Prompt version names returned in observability are derived from the resolved prompt file path.
- Check `backend/routes/query.py` for the exact runtime resolver before adding new prompt variants.
