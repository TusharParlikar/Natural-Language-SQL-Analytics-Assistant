import json
import os
import re
import sqlite3
import sys
from pathlib import Path

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
        rows = "\n".join(" | ".join(map(str, r)) for r in cur.fetchall())
        parts.append(f"CREATE TABLE {t} (\n" + ",\n".join(cols + fks) + "\n);\n"
                     f"/* sample rows:\n{header}\n{rows}\n*/")
    conn.close()
    return "\n\n".join(parts)


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


def ask(question, schema=None, max_retries=MAX_RETRIES):
    """Question -> {"sql", "df", "answer", "error"} using OpenAI-compatible tool calling."""
    global _client
    _client = _client or OpenAI(base_url=BASE_URL, api_key=API_KEY)
    messages = [{"role": "system", "content": system_prompt(schema or get_schema())},
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
                result_df = run_query(query)
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
    if len(sys.argv) > 1:  # python assistant.py "your question"
        r = ask(" ".join(sys.argv[1:]))
        print("SQL:", r["sql"], "\n", r["df"], "\n\n", r["answer"] or r["error"], sep="")
    else:
        s = get_schema()
        assert s.count("CREATE TABLE") == 11, "expected 11 Chinook tables"
        assert "FOREIGN KEY (CustomerId) REFERENCES Customer(CustomerId)" in s
        print(s)
        print(f"\n{len(s)} chars")
