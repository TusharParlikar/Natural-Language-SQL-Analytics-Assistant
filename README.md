# Natural-Language SQL Analytics Assistant

Ask business questions in plain English and get answers from a SQL database, shown as tables and charts.

> "Which 5 countries brought in the most revenue?" → SQL → answer + bar chart + table

## Aim

Make a multi-table database usable by people who don't know SQL. The assistant should give correct answers, and it must never change or damage the data.

## Objectives

1. **Text-to-SQL:** turn a question into a valid SQLite query using schema-aware prompting and LLM function calling.
2. **Safe execution:** run only read-only, validated SQL. If a query fails, send the error back to the model and retry.
3. **Clear results:** show results as a table plus an automatic chart in a Streamlit app, together with the SQL that produced them.
4. **Measured accuracy:** report execution accuracy on a hand-written set of question–SQL pairs.

## How it works

```
Question ──► Schema-aware prompt ──► LLM (function call: run_sql)
                                          │
                                          ▼
                                  Guardrails: validate → read-only execute
                                          │
                         error? ◄─────────┤
                  (feed error back,        ▼
                   retry ≤ 2 times)    Pandas DataFrame ──► Streamlit table + chart
```

1. **Schema context:** table names, columns, types, foreign keys and 3 sample rows per table are read from SQLite and put into the system prompt.
2. **Function calling:** the model gets one tool, `run_sql(query)`. It writes SQL by calling the tool, so we never have to parse SQL out of free text.
3. **Guardrails:**
   - SQL is parsed with `sqlglot`. Only a single `SELECT` / `WITH` statement is allowed, and DDL/DML is rejected.
   - The database is opened read-only (`file:...?mode=ro` plus `PRAGMA query_only = ON`).
   - `LIMIT 1000` is added when a query has no limit, and queries are stopped after 5 seconds.
   - When a query fails, the error goes back to the model, which can retry up to 2 times.
4. **Display:** Pandas DataFrame → `st.dataframe` plus a chart chosen from the result's shape (time series → line chart, category + number → bar chart).

## Tech stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| Database | SQLite ([Chinook](https://github.com/lerocha/chinook-database) sample DB, 11 tables) |
| LLM | Claude API, `claude-opus-5-5` (tool use, server-side refusal fallback) |
| SQL validation | sqlglot |
| Data | Pandas |
| UI | Streamlit |

## Project structure

```
├── app.py              # Streamlit UI
├── assistant.py        # schema extraction, prompt, LLM tool loop
├── guard.py            # SQL validation + read-only execution (+ self-checks)
├── eval.py             # execution-accuracy evaluation + unsafe-prompt check
├── data/
│   ├── chinook.db
│   └── eval_set.json   # hand-written question–SQL pairs
├── requirements.txt
└── PLAN.md             # phased build plan
```

## Quick start

```bash
git clone https://github.com/TusharParlikar/Natural-Language-SQL-Analytics-Assistant.git
cd Natural-Language-SQL-Analytics-Assistant
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
set ANTHROPIC_API_KEY=your-key      # PowerShell: $env:ANTHROPIC_API_KEY="your-key"; macOS/Linux: export ANTHROPIC_API_KEY=your-key
streamlit run app.py
```

Ask a single question from the terminal:

```bash
python assistant.py "Top 5 countries by total revenue"
```

Run the checks (no API key needed) and the evaluation:

```bash
python guard.py           # guardrail self-checks
python assistant.py       # schema extraction self-check
python eval.py            # execution accuracy, with retry
python eval.py --no-retry # without retry, for comparison
```

To use a different model, change `MODEL` in `assistant.py`.

### Deploy (optional)

On [Streamlit Community Cloud](https://streamlit.io/cloud), point a new app at `app.py` and add `ANTHROPIC_API_KEY = "..."` under **Secrets**. Streamlit makes top-level secrets available as environment variables, which is where the Anthropic client reads the key.

## Evaluation

**Execution accuracy** is the share of questions where the generated SQL returns the same result as the hand-written reference SQL. A result counts as correct when it has the same number of rows and contains every reference column, ignoring row order and column names, with numbers rounded to 2 decimals. Extra columns are allowed, such as a name shown next to an ID.

The eval set ([data/eval_set.json](data/eval_set.json)) has 32 questions: 10 easy (one table), 12 medium (joins, group by, dates) and 10 hard (subqueries, CTEs, window functions, percentages). Six unsafe prompts ("delete all customers", "drop the Invoice table", prompt injection, `PRAGMA`) check that the database stays unchanged. Failed questions are written to `eval_failures.json`.

| Metric | Result |
|---|---|
| Questions in eval set | 32 (10 easy / 12 medium / 10 hard) |
| Execution accuracy | _TBD_ |
| Accuracy with retry vs. without | _TBD_ |
| Database unchanged after unsafe prompts | _TBD_ |

## Example questions

- What are the top 10 best-selling tracks by revenue?
- Monthly revenue for 2012.
- Which employee supports the customers with the highest total spend?
- Average invoice value per country, highest first.

## Limitations

- Only one database at a time, and the schema must fit in the prompt.
- Questions that need data outside the database can't be answered.
- Accuracy is measured on a small hand-written set, not on a public benchmark such as Spider or BIRD.
- Each question is answered on its own, with no memory of earlier questions.
- The result checker compares columns independently, so it is more lenient than strict row-by-row matching.

## Roadmap

See [PLAN.md](PLAN.md).
