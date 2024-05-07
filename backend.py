import json
import pandas as pd
import requests
import sys
import time

# Query NOMAD
upload_id = "-jbjmBQ4SNSMi9CkaXhhug"

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
                    "program_version": "*",
                },
            }
        }
    }
}

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
    return json.loads(llama_response.content.decode('ascii').strip())['message']['content']

# Check if the NOMAD query was successful
nomad_df_header, nomad_df_body = [], []
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
        print(f"Downloading {nomad_data['pagination']['page_size']} more files from NOMAD...")
        # Mangle data
        for entry in nomad_data['data']:
            nomad_df_body.append([value for _, value in get_leaf_nodes(entry["archive"])])
        if nomad_df_header == []:
            nomad_df_header = [".".join(map(str, path)) for path, _ in get_leaf_nodes(entry["archive"])]
        print(f"Accumulated {len(nomad_df_body)}/{total_hits} entries thus far.")    
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

nomad_df = pd.DataFrame(nomad_df_body, columns=nomad_df_header)
print(nomad_df.describe(include="all"))

# Push a llama query
llama_url = "http://172.28.105.30/backend/api/chat"
llama_init_params = {
    "messages": [
        {
            "role": "system",
            "content": """
                You are a data analyst, summarizing data from a database.
                You give me short (max 250 words) responses to my prompts.
                You stay on-topic and provide relevant information.
                No disclaimer or suggestions for improvements.
            """.strip().replace("\n", ""),
        },
        {
            "role": "user",
            "content": """
                Write me a Methods section for a paper draft.
                Here is a response from the database API:
            """.strip().replace("\n", ""),
        },
        {
            "role": "user",
            "content": str(nomad_df.describe(include="all")),
        }
    ]  
}

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
