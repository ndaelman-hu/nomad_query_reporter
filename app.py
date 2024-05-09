import io
from contextlib import redirect_stdout
import re

import streamlit as st

from backend import main


def _fix_streamlit_space(text: str) -> str:
    """Fix silly streamlit issue where a newline needs 2 spaces before it.

    Source: https://github.com/streamlit/streamlit/issues/868#issuecomment-2016515781
    """

    def _replacement(match: re.Match):
        if match.group(0).startswith(" "):
            return " \n"
        else:
            return "  \n"

    return re.sub(r"( ?)\n", _replacement, text)


st.image('nomad-horizontal.svg', width=300)
st.title('NOMAD Query Reporter')

# Query selector
query_options = ["verbose", "executive summary"]
query_option_map = {"verbose": ("computational", "computational"), "executive summary": ("computational_short", "computational_short")}

query_type = st.selectbox("select your query type", query_options, index=0)
st.session_state.query_type = query_type
query_option = query_option_map[st.session_state.get("query_type", "verbose")]

# Chat
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if prompt := st.chat_input("What is the upload id? Use commas to separate multiple."):
    with st.chat_message("user"):
        st.write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with redirect_stdout(io.StringIO()) as buffer:
        main(
            query_option[0],
            llama_query_type=query_option[1],
            upload_id=[prompt],
            use_streamlit=True,
        )
    response = buffer.getvalue()

    with st.chat_message("assistant"):
        st.write(_fix_streamlit_space(response))

    st.session_state.messages.append({"role": "assistant", "content": response})
