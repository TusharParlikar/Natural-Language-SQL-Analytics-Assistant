import os
import tempfile

import pandas as pd
import streamlit as st

# Streamlit Cloud secrets -> environment, before assistant reads its LLM settings
try:
    for k, v in st.secrets.items():
        os.environ.setdefault(k, str(v))
except FileNotFoundError:  # no secrets file: running locally with .env
    pass

from assistant import BASE_URL, DB_PATH, ask, files_to_sqlite, get_schema, is_sqlite  # noqa: E402

EXAMPLES = [
    "What are the top 10 best-selling tracks by revenue?",
    "Monthly revenue for 2012",
    "Which 5 countries brought in the most revenue?",
    "Which employee supports the customers with the highest total spend?",
    "Average invoice value per country, highest first",
]
UPLOAD_TYPES = ["csv", "xlsx", "xls", "db", "sqlite", "sqlite3"]


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


def build_upload_db(files):
    """Turn uploaded files into a SQLite DB path. A SQLite file is used as-is; CSV/Excel are converted.

    ponytail: temp files are never deleted; add cleanup if the app runs long-term on a server.
    """
    data = [(f.name, f.getvalue()) for f in files]
    path = os.path.join(tempfile.mkdtemp(prefix="nlsql_"), "upload.db")
    sqlite_files = [d for d in data if is_sqlite(d[1])]
    if sqlite_files:
        if len(data) > 1:
            raise ValueError("Upload a SQLite database on its own, or only CSV/Excel files.")
        with open(path, "wb") as fh:
            fh.write(sqlite_files[0][1])
    else:
        files_to_sqlite(data, path)
    return path


@st.cache_data
def schema(db_path):
    return get_schema(db_path)


st.set_page_config(page_title="SQL Analytics Assistant", page_icon="📊", layout="wide")
st.title("Natural-Language SQL Analytics Assistant")

with st.sidebar:
    source = st.radio("Data source", ["Sample: Chinook music store", "Upload my own data"])
    if source.startswith("Sample"):
        db_path = DB_PATH
        st.subheader("Example questions")
        for q in EXAMPLES:
            if st.button(q, width="stretch"):
                st.session_state.question = q
    else:
        files = st.file_uploader("CSV, Excel or SQLite files", type=UPLOAD_TYPES, accept_multiple_files=True,
                                 help="Each CSV file and each Excel sheet becomes one table.")
        db_path = None
        if files:
            key = tuple((f.name, f.size) for f in files)
            if st.session_state.get("upload_key") != key:
                try:
                    st.session_state.upload_db = build_upload_db(files)
                    st.session_state.upload_key = key
                except Exception as e:
                    st.session_state.upload_key = None
                    st.error(f"Could not load the files: {e}")
            if st.session_state.get("upload_key") == key:
                db_path = st.session_state.upload_db
    if db_path:
        with st.expander("Database schema"):
            st.code(schema(db_path), language="sql")

if not db_path:
    st.info("Upload one or more CSV or Excel files, or a SQLite database, in the sidebar to start asking questions.")
    st.stop()

st.caption("Ask a business question about " + ("the Chinook music store database." if db_path == DB_PATH else "your uploaded data."))
with st.form("ask_form", border=False):  # a form submits on Enter
    question = st.text_input("Your question", key="question",
                             placeholder=EXAMPLES[0] if db_path == DB_PATH else "e.g. Total sales by region")
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    with st.spinner("Writing and running SQL..."):
        try:
            r = ask(question, schema(db_path), db_path=db_path)
        except Exception as e:  # API key, network, rate limits
            r = {"sql": None, "df": None, "answer": None, "error": f"{type(e).__name__}: {e} (LLM server: {BASE_URL})"}

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
