# Build Plan: Natural-Language SQL Analytics Assistant

**Aim:** a Streamlit app that answers business questions over a multi-table SQLite database. It turns each question into safe, read-only SQL and shows the results as tables and charts, and its accuracy is measured.

**Final deliverable:** a working app, an evaluation script with an accuracy number, and a README with results and screenshots.

---

## Phase 0: Setup ✅

**Objective:** set up the repo and environment.

- [x] Create the GitHub repo and push the first commit
- [x] Create a virtual env: `python -m venv .venv`
- [x] Write `requirements.txt`: `anthropic`, `streamlit`, `pandas`, `sqlglot`
- [x] Add `.gitignore` (`.venv/`, `__pycache__/`, `.env`)
- [x] LLM settings in `.env` (git-ignored): Ollama `qwen3:1.7b` locally, any OpenAI-compatible provider by editing `.env`

**Done when:** `pip install -r requirements.txt` works and the key loads from the environment.

---

## Phase 1: Database and schema extraction ✅

**Objective:** give the LLM an accurate, compact picture of the database.

- [x] Download `chinook.db` into `data/`
- [x] Write `get_schema(db_path)` in `assistant.py` using `sqlite_master` and `PRAGMA table_info` / `PRAGMA foreign_key_list`
- [x] Add 3 sample rows per table, so the model sees real value formats such as dates and country names
- [x] Format all of it as compact `CREATE TABLE`-style text

**Done when:** printing the schema shows all 11 tables with their columns, foreign keys and sample rows.

---

## Phase 2: Text-to-SQL core with function calling 🟡 (live-tested on Ollama; 10-question check pending)

**Objective:** question in, SQL and a result DataFrame out.

- [x] System prompt: role + schema + rules (SQLite dialect, use only listed tables and columns, always call `run_sql`)
- [x] Define one tool: `run_sql(query: str)`
- [x] Tool loop: send the question → model calls `run_sql` → run it → return the result → model writes a short answer
- [x] Return `(sql, dataframe, answer_text)`
- [ ] Try 10 questions by hand from the CLI

**Done when:** at least 7 of 10 hand-tested questions return correct results.

---

## Phase 3: Guardrails ✅

**Objective:** make the assistant safe and self-correcting.

- [x] `guard.py` → `validate(sql)`: parse with `sqlglot`, allow only a single `SELECT`/`WITH`, reject `INSERT/UPDATE/DELETE/DROP/ALTER/ATTACH/PRAGMA`
- [x] Open the DB read-only: `sqlite3.connect("file:data/chinook.db?mode=ro", uri=True)` + `PRAGMA query_only = ON`
- [x] Add `LIMIT 1000` when the query has no limit
- [x] Query timeout using `conn.set_progress_handler`
- [x] Retry: on a validation or execution error, return the error text to the model as the tool result and allow at most 2 retries
- [x] Self-check: asserts proving that `DROP TABLE`, `DELETE`, multiple statements and `ATTACH` are blocked

**Done when:** malicious prompts ("delete all customers") never change the DB, and the retry fixes at least some broken queries.

---

## Phase 4: Streamlit UI ✅ (tested with stubbed LLM)

**Objective:** a clean app that non-technical users can use.

- [x] `app.py`: question box, submit button, and spinner
- [x] Show the answer text, the result table (`st.dataframe`) and the generated SQL (in an expander)
- [x] Auto chart: date column + number → `st.line_chart`; text column + number → `st.bar_chart`; otherwise table only
- [x] Sidebar: example questions and a schema viewer
- [x] Friendly error message when every retry fails
- [x] Cache the schema with `@st.cache_data`

**Done when:** `streamlit run app.py` answers the example questions with tables and charts.

---

## Phase 5: Evaluation 🟡 (32 pairs + script done, live run pending)

**Objective:** measure accuracy with real numbers.

- [x] Write `data/eval_set.json` with 30–50 `{question, sql}` pairs: easy (1 table), medium (joins and group by), hard (subqueries, dates, ranking)
- [x] `eval.py`: for each pair, run the gold SQL and the generated SQL, then compare result sets (gold columns found in output, order-insensitive, values rounded to 2 dp)
- [x] Report overall and per-difficulty accuracy, with and without retry
- [x] Add 5–10 unsafe prompts and report the block rate
- [ ] Log the failures and fix the prompt where possible (few-shot examples, clearer rules)

**Done when:** `python eval.py` prints a results table and the numbers go into the README.

---

## Phase 6: Polish and ship 🟡 (waiting on live results)

**Objective:** make it presentable for a portfolio or resume.

- [ ] Fill in the README results table and add screenshots or a GIF
- [x] Clean up code comments and pin requirement versions
- [ ] Optional: deploy to Streamlit Community Cloud with a hosted provider's settings in secrets (steps in README)
- [ ] Final commit and push

**Done when:** a stranger can clone the repo, run the app in under 5 minutes and see the accuracy numbers.

---

## Phase 7: Bring your own data ✅

**Objective:** let users ask questions about their own files, not only the sample database.

- [x] Sidebar choice: sample database or upload
- [x] Upload CSV (one table per file), Excel (one table per sheet) or a single SQLite file (used as-is)
- [x] Clean file, sheet and column names into plain SQL names, and de-duplicate them
- [x] Same guardrails on uploaded data (read-only, validated, limited)
- [x] `ARCHITECTURE.md` describing inputs, outputs and data flow

**Done when:** a user uploads a CSV and gets a correct answer to "total sales by region" (verified live on Ollama `qwen3:1.7b`).

---

## Timeline (suggested)

| Phase | Effort |
|---|---|
| 0 Setup | 0.5 day |
| 1 Schema | 0.5 day |
| 2 Core | 1–2 days |
| 3 Guardrails | 1 day |
| 4 UI | 1 day |
| 5 Evaluation | 1–2 days |
| 6 Polish | 0.5 day |

**Total:** about 1 week part-time.

## Out of scope (add later if needed)

- Querying several databases at once
- Postgres/MySQL support
- Conversation memory and follow-up questions
- Users and authentication
