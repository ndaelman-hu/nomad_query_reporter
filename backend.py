import re
import requests
import sys

from query_llama import *
from query_nomad import *
from utils import substitute_tags

nomad_url = "https://nomad-lab.eu/prod/v1/staging/api/v1/entries/archive/query"
llama_url = "http://172.28.105.30/backend/api/chat"
nq_dir, lq_dir = "nomad_queries/", "llama_queries/"

def check_upload_id(upload_id: str) -> bool:
    """Check if the upload ID is valid."""
    return re.match(r"^[a-zA-Z0-9_-]{22}$", upload_id) is not None


# ! Add check_entry_id


def main(
    nomad_query_type: str,
    llama_query_type: str="",
    upload_id: list[str]=[],
    entry_id: list[str]=[],
    *,
    use_streamlit: bool=False
):
    # Read IDs
    ids, id_type = [], ""
    if len(upload_id) > 0:
        for upload_idlet in upload_id:
            if not check_upload_id(upload_idlet):
                print(f"Invalid upload ID: {upload_idlet}")
                sys.exit(1)
        ids.extend(upload_id)
        id_type = "upload_id"
    elif len(entry_id) > 0:
        ids.extend(entry_id)
        id_type = "entry_id"
    else:
        print("Please provide at least one ID to query.")
        sys.exit(1)

    # Query NOMAD
    try:
        nomad_query = substitute_tags(
            nomad_complete_prompt(f"{nq_dir}/{nomad_query_type}.json"),
            {id_type: ids},
        )
    except FileNotFoundError:
        print("Invalid NOMAD query type.")
    
    nomad_df = ping_nomad(nomad_query, nomad_url, extend_dataframe, use_streamlit=use_streamlit)


    # Query LLAMA
    if llama_query_type:
        if use_streamlit:
            llama_status = st.status("Sending query to LLAMA …")

        llama_query_specs, llama_response = json.load(open(f"{lq_dir}/{llama_query_type}.json")), None
        for pattern, chat in zip(llama_query_specs["patterns"], llama_query_specs["chats"]):
            llama_prompt = str(
                {
                    column_name: list(nomad_df[column_name].unique())
                    for column_name in filter_by_column(nomad_df, pattern).keys()
                }
            )
            llama_params = substitute_tags(llama_complete_prompt(chat, temperature=.1), {"prompt": llama_prompt})
            if llama_response is not None:
                llama_params['messages'] = [llama_response_to_list(llama_response)['message']] + llama_params['messages']

            llama_response = requests.post(llama_url, json=llama_params)
            if llama_response.status_code != 200:
                if use_streamlit:
                    llama_status.update(label="Failed to push LLAMA query.", state="error")
                print("Failed to push llama query:", llama_response.text)
                sys.exit(1)

        if llama_response.status_code == 200:
                if use_streamlit:
                    llama_status.update(label="LLAMA query successful.", state="complete")
                print(llama_response_to_list(llama_response)['message']['content'])


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("nomad_query_type", help="Type of NOMAD query to perform (e.g. `computational`)")
    ap.add_argument("--llama_query_type", "--lq", default="", help="Type of LLAMA query to perform (e.g. `computational`)")
    ap.add_argument("--upload_id", "-u", default=[], nargs="*", help="ID of the upload to query in NOMAD (e.g. `If6n8Mv2TamLe98nUFmnIA`)")
    ap.add_argument("--entry_id", "-e", default=[],  nargs="*", help="ID of the entry to query in NOMAD (e.g. `5f6e8b4b9b7e4b0001f7b1d4`)")
    args = ap.parse_args()  # ! add credentials

    main(args.nomad_query_type, args.llama_query_type, args.upload_id, args.entry_id)
