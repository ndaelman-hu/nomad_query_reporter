import json
import re
import pandas as pd
import requests
import sys
import time

# Helper functions
def get_leaf_nodes(data, path=None):
    if path is None:
        path = []
    
    if isinstance(data, dict):
        for key, value in data.items():
            yield from get_leaf_nodes(value, path + [key])
    elif isinstance(data, list):
        for i, item in enumerate(data):
            yield from get_leaf_nodes(item, path + [i])
    else:
        yield path, data

def llama_complete(llama_prompt: dict[str, str]) -> dict[str, str]:
    llama_prompt['model'] = "llama3:70b"
    llama_prompt['options'] = {
        "temperature": 0.1,
        "seed": 42,
    }
    llama_prompt['stream'] = False
    return llama_prompt

def llama_inject_context(llama_prompt: dict[str, str], llama_responses: list[dict[str, str]]) -> dict[str, str]:
    response_end = llama_responses[-1]
    llama_prompt['context'] = response_end['context'] if response_end['done'] else []
    return llama_prompt

def llama_response_to_list(llama_response: dict[str, str]) -> list[dict[str, str]]:
    return json.loads(llama_response.content.decode('utf-8').strip())['message']['content'] # check for ascii or utf-8

def query_nomad(upload_id: str):
    if re.match(r"^[a-zA-Z0-9_-]{22}$", upload_id) is None:
        raise ValueError("Invalid upload ID")

    nomad_url = "https://nomad-lab.eu/prod/v1/api/v1/entries/archive/query"  # ! add support for stagging
    nomad_params = {
        "query": {"upload_id": upload_id},
        "pagination": {
            "page_size": 1e2,  # 1e4 is the max supported by NOMAD
        },
        "required": {
            "resolve-inplace": True,
            "metadata": {
                "datasets": {
                    "doi": "*",
                },
            },
            "results": {
                "material": {
                    "material_name": "*",
                    "chemical_formula_iupac": "*",
                    "symmetry": "*",
                },
                "method": {
                    "method_name": "*",
                    "workflow_name": "*",
                    "simulation": {
                        "program_name": "*",
                    },
                },
                "properties": "*",
            },
        }
    }

    # Check if the NOMAD query was successful
    nomad_df = pd.DataFrame()
    trial_counter, max_trials = 0, 10
    first_pass, total_hits = True, 0
    while True:
        nomad_response = requests.post(nomad_url, json=nomad_params)
        trial_counter += 1
        if nomad_response.status_code == 200:
            nomad_data = nomad_response.json()
            # Update progress
            if first_pass:
                total_hits = nomad_data['pagination']['total']
                print(f"Found {total_hits} entries matching upload_id {upload_id} in NOMAD. Commencing download...")
                first_pass = False
            # Mangle data
            for entry in nomad_data['data']:
                leafs = get_leaf_nodes(entry["archive"])
                nomad_df_entry = pd.DataFrame(
                    {".".join([str(l) for l in leaf[0]]): [leaf[1]] for leaf in leafs}
                )
                nomad_df = pd.concat(
                    [nomad_df, nomad_df_entry], ignore_index=True, sort=False
                )
            print(f"Accumulated {len(nomad_df)}/{total_hits} entries thus far.")
            if (next_page := nomad_data['pagination'].get('next_page_after_value', '')):
                nomad_params["pagination"]["page_after_value"] = next_page
                trial_counter = 0 # reset the trial counter
            else:
                break
        elif trial_counter >= max_trials:
            print(f"Failed to query NOMAD after {max_trials} trials.")
            sys.exit(1)
        elif nomad_response.status_code in (502, 503):
            print("Retrying query to NOMAD...")
            time.sleep(10)
        else:
            print("Failed to query NOMAD:", nomad_response.text)
            sys.exit(1)  # ! add error handling
    print(f"Download completed. Analyzing...")

    return nomad_df


def report_on_upload(upload_id: str):
    nomad_df = query_nomad(upload_id)

    nomad_df = nomad_df.drop(nomad_df.columns[nomad_df.isin(['Unknown']).any()], axis=1)

    # Push a llama query
    llama_url = "http://172.28.105.30/backend/api/chat"
    llama_init_params = {
        "messages": [
            {
                "role": "system",
                "content": """
                    I am a data analyst, summarizing data that you provide.
                    I only provide full-sentence summaries, and no bullet points.
                    Let us stay on-topic and provide relevant information only.
                    I will no bother you with disclaimers or suggestions for improvements.
                """.strip().replace("\n", ""),
            },
            {
                "role": "user",
                "content": """
                    Here is my data:
                """.strip().replace("\n", ""),
            },
            {
                "role": "user",
                "content": str(nomad_df.describe(include='all')),
            },
            {
                "role": "user",
                "content": """
                    Formulate a method and a results section for a scientific publication
                    based on the parameters provided. Write full sentences. 
                    Focus on process steps and used parameters which these processes have in common.
                    Ignore input data that is Unknown and do not write about unknown or nan values.
                """.strip().replace("\n", ""),
            },
        ] 
    }


    llama_init_response = requests.post(llama_url, json=llama_complete(llama_init_params))

    # Check if the llama query was successful
    if llama_init_response.status_code == 200:
        print(llama_response_to_list(llama_init_response))
    else:
        print("Failed to push llama query:", llama_init_response.text)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("upload_id", help="ID of the upload to query in NOMAD (e.g. If6n8Mv2TamLe98nUFmnIA)")
    args = ap.parse_args()

    report_on_upload(args.upload_id)
