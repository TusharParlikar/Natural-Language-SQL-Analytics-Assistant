import pandas as pd
import streamlit as st

from assistant import ask, get_schema

EXAMPLES = [
    "What are the top 10 best-selling tracks by revenue?",
    "Monthly revenue for 2012",
    "Which 5 countries brought in the most revenue?",
    "Which employee supports the customers with the highest total spend?",
    "Average invoice value per country, highest first",
]


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


@st.cache_data
def schema():
    return get_schema()


st.set_page_config(page_title="SQL Analytics Assistant", page_icon="📊", layout="wide")
st.title("Natural-Language SQL Analytics Assistant")
st.caption("Ask a business question about the Chinook music store database.")

with st.sidebar:
    st.subheader("Example questions")
    for q in EXAMPLES:
        if st.button(q, width="stretch"):
            st.session_state.question = q
    with st.expander("Database schema"):
        st.code(schema(), language="sql")

question = st.text_input("Your question", key="question", placeholder=EXAMPLES[0])

if st.button("Ask", type="primary") and question.strip():
    with st.spinner("Writing and running SQL..."):
        try:
            r = ask(question, schema())
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
