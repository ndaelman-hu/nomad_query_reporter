import json
import requests

# Query NOMAD
upload_id = "-jbjmBQ4SNSMi9CkaXhhug"

nomad_url = "https://nomad-lab.eu/prod/v1/api/v1/entries/archive/query"  # ! add support for stagging
nomad_params = {
    "query": {"upload_id": upload_id},
    "pagination": {
            "page_size": 1e3,  # 1e4 is the max supported by NOMAD
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

nomad_response = requests.post(nomad_url, json=nomad_params)

def llama_complete(llama_prompt: dict[str, str]) -> dict[str, str]:
    llama_prompt['model'] = "llama3:70b"
    llama_prompt['temperature'] = 0.05
    return llama_prompt

def llama_inject_context(llama_prompt: dict[str, str], llama_responses: list[dict[str, str]]) -> dict[str, str]:
    response_end = llama_responses[-1]
    llama_prompt['context'] = response_end['context'] if response_end['done'] else []
    return llama_prompt

def llama_reponse_to_list(llama_reponse: dict[str, str]) -> list[dict[str, str]]:
    return [json.loads(x) for x in llama_reponse.content.decode('utf-8').strip().split('\n')]

# Check if the NOMAD query was successful
if nomad_response.status_code == 200:
    nomad_data = nomad_response.json()
    nomad_prompt = str([entry["archive"]['results'] for entry in nomad_data['data']])
    # nomad_prompt = str(nomad_data['data'][0]['archive']['results'])

    # Push a llama query
    llama_url = "http://172.28.105.30/backend/api/generate"
    llama_init_params = {
        "prompt": """
            Write me a Methods section for a paper draft. Keep it short and descriptive, 250 words max.
            Focus on providing an overview of the data (mentioned below) and avoid giving reasons. No citations.
            Start immediately with the suggestion. Use a formal tone and the past tense.
            Here is a json format overview of the settings:
        """.strip().replace("\n", "") + '\n' + nomad_prompt,
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
        llama_init_data = llama_reponse_to_list(llama_init_response)
        print(''.join([x["response"] for x in llama_init_data]))
    else:
        print("Failed to push llama query:", llama_init_response.text)

    # ! add citations
    if any([len(x['archive']['metadata']['datasets']) for x in nomad_data['data']]):
        llama_citation_response = requests.post(llama_url, json=llama_complete(llama_inject_context(llama_citation, llama_init_data)))
        if llama_citation_response.status_code == 200:
            print(''.join([x["response"] for x in llama_reponse_to_list(llama_citation_response)]))
        else:
            print("Failed to push llama follow-up query:", llama_citation_response.text)
else:
    print("Failed to query NOMAD:", nomad_response.text)