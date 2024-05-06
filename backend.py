import json
import requests
import sys

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
}  # ? vector embedding of query responses

def llama_complete(llama_prompt: dict[str, str]) -> dict[str, str]:
    llama_prompt['model'] = "llama3:70b"
    llama_prompt['temperature'] = 0.05
    return llama_prompt

def llama_inject_context(llama_prompt: dict[str, str], llama_responses: list[dict[str, str]]) -> dict[str, str]:
    response_end = llama_responses[-1]
    llama_prompt['context'] = response_end['context'] if response_end['done'] else []
    return llama_prompt

def llama_response_to_list(llama_response: dict[str, str]) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    for x in llama_response.content.decode('utf-8').strip().split('\n'):
        x = json.loads(x)
        if 'response' in x:
            extracted.append(x)
        elif 'error' in x:
            print("Error in llama response:", x)
            sys.exit(1)
    return extracted

# Check if the NOMAD query was successful
nomad_results, nomad_metadata = [], []

while True:
    nomad_response = requests.post(nomad_url, json=nomad_params)

    if nomad_response.status_code == 200:
        nomad_data = nomad_response.json()
        if (next_page := nomad_data['pagination'].get('next_page_after_value', '')):
            nomad_params["pagination"]["page_after_value"] = next_page
            nomad_results.extend([entry["archive"]['results'] for entry in nomad_data['data']])
            nomad_metadata.extend([entry["archive"]['metadata'] for entry in nomad_data['data']])
        else:
            break
    else:
        print("Failed to query NOMAD:", nomad_response.text)
        sys.exit(1)  # ! add error handling
print(f"Found {len(nomad_results)} results in NOMAD for upload_id {upload_id}. Analyzing...")

# Push a llama query
llama_url = "http://172.28.105.30/backend/api/generate"
llama_init_params = {
    "prompt": """
        Write me a Methods section for a paper draft. Keep it short and descriptive, 250 words max.
        Focus on providing an overview of the data (mentioned below) and avoid giving reasons. No citations.
        Start immediately with the suggestion. Use a formal tone and the past tense.
        Here is a json format overview of the settings:
    """.strip().replace("\n", "") + '\n' + str(nomad_results),
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
    llama_init_data = llama_response_to_list(llama_init_response)
    print(''.join([x["response"] for x in llama_init_data]))
else:
    print("Failed to push llama query:", llama_init_response.text)

# ! add citations
if any([len(x['datasets']) for x in nomad_metadata]):
    llama_citation_response = requests.post(llama_url, json=llama_complete(llama_inject_context(llama_citation, llama_init_data)))
    if llama_citation_response.status_code == 200:
        print(''.join([x["response"] for x in llama_response_to_list(llama_citation_response)]))
    else:
        print("Failed to push llama follow-up query:", llama_citation_response.text)
