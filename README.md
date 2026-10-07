# Natural-Language SQL Analytics Assistant

Ask business questions in plain English and get answers from a SQL database, shown as tables and charts. Use the built-in sample database, or **upload your own CSV, Excel or SQLite files**.

> "Which 5 countries brought in the most revenue?" → SQL → answer + bar chart + table

## Aim

Make a multi-table database usable by people who don't know SQL. The assistant should give correct answers, and it must never change or damage the data.

## Objectives

1. **Text-to-SQL:** turn a question into a valid SQLite query using schema-aware prompting and LLM function calling.
2. **Safe execution:** run only read-only, validated SQL. If a query fails, send the error back to the model and retry.
3. **Clear results:** show results as a table plus an automatic chart in a Streamlit app, together with the SQL that produced them.
4. **Your own data:** let users upload their own files and ask questions about them.
5. **Measured accuracy:** report execution accuracy on a hand-written set of question–SQL pairs.
6. **Any LLM:** run on a local model (Ollama) or any hosted provider by changing `.env` only.

## Features

- Plain-English questions in, SQL plus a short answer, chart and table out
- Two data sources:
  - **Sample:** the [Chinook](https://github.com/lerocha/chinook-database) music-store database (11 related tables)
  - **Upload:** CSV files, Excel workbooks (each sheet becomes a table) or a SQLite database file
- Read-only guardrails: SQL validation, read-only connection, row limit, timeout
- Self-correction: SQL errors go back to the model, which can retry up to 2 times
- Runs locally on Ollama (`qwen3:1.7b` by default), or on OpenAI, Groq, Gemini, Claude or any other OpenAI-compatible API
- Evaluation script with 32 question–SQL pairs and an unsafe-prompt check

## How it works

```
Data (sample DB or upload) ──► SQLite ──► Schema + sample rows ──► System prompt
                                                                        │
Question ───────────────────────────────────────────────────────────► LLM
                                                                        │ calls run_sql(query)
                                                                        ▼
                                              Guardrails: validate → read-only execute
                                                                        │
                                       error? → sent back to the LLM ◄──┤ (retry ≤ 2)
                                                                        ▼
                                          rows → LLM writes answer → Streamlit: answer + chart + table + SQL
```

1. **Load data:** the sample DB is used directly. Uploaded CSV and Excel files are loaded into a temporary SQLite database, with file, sheet and column names cleaned into simple SQL names (`Sales Amount ($)` → `sales_amount`).
2. **Schema context:** table names, columns, types, foreign keys and 3 sample rows per table go into the system prompt.
3. **Function calling:** the model gets one tool, `run_sql(query)`, so SQL never has to be parsed out of free text.
4. **Guardrails:** `sqlglot` allows only a single `SELECT`/`WITH` statement. The database is opened read-only, a `LIMIT 1000` is added when the query has none, and queries are stopped after 5 seconds.
5. **Answer:** the rows go back to the model, which writes a 1–3 sentence answer. The app picks a chart from the result's shape: line for dates, bar for categories.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design, with inputs, outputs, data flow and the decisions behind it.

## Tech stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| Database | SQLite (Chinook sample DB, or the user's uploaded data) |
| LLM | Any OpenAI-compatible chat API with tool calling (`openai` SDK). Local default: Ollama `qwen3:1.7b` |
| SQL validation | sqlglot |
| Data | Pandas (+ openpyxl for Excel) |
| UI | Streamlit |

## Project structure

```
├── app.py              # Streamlit UI: data source, upload, question box, results
├── assistant.py        # .env config, schema extraction, file → SQLite loading, LLM tool loop
├── guard.py            # SQL validation + read-only execution (+ self-checks)
├── eval.py             # execution-accuracy evaluation + unsafe-prompt check
├── data/
│   ├── chinook.db      # sample database
│   └── eval_set.json   # 32 hand-written question–SQL pairs
├── .env.example        # LLM settings template (copy to .env)
├── requirements.txt
├── ARCHITECTURE.md     # how it works in detail
└── PLAN.md             # phased build plan
```

## Quick start

```bash
git clone https://github.com/TusharParlikar/Natural-Language-SQL-Analytics-Assistant.git
cd Natural-Language-SQL-Analytics-Assistant
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # macOS/Linux: cp .env.example .env
ollama pull qwen3:1.7b             # local model (default in .env)
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

### Using your own data

1. In the sidebar, choose **Upload my own data**.
2. Upload one of these:
   - one or more **CSV** files (each becomes a table named after the file)
   - **Excel** workbooks (each sheet becomes a table, named `<file>_<sheet>` when there are several)
   - a single **SQLite** database file (`.db`, `.sqlite`, `.sqlite3`), used as-is
3. Open **Database schema** to see the table and column names the model will use, then ask your question.

Uploaded data is stored in a temporary file on the machine running the app. It is opened read-only for every query and is never changed. When you use a hosted LLM, the schema, 3 sample rows per table and query results are sent to that provider. With Ollama, everything stays on your machine.

### Terminal usage and checks

```bash
python assistant.py "Top 5 countries by total revenue"   # one question against the sample DB
python guard.py           # guardrail self-checks (no LLM needed)
python assistant.py       # schema extraction self-check (no LLM needed)
python eval.py            # execution accuracy, with retry
python eval.py --no-retry # without retry, for comparison
```

### Choosing the LLM

All LLM settings live in `.env`; no code changes are needed. Any provider with an OpenAI-compatible chat completions API and tool calling works:

| Setting | Meaning | Default |
|---|---|---|
| `LLM_BASE_URL` | API endpoint | `http://localhost:11434/v1` (Ollama) |
| `LLM_API_KEY` | Provider key | `ollama` |
| `LLM_MODEL` | Model name | `qwen3:1.7b` |

`.env.example` has ready-made lines for OpenAI, Groq, Gemini and Claude. Real environment variables override `.env`. Small local models are fine for simple questions. Hard multi-join questions work better with a larger model.

### Deploy (optional)

On [Streamlit Community Cloud](https://streamlit.io/cloud), point a new app at `app.py` and add `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` for a hosted provider under **Secrets**. Streamlit makes top-level secrets available as environment variables, which is where the app reads them. Ollama on your PC can't be reached from the cloud.

## Evaluation

**Execution accuracy** is the share of questions where the generated SQL returns the same result as the hand-written reference SQL. A result counts as correct when it has the same number of rows and contains every reference column, ignoring row order and column names, with numbers rounded to 2 decimals. Extra columns are allowed, such as a name shown next to an ID.

The eval set ([data/eval_set.json](data/eval_set.json)) has 32 questions on the sample database: 10 easy (one table), 12 medium (joins, group by, dates) and 10 hard (subqueries, CTEs, window functions, percentages). Six unsafe prompts ("delete all customers", "drop the Invoice table", prompt injection, `PRAGMA`) check that the database stays unchanged. Failed questions are written to `eval_failures.json`.

| Metric | Result |
|---|---|
| Questions in eval set | 32 (10 easy / 12 medium / 10 hard) |
| Execution accuracy | _TBD_ |
| Accuracy with retry vs. without | _TBD_ |
| Database unchanged after unsafe prompts | _TBD_ |

## Example questions

Sample database:
- What are the top 10 best-selling tracks by revenue?
- Monthly revenue for 2012.
- Which employee supports the customers with the highest total spend?
- Average invoice value per country, highest first.

Your own data, for example a sales CSV:
- Total sales by region.
- Which product had the highest revenue last month?
- How many orders per month in 2024?

## Limitations

- One data source at a time, and its schema must fit in the prompt (fine for tens of tables, not thousands).
- Uploaded CSV and Excel columns are stored with the types pandas infers. Dates are stored as text, which works with SQLite date functions when they are in `YYYY-MM-DD` form.
- Tables built from CSV or Excel uploads have no foreign keys, so the model has to infer joins from column names.
- Uploaded files are kept in the system temp folder and are not cleaned up automatically.
- Each question is answered on its own, with no memory of earlier questions.
- Accuracy is measured on a small hand-written set, not on a public benchmark such as Spider or BIRD. The result checker compares columns independently, so it is more lenient than strict row-by-row matching.

## Roadmap

See [PLAN.md](PLAN.md).
