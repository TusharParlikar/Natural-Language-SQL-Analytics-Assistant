import os
import shutil

import pandas as pd
import streamlit as st

from assistant import (DB_PATH, _identifier, ask, drop_table, files_to_sqlite, get_schema, is_sqlite, load_table,
                       save_table, table_names)

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


def data_tab(db_path, modify):
    """Browse tables; in Modify mode also edit, add and delete rows or delete a table. The LLM stays read-only."""
    tables = table_names(db_path)
    if not tables:
        st.info("This database has no tables left.")
        return
    table = st.selectbox("Table", tables)
    if not modify:
        st.caption("Turn on **Modify** at the top to change the data.")
        st.dataframe(load_table(db_path, table), width="stretch", hide_index=True)
        return
    ver = st.session_state.get("edit_ver", 0)  # bumped on save so the editor reloads from the DB
    st.caption("Click a cell to edit it. Add rows at the bottom; select rows by their left edge and press Delete to remove them.")
    # ponytail: loads the whole table into the browser; page it if uploads get very large
    edited = st.data_editor(load_table(db_path, table), num_rows="dynamic", width="stretch", hide_index=True,
                            key=f"edit_{db_path}_{table}_{ver}")
    col1, col2 = st.columns([1, 5])
    if col1.button("Save changes", type="primary"):
        try:
            save_table(db_path, table, edited)
        except Exception as e:
            st.error(f"Could not save: {e}")
        else:
            st.session_state.edit_ver = ver + 1
            schema.clear()
            st.rerun()
    if col2.button(f"Delete table {table}"):
        drop_table(db_path, table)
        st.session_state.edit_ver = ver + 1
        schema.clear()
        st.rerun()


st.set_page_config(page_title="SQL Analytics Assistant", page_icon="📊", layout="wide")
title_col, modify_col = st.columns([5, 1], vertical_alignment="bottom")
title_col.title("Natural-Language SQL Analytics Assistant")
modify = modify_col.toggle("Modify", help="Turn on to upload, edit or delete data. Off = view only.")

with st.sidebar:
    names = stored_dbs()
    if "pending_db" in st.session_state:  # a new upload: select it (must happen before the selectbox is drawn)
        st.session_state.db = st.session_state.pop("pending_db")
    if st.session_state.get("db") not in names:
        st.session_state.db = "chinook"
    db = st.selectbox("Database", names, key="db")
    db_path = f"{STORE}/{db}.db"
    sample = db == "chinook"
    with open(db_path, "rb") as fh:
        st.download_button("Download database", fh.read(), file_name=f"{db}.db", width="stretch",
                           help="Keep a copy of your data, e.g. before the server restarts.")
    if modify:
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
        if st.button("Reset sample database" if sample else f"Delete database {db}", width="stretch"):
            os.remove(db_path)
            st.session_state.edit_ver = st.session_state.get("edit_ver", 0) + 1
            schema.clear()
            st.rerun()
    if sample:
        st.subheader("Example questions")
        for q in EXAMPLES:
            if st.button(q, width="stretch"):
                st.session_state.question = q
    with st.expander("Database schema"):
        st.code(schema(db_path), language="sql")

ask_tab, tab = st.tabs(["Ask a question", "Data"])
with tab:
    data_tab(db_path, modify)

with ask_tab:
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
