import sqlite3
import sys

import anthropic

from guard import run_query

DB_PATH = "data/chinook.db"
MODEL = "claude-opus-5-5"
MAX_RETRIES = 2  # failed SQL attempts allowed before giving up

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": "Run one read-only SQLite SELECT query against the database and get the result rows back as CSV.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A single SQLite SELECT statement."}},
        "required": ["query"],
        "additionalProperties": False,
    },
}


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


def ask(question, schema=None, max_retries=MAX_RETRIES):
    """Question -> {"sql", "df", "answer", "error"} using Claude tool calling."""
    global _client
    _client = _client or anthropic.Anthropic()
    system = system_prompt(schema or get_schema())
    messages = [{"role": "user", "content": question}]
    sql, df, failures, last_error = None, None, 0, None

    while True:
        response = _client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            tools=[RUN_SQL_TOOL],
            messages=messages,
        )
        if response.stop_reason == "refusal":
            return {"sql": sql, "df": df, "answer": None, "error": "The model declined this request."}

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            answer = "".join(b.text for b in response.content if b.type == "text")
            return {"sql": sql, "df": df, "answer": answer, "error": None}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            try:
                result_df = run_query(tu.input["query"])
                sql, df = tu.input["query"], result_df
                content = result_df.head(50).to_csv(index=False) or "(no rows)"
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content})
            except Exception as e:
                failures, last_error = failures + 1, str(e)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"Error: {e}", "is_error": True})
        if failures > max_retries:
            return {"sql": sql, "df": df, "answer": None,
                    "error": f"Query failed after {max_retries} retries: {last_error}"}
        messages.append({"role": "user", "content": results})


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
