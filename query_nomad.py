import json
import re
import pandas as pd
import requests
import sys
import time
import streamlit as st

from utils import get_leaf_nodes, leafs_to_df

def nomad_complete_prompt(query_file: str) -> dict[str, any]:
    """Read a NOMAD query from a JSON file."""
    with open(query_file, "r") as f:
        nomad_params = json.load(f)
        nomad_params["pagination"] = {
            "page_size": 1e2  # max is 1e4
        }
    return nomad_params


def extend_dataframe(data, starting_df):
    """Extend a DataFrame with queried data from NOMAD."""
    for entry in data['data']:
        entry_df = leafs_to_df(get_leaf_nodes(entry["archive"]))
        starting_df = pd.concat([starting_df, entry_df], ignore_index=True, sort=False)
    return starting_df


def filter_by_column(df: pd.DataFrame, regex_str: str) -> pd.DataFrame:
    groups = {}

    pattern = re.compile(regex_str)
    for column in df.columns:
        match = pattern.search(column)
        if match:
            key = match.group()  # This extracts the substring
            if key in groups:
                groups[key].append(column)
            else:
                groups[key] = [column]

    return groups


def ping_nomad(
    query: dict[str, any],
    nomad_url: str,
    converter: callable,
    max_trials: int = 10,
    sleep_time: int = 10,
    *,
    use_streamlit: bool = False
) -> pd.DataFrame:
    """Ping NOMAD with a query and convert the results to a DataFrame."""
    final_data = pd.DataFrame()
    trial_counter, first_pass, total_hits = 0, True, 0

    if use_streamlit:
        progress_bar_text = 'Downloading data from NOMAD …'
        progress_bar = st.progress(0.0, progress_bar_text)

        message = st.chat_message('assistant')
        def print(*args, **kwargs):
            message.write(*args, **kwargs)
                

    while True:
        nomad_response = requests.post(nomad_url, json=query)
        trial_counter += 1
        # Successful query
        if nomad_response.status_code == 200:
            nomad_data = nomad_response.json()
            # Update progress
            if first_pass:
                total_hits = nomad_data['pagination']['total']
                print(f"Found {total_hits} entries matching the query. Commencing download...")
                first_pass = False
            final_data = converter(nomad_data, final_data)  # Convert data
            print(f"Accumulated {len(final_data)}/{total_hits} entries thus far.")
            if use_streamlit:
                progress_bar.progress(len(final_data) / total_hits, progress_bar_text)
            # Prepare next step
            if (next_page := nomad_data['pagination'].get('next_page_after_value', '')):
                query["pagination"]["page_after_value"] = next_page
                trial_counter = 0 # Reset the trial counter
            else:
                break
        # No. trials exceeded
        elif trial_counter >= max_trials:
            print(f"Failed to query NOMAD after {max_trials} trials.")
            sys.exit(1)
        # Limit reached
        elif nomad_response.status_code in (502, 503):
            print("Retrying query to NOMAD...")
            time.sleep(sleep_time)
        # Other kinds of warnings
        else:
            print("Failed to query NOMAD:", nomad_response.text)
            sys.exit(1)
    print("Download completed. Analyzing...")
    return final_data
