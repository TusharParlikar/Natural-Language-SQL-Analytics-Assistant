import sqlite3
import time

import pandas as pd
import sqlglot
from sqlglot import exp

DB_PATH = "data/chinook.db"
ROW_LIMIT = 1000
TIMEOUT_S = 5
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Pragma)


def validate(sql):
    """Allow exactly one read-only SELECT/WITH statement. Returns cleaned SQL with a row limit, or raises ValueError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL could not be parsed: {e}") from None
    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise ValueError(f"Only SELECT queries are allowed, got {tree.key.upper()}.")
    if any(tree.find_all(*FORBIDDEN)):
        raise ValueError("Only read-only SELECT queries are allowed.")
    sql = sql.strip().rstrip(";")
    if not tree.args.get("limit"):
        sql += f"\nLIMIT {ROW_LIMIT}"
    return sql


def run_query(sql, db_path=DB_PATH, timeout_s=TIMEOUT_S):
    """Validate, then execute on a read-only connection with a timeout. Returns a DataFrame."""
    sql = validate(sql)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)  # non-zero return aborts
        cur = conn.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    finally:
        conn.close()


if __name__ == "__main__":
    blocked = [
        "DROP TABLE Artist",
        "DELETE FROM Artist",
        "UPDATE Artist SET Name = 'x'",
        "INSERT INTO Artist VALUES (999, 'x')",
        "SELECT 1; DROP TABLE Artist",
        "ATTACH DATABASE 'evil.db' AS evil",
        "PRAGMA writable_schema = ON",
        "CREATE TABLE t (x)",
        "WITH x AS (SELECT 1) DELETE FROM Artist",
        "not even sql (",
    ]
    for q in blocked:
        try:
            validate(q)
        except ValueError:
            continue
        raise AssertionError(f"not blocked: {q}")

    assert validate("SELECT * FROM Artist").endswith(f"LIMIT {ROW_LIMIT}")
    assert validate("SELECT * FROM Artist LIMIT 5;") == "SELECT * FROM Artist LIMIT 5"
    assert len(run_query("SELECT * FROM Track")) == ROW_LIMIT
    assert run_query("WITH c AS (SELECT COUNT(*) AS n FROM Artist) SELECT n FROM c").n[0] == 275
    assert len(run_query("SELECT Name FROM Artist UNION SELECT Name FROM Genre")) == 300

    try:  # cartesian blow-up must hit the timeout
        run_query("SELECT COUNT(*) FROM Track a, Track b, Track c", timeout_s=0.5)
        raise AssertionError("timeout not enforced")
    except sqlite3.OperationalError as e:
        assert "interrupt" in str(e)

    assert run_query("SELECT COUNT(*) AS n FROM Artist").n[0] == 275  # data untouched
    print("guard checks passed")
