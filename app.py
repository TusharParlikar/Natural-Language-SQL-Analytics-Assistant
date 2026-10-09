import os
import shutil

import pandas as pd
import streamlit as st

from assistant import DB_PATH, _identifier, ask, files_to_sqlite, get_schema, is_sqlite

EXAMPLES = [
    "What are the top 10 best-selling tracks by revenue?",
    "Monthly revenue for 2012",
    "Which 5 countries brought in the most revenue?",
    "Which employee supports the customers with the highest total spend?",
    "Average invoice value per country, highest first",
]
UPLOAD_TYPES = ["csv", "xlsx", "xls", "db", "sqlite", "sqlite3"]
STORE = "data/store"  # saved databases; kept across restarts on your own machine or server


def chart_spec(df):
    """Pick a chart from the result's shape: ("line"|"bar", x, y) or None."""
    num = list(df.select_dtypes("number").columns)
    other = [c for c in df.columns if c not in num]
    if len(df) < 2 or not num or not other:
        return None
    x = other[0]
    if pd.to_datetime(df[x], errors="coerce", format="mixed").notna().all():
        return "line", x, num
    return "bar", x, num[0]


def stored_dbs():
    """Names of the saved databases. The Chinook sample is copied in on first run, and again if it is deleted."""
    os.makedirs(STORE, exist_ok=True)
    if not os.path.exists(f"{STORE}/chinook.db"):
        shutil.copyfile(DB_PATH, f"{STORE}/chinook.db")
    return sorted(f[:-3] for f in os.listdir(STORE) if f.endswith(".db"))


def save_upload(files):
    """Store uploaded files as a new database and return its name. A SQLite file is kept as-is; CSV/Excel are converted."""
    data = [(f.name, f.getvalue()) for f in files]
    sqlite_files = [d for d in data if is_sqlite(d[1])]
    if sqlite_files and len(data) > 1:
        raise ValueError("Upload a SQLite database on its own, or only CSV/Excel files.")
    base = _identifier(os.path.splitext(files[0].name)[0], "data")
    name, n = base, 1
    while os.path.exists(f"{STORE}/{name}.db"):  # never overwrite a saved database
        n += 1
        name = f"{base}_{n}"
    path = f"{STORE}/{name}.db"
    try:
        if sqlite_files:
            with open(path, "wb") as fh:
                fh.write(sqlite_files[0][1])
        else:
            files_to_sqlite(data, path)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return name


@st.cache_data
def schema(db_path):
    return get_schema(db_path)


st.set_page_config(page_title="SQL Analytics Assistant", page_icon="📊", layout="wide")
st.title("Natural-Language SQL Analytics Assistant")

with st.sidebar:
    names = stored_dbs()
    if "pending_db" in st.session_state:  # a new upload: select it (must happen before the selectbox is drawn)
        st.session_state.db = st.session_state.pop("pending_db")
    if st.session_state.get("db") not in names:
        st.session_state.db = "chinook"
    db = st.selectbox("Database", names, key="db")
    db_path = f"{STORE}/{db}.db"
    sample = db == "chinook"
    files = st.file_uploader("Add a database from CSV, Excel or SQLite files", type=UPLOAD_TYPES,
                             accept_multiple_files=True, help="Each CSV file and each Excel sheet becomes one table.")
    if files:
        key = tuple((f.name, f.size) for f in files)
        if st.session_state.get("upload_key") != key:
            st.session_state.upload_key = key
            try:
                st.session_state.pending_db = save_upload(files)
                st.rerun()
            except Exception as e:
                st.error(f"Could not load the files: {e}")
    if sample:
        st.subheader("Example questions")
        for q in EXAMPLES:
            if st.button(q, width="stretch"):
                st.session_state.question = q
    with st.expander("Database schema"):
        st.code(schema(db_path), language="sql")

st.caption("Ask a business question about " + ("the Chinook music store database." if sample else "your uploaded data."))
question = st.text_input("Your question", key="question",
                         placeholder=EXAMPLES[0] if sample else "e.g. Total sales by region")

if st.button("Ask", type="primary") and question.strip():
    with st.spinner("Writing and running SQL..."):
        try:
            r = ask(question, schema(db_path), db_path=db_path)
        except Exception as e:  # API key, network, rate limits
            r = {"sql": None, "df": None, "answer": None, "error": f"{type(e).__name__}: {e}"}

    if r["error"]:
        st.error(r["error"])
    elif r["answer"]:
        st.success(r["answer"])

    df = r["df"]
    if df is not None:
        spec = chart_spec(df)
        if spec and spec[0] == "line":
            st.line_chart(df, x=spec[1], y=spec[2])
        elif spec:
            st.bar_chart(df.head(50), x=spec[1], y=spec[2], sort=False)
        st.dataframe(df, width="stretch", hide_index=True)
    if r["sql"]:
        with st.expander("Generated SQL"):
            st.code(r["sql"], language="sql")
