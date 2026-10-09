import io
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd
from openai import OpenAI

from guard import run_query

# Load KEY=VALUE lines from .env; real environment variables win.
_env = Path(__file__).with_name(".env")
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

DB_PATH = "data/chinook.db"
# Any OpenAI-compatible endpoint: Ollama (default), OpenAI, Groq, Together, LM Studio, vLLM, Gemini, Claude...
BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
API_KEY = os.environ.get("LLM_API_KEY", "ollama")
MODEL = os.environ.get("LLM_MODEL", "qwen3:1.7b")
TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT", "120"))  # per LLM request; slow CPU models may need more
MAX_RETRIES = 2  # failed SQL attempts allowed before giving up
MAX_TURNS = 6  # stops a model that keeps calling the tool without answering

RUN_SQL_TOOL = {"type": "function", "function": {
    "name": "run_sql",
    "description": "Run one read-only SQLite SELECT query against the database and get the result rows back as CSV.",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A single SQLite SELECT statement."}},
        "required": ["query"],
    },
}}


def get_schema(db_path=DB_PATH, sample_rows=3):
    """Compact CREATE TABLE-style schema with foreign keys and sample rows, for the LLM prompt."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    parts = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        cols = [f"  {c[1]} {c[2]}{' PRIMARY KEY' if c[5] else ''}"
                for c in conn.execute(f'PRAGMA table_info("{t}")')]
        fks = [f"  FOREIGN KEY ({fk[3]}) REFERENCES {fk[2]}({fk[4]})"
               for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")')]
        cur = conn.execute(f'SELECT * FROM "{t}" LIMIT {sample_rows}')
        header = " | ".join(d[0] for d in cur.description)
        rows = "\n".join(" | ".join(str(v)[:50] for v in r) for r in cur.fetchall())  # cap long text
        parts.append(f"CREATE TABLE {t} (\n" + ",\n".join(cols + fks) + "\n);\n"
                     f"/* sample rows:\n{header}\n{rows}\n*/")
    conn.close()
    return "\n\n".join(parts)


def _identifier(name, fallback):
    """Turn a file, sheet or column name into a plain SQL name: 'Sales 2024' -> sales_2024."""
    name = re.sub(r"\W+", "_", str(name)).strip("_").lower() or fallback
    return f"t_{name}" if name[0].isdigit() else name


def is_sqlite(data):
    return data[:16] == b"SQLite format 3\x00"


def files_to_sqlite(files, db_path):
    """Load uploaded (filename, bytes) pairs into a new SQLite DB: each CSV and each Excel sheet
    becomes one table. Returns the table names."""
    frames = {}
    for filename, data in files:
        stem, ext = os.path.splitext(filename.lower())
        if ext == ".csv":
            frames[_identifier(stem, "data")] = pd.read_csv(io.BytesIO(data))
        elif ext in (".xlsx", ".xls"):
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
            for sheet, df in sheets.items():
                frames[_identifier(stem if len(sheets) == 1 else f"{stem}_{sheet}", "sheet")] = df
        else:
            raise ValueError(f"Unsupported file type: {filename}")
    conn = sqlite3.connect(db_path)
    try:
        for table, df in frames.items():
            seen, cols = {}, []
            for i, c in enumerate(df.columns, 1):
                c = _identifier(c, f"col{i}")
                seen[c] = seen.get(c, 0) + 1
                cols.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
            df.columns = cols
            df.to_sql(table, conn, index=False, if_exists="replace")
    finally:
        conn.close()
    return list(frames)


def table_names(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def load_table(db_path, table):
    with closing(sqlite3.connect(db_path)) as conn:
        return pd.read_sql(f'SELECT * FROM "{table}"', conn)


def save_table(db_path, table, df):
    """Replace a table's rows with df, keeping its column types and keys. Used for user edits, never by the LLM."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:  # one transaction: all rows saved or none
            conn.execute(f'DELETE FROM "{table}"')
            df.to_sql(table, conn, index=False, if_exists="append")
    finally:
        conn.close()


def drop_table(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(f'DROP TABLE "{table}"')
    finally:
        conn.close()


def system_prompt(schema):
    return f"""You are a data analyst answering business questions about a SQLite database.

Answer every question by calling the run_sql tool. Write SQLite-dialect SQL that uses only the tables and columns in the schema below, and alias computed columns with readable names. If a query returns an error, fix the SQL and call run_sql again.
After you get the rows back, reply with a short plain-English answer (1-3 sentences). If the question cannot be answered from this database, say so without calling the tool.

Schema:
{schema}"""


_client = None


def _clean(text):
    """Drop <think>...</think> blocks that some local reasoning models put in the reply."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def ask(question, schema=None, max_retries=MAX_RETRIES, db_path=DB_PATH):
    """Question -> {"sql", "df", "answer", "error"} using OpenAI-compatible tool calling."""
    global _client
    _client = _client or OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT_S, max_retries=3)  # retries 429 rate limits
    messages = [{"role": "system", "content": system_prompt(schema or get_schema(db_path))},
                {"role": "user", "content": question}]
    sql, df, failures, last_error = None, None, 0, None

    for _ in range(MAX_TURNS):
        msg = _client.chat.completions.create(model=MODEL, messages=messages, tools=[RUN_SQL_TOOL]).choices[0].message
        if not msg.tool_calls:
            return {"sql": sql, "df": df, "answer": _clean(msg.content), "error": None}

        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                query = json.loads(call.function.arguments)["query"]
                result_df = run_query(query, db_path)
                sql, df = query, result_df
                content = result_df.head(50).to_csv(index=False) or "(no rows)"
            except Exception as e:  # bad tool arguments, guardrail rejection, or SQLite error
                failures, last_error = failures + 1, str(e)
                content = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        if failures > max_retries:
            return {"sql": sql, "df": df, "answer": None,
                    "error": f"Query failed after {max_retries} retries: {last_error}"}

    return {"sql": sql, "df": df, "answer": None, "error": f"No final answer after {MAX_TURNS} model turns."}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # model replies can contain non-ASCII (Windows console)
    if len(sys.argv) > 1:  # python assistant.py "your question"
        r = ask(" ".join(sys.argv[1:]))
        print("SQL:", r["sql"], "\n", r["df"], "\n\n", r["answer"] or r["error"], sep="")
    else:
        s = get_schema()
        assert s.count("CREATE TABLE") == 11, "expected 11 Chinook tables"
        assert "FOREIGN KEY (CustomerId) REFERENCES Customer(CustomerId)" in s
        print(s)
        print(f"\n{len(s)} chars")
