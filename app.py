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


st.title("NOMAD Query Reporter")

# Query selector
button_clicked = st.button("query type")
query_options = ["computational"]
query_option_map = {"computational": ("computational", "computational")}

default_index = 0
query_type = query_options[default_index]
if button_clicked:
    query_type = st.selectbox("Select an option", query_options, index=default_index)

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
            query_option_map[query_type][0],
            llama_query_type=query_option_map[query_type][1],
            upload_id=[prompt],
        )
    response = buffer.getvalue()

    with st.chat_message("Reporter"):
        st.write(_fix_streamlit_space(response))

    st.session_state.messages.append({"role": "Reporter", "content": response})
