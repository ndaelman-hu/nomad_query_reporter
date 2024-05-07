import json
import re
import pandas as pd
import requests
import sys
import time
import nltk
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.corpus import stopwords
from nltk.probability import FreqDist
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer


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


# Current implementation: extractive summarization (selecting a subset of important sentences or segments directly from the original text)
# Semantic understanding using a pretrained model such as BERT or GPT-3 might also be an option.
def summarize_context(context, keywords, MAX_SENTENCES=5, keyword_boost=1.5):
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    stop_words = set(stopwords.words('english'))

    sentences = sent_tokenize(context)
    words = [word_tokenize(sentence.lower()) for sentence in sentences]
    filtered_words = [
        [word for word in sentence_words if word not in stop_words]
        for sentence_words in words
    ]

    fdist = FreqDist([word for sentence in filtered_words for word in sentence])
    sentence_scores = {}

    # Assign scores to sentences, boosting those with keywords
    for i, sentence_words in enumerate(filtered_words):
        base_score = sum(fdist[word] for word in sentence_words if word in fdist)
        if any(keyword in sentence_words for keyword in keywords):
            base_score *= keyword_boost
        sentence_scores[i] = base_score

    # Compute TF-IDF and then cosine similarity matrix
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(sentences)
    similarity_matrix = cosine_similarity(tfidf_matrix)

    # Reduce sentence scores by similarity to higher scoring sentences
    ranked_sentences = sorted(sentence_scores, key=sentence_scores.get, reverse=True)

    selected_sentences = []
    for sent in ranked_sentences:
        if all(
            similarity_matrix[sent, other] < 0.2 for other in selected_sentences
        ):  # threshold to tweak
            selected_sentences.append(sent)
        if len(selected_sentences) >= MAX_SENTENCES:
            break

    # Sort selected sentences by their original order
    summarized_text = ' '.join(sentences[idx] for idx in sorted(selected_sentences))
    return summarized_text


def llama_inject_context(llama_responses: list[str]) -> list[str]:
    """
    Update the Llama prompt with a compressed version of the context
    from the last response if the query is not done.
    """
    llama_response = None
    MAX_SENTENCES = 5  # Arbitrary limit for the number of sentences in the response
    if llama_responses:
        # Combine all responses into one large text block
        all_responses_text = ' '.join(llama_responses)
        # Summarize the combined responses
        keywords = ['Methods\n\n']
        summarized_context = summarize_context(
            all_responses_text, keywords, MAX_SENTENCES, keyword_boost=0.0
        )
        llama_response = summarized_context

    return llama_response


def llama_complete(llama_prompt: dict[str, str]) -> dict[str, str]:
    llama_prompt['model'] = 'llama3:70b'
    llama_prompt['seed'] = 42
    llama_prompt['temperature'] = 0.05
    llama_prompt['stream'] = False
    return llama_prompt


def llama_response_to_list(llama_response: dict[str, str]) -> list[dict[str, str]]:
    return json.loads(llama_response.content.decode('ascii').strip())['message'][
        'content'
    ]


def query_nomad(upload_id: str):
    if re.match(r'^[a-zA-Z0-9_-]{22}$', upload_id) is None:
        raise ValueError('Invalid upload ID')

    nomad_url = 'https://nomad-lab.eu/prod/v1/api/v1/entries/archive/query'  # ! add support for stagging
    nomad_params = {
        'query': {'upload_id': upload_id},
        'pagination': {
            'page_size': 1e2,  # 1e4 is the max supported by NOMAD
        },
        'required': {
            'resolve-inplace': True,
            'metadata': {
                'datasets': {
                    'doi': '*',
                },
            },
            'results': {
                'material': {
                    'material_name': '*',
                    'chemical_formula_iupac': '*',
                    'symmetry': '*',
                },
                'method': {
                    'method_name': '*',
                    'workflow_name': '*',
                    'simulation': {
                        'program_name': '*',
                        'program_version': '*',
                    },
                },
            },
        },
    }

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
                print(
                    f'Found {total_hits} entries matching upload_id {upload_id} in NOMAD. Commencing download...'
                )
                first_pass = False
            # Mangle data
            for entry in nomad_data['data']:
                nomad_df_body.append(
                    [value for _, value in get_leaf_nodes(entry['archive'])]
                )
            if nomad_df_header == []:
                nomad_df_header = [
                    '.'.join(map(str, path))
                    for path, _ in get_leaf_nodes(entry['archive'])
                ]
            print(f'Accumulated {len(nomad_df_body)}/{total_hits} entries thus far.')
            if next_page := nomad_data['pagination'].get('next_page_after_value', ''):
                nomad_params['pagination']['page_after_value'] = next_page
                trial_counter = 0  # reset the trial counter
            else:
                break
        elif trial_counter >= max_trials:
            print(f'Failed to query NOMAD after {max_trials} trials.')
            sys.exit(1)
        elif nomad_response.status_code in (502, 503):
            print('Retrying query to NOMAD...')
            time.sleep(10)
        else:
            print('Failed to query NOMAD:', nomad_response.text)
            sys.exit(1)  # ! add error handling
    print(f'Download completed. Analyzing...')
    return nomad_df_header, nomad_df_body


def report_on_upload(upload_id: str):
    nomad_df_header, nomad_df_body = query_nomad(upload_id)
    nomad_df = pd.DataFrame(nomad_df_body, columns=nomad_df_header)
    print(nomad_df.describe(include='all'))

    # Push a llama query
    llama_responses = []
    llama_url = 'http://172.28.105.30/backend/api/chat'
    llama_init_params = {
        'messages': [
            {
                'role': 'system',
                'content': """
                    You are a data analyst, summarizing data from a database.
                    You give me short (max 250 words) responses to my prompts.
                    You stay on-topic and provide relevant information.
                    No disclaimer or suggestions for improvements.
                """.strip().replace('\n', ''),
            },
            {
                'role': 'user',
                'content': """
                    Write me a Methods section for a paper draft.
                    Here is a response from the database API:
                """.strip().replace('\n', ''),
            },
            {
                'role': 'user',
                'content': str(nomad_df.describe(include='all')),
            },
        ]
    }

    llama_citation = {
        'prompt': """
            Amend the previous response by adding citations. Say that a 'similar setup as in [1]' was used.
            Then, at the end, add the actual citations. You can go over the previous word limit now.
            Avoid citations of methodology, programs, or experimental hardware.
        """.strip().replace('\n', ''),
    }  # ! query another API for the DOI

    # llama_init_response = requests.post(
    #     llama_url, json=llama_complete(llama_init_params)
    # )

    # # Check if the llama query was successful
    # if llama_init_response.status_code == 200:
    #     print(llama_response_to_list(llama_init_response))
    # else:
    #     print('Failed to push llama query:', llama_init_response.text)

    max_iterations = 10  # set a practical limit based on expected use case
    iteration_count = 0

    while iteration_count < max_iterations:
        llama_response = requests.post(
            llama_url, json=llama_complete(llama_init_params)
        )
        if llama_response.status_code == 200:
            llama_responses.append(
                llama_response_to_list(llama_response).split(':')[-1]
            )
            iteration_count += 1
        else:
            print('Failed to push llama query:', llama_response.text)
            break

    if llama_responses:
        llama_response = llama_inject_context(llama_responses)
        print('\nFinal Output:', llama_response)
    else:
        print('No responses were generated.')


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        'upload_id',
        help='ID of the upload to query in NOMAD (e.g. If6n8Mv2TamLe98nUFmnIA)',
    )
    args = ap.parse_args()

    report_on_upload(args.upload_id)
