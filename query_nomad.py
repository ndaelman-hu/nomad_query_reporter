import json
import pandas as pd
import requests
import sys
import time

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


def get_token(url, name=None):
    user = "pepe_marquez"
    password = "llm-hack"

    # Get a token from the api, login
    response = requests.get(
        f'{url}/auth/token', params=dict(username=user, password=password))
    return response.json()['access_token']

def ping_nomad(
    query: dict[str, any],
    nomad_url: str,
    converter: callable,
    max_trials: int = 10,
    sleep_time: int = 10,
) -> pd.DataFrame:
    """Ping NOMAD with a query and convert the results to a DataFrame."""
    final_data = pd.DataFrame()
    trial_counter, first_pass, total_hits = 0, True, 0

    nomad_url = "https://nomad-hzb-se.de/nomad-oasis/api/v1"  # ! add support for stagging
    token = get_token(nomad_url)

    while True:
        nomad_response = requests.post(f'{nomad_url}/entries/archive/query', headers={'Authorization': f'Bearer {token}'}, json=query)
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
            print(f"Accumulated {len(nomad_data['data'])}/{total_hits} entries thus far.")
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
