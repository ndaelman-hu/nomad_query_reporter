import json
import re
import pandas as pd
import requests
import sys
import time
import html2text

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
    llama_prompt['seed'] = 42
    llama_prompt['temperature'] = 0.05
    llama_prompt['stream'] = False
    return llama_prompt

def llama_inject_context(llama_prompt: dict[str, str], llama_responses: list[dict[str, str]]) -> dict[str, str]:
    response_end = llama_responses[-1]
    llama_prompt['context'] = response_end['context'] if response_end['done'] else []
    return llama_prompt

def llama_response_to_list(llama_response: dict[str, str]) -> list[dict[str, str]]:
    return json.loads(llama_response.content.decode('utf-8').strip())['message']['content'] # check for ascii or utf-8


def get_token(url, name=None):
    user = "pepe_marquez"
    password = "xxxxxx"

    # Get a token from the api, login
    response = requests.get(
        f'{url}/auth/token', params=dict(username=user, password=password))
    return response.json()['access_token']

def query_nomad(upload_id: str):
    if re.match(r"^[a-zA-Z0-9_-]{22}$", upload_id) is None:
        raise ValueError("Invalid upload ID")

    nomad_url = "https://nomad-hzb-se.de/nomad-oasis/api/v1"  # ! add support for stagging
    token = get_token(nomad_url)

    entry_id = "zxGAwm2x40wPpeMt9HDlE9CptBvG"

    nomad_params = {
        "query": {"upload_id": upload_id, "entry_type": "HySprint_ExperimentalPlan"},
        'owner': 'visible',
        "pagination": {
            "page_size": 1e2,  # 1e4 is the max supported by NOMAD
        },
        "required": {
            "data": {
                "description" : "*"
            }
        }
    }

    # Check if the NOMAD query was successful
    nomad_df = pd.DataFrame()
    trial_counter, max_trials = 0, 10
    first_pass, total_hits = True, 0
    while True:
        nomad_response = requests.post(f'{nomad_url}/entries/archive/query', headers={'Authorization': f'Bearer {token}'}, json=nomad_params)
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
                nomad_df_entry = pd.json_normalize(entry["archive"])
                nomad_df = pd.concat([nomad_df, nomad_df_entry], ignore_index=True, sort=False)
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
    print(nomad_df.describe(include="all"))

    #nomad_df = nomad_df.drop(nomad_df.columns[nomad_df.isin(['Unknown']).any()], axis=1)
    #column_dict = nomad_df.to_dict(orient='list')
    #print(column_dict)

    #print(nomad_df.iloc[0]['data.description'])

    plain_text = html2text.html2text(nomad_df.iloc[0]['data.description'])
    plain_text = plain_text.replace("**","")
    list_of_text = plain_text.split('###')



    print(plain_text)
    print(len(plain_text.split()))

    # Push a llama query
    llama_url = "http://172.28.105.30/backend/api/chat"
    llama_init_params = {
        "messages": [
            {
                "role": "system",
                "content": """
                    From now on, you are a data scientist, summarizing data from experimental samples.
                    You give me short (max 250 words) responses to my prompts.
                    You only write full sentences and no bullet points.
                    You stay on-topic and provide relevant information.
                    No disclaimer or suggestions for improvements.
                    Under no circumstances you should make stuff up.
                """.strip().replace("\n", ""),
            },
            {
                "role": "user",
                "content": """
                    The following is experimental data from an electronic lab book which is available for
                    the processes used to fabricate this batch of samples:
                """.strip().replace("\n", ""),
            }
        ]}
    for element in list_of_text:
        llama_init_params['messages'].append({
            "role": "user",
            "content": element
        })
    llama_init_params['messages'].append({
        "role": "user",
        "content": """
            Formulate the full method section for a scientific publication used to describe the sample fabrication and characterization.
            Write full sentences. Focus on process steps and used parameters which these processes have in common.
            """.strip().replace("\n", ""),
    })

    llama_citation = {
        "prompt": """
            Amend the previous response by adding citations. Say that a 'similar setup as in [1]' was used.
            Then, at the end, add the actual citations. You can go over the previous word limit now.
            Avoid citations of methodology, programs, or experimental hardware.
        """.strip().replace("\n", ""),
    } # ! query another API for the DOI

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
