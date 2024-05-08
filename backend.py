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
    nomad_query = substitute_tags(
        nomad_complete_prompt(f"{nq_dir}/{nomad_query_type}.json"),
        {id_type: ids},
    )
    if nomad_query_type == "computational":
        nomad_df = ping_nomad(nomad_query, nomad_url, extend_dataframe, use_streamlit=use_streamlit)
        # nomad_df = nomad_df.drop(nomad_df.columns[nomad_df.isin(['Unknown']).any()], axis=1)  # ! re-evaluate
        llama_prompt = str(
            {
                "attributes": nomad_df.columns,
                "method": nomad_df[filter_by_column(nomad_df, r"results\.method\..*").keys()].to_string(),
                "software": nomad_df["results.method.simulation.program_name"].unique,
                "material": nomad_df["results.material.chemical_formula_iupac"].unique,
            }
        )  # nomad_df.to_string()
    else:
        print("Invalid NOMAD query type.")

    # Query LLAMA
    if llama_query_type:
        llama_params = substitute_tags(
            llama_complete_prompt(f"{lq_dir}/{llama_query_type}.json"),
            {"prompt": llama_prompt},
        )
        if use_streamlit:
            llama_status = st.status("Sending query to LLAMA …")
        llama_response = requests.post(llama_url, json=llama_params)
        if llama_response.status_code == 200:
            if use_streamlit:
                llama_status.update(label="LLAMA query successful.", state="complete")
            print(llama_response_to_list(llama_response))
        else:
            if use_streamlit:
                llama_status.update(label="Failed to push LLAMA query.", state="error")
            print("Failed to push llama query:", llama_response.text)
            sys.exit(1)
    else:
        print(llama_prompt)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("nomad_query_type", help="Type of NOMAD query to perform (e.g. `computational`)")
    ap.add_argument("--llama_query_type", "--lq", default="", help="Type of LLAMA query to perform (e.g. `computational`)")
    ap.add_argument("--upload_id", "-u", default=[], nargs="*", help="ID of the upload to query in NOMAD (e.g. `If6n8Mv2TamLe98nUFmnIA`)")
    ap.add_argument("--entry_id", "-e", default=[],  nargs="*", help="ID of the entry to query in NOMAD (e.g. `5f6e8b4b9b7e4b0001f7b1d4`)")
    args = ap.parse_args()  # ! add credentials

    main(args.nomad_query_type, args.llama_query_type, args.upload_id, args.entry_id)
