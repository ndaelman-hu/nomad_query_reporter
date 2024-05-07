import json
from typing import Optional

def llama_complete_prompt(
    query_file: str,
    temperature: float = 0,
    seed: Optional[int] = 42,
) -> dict[str, str]:
    """Complete a prompt for the llama model."""
    with open(query_file, "r") as f:
        llama_prompt = json.load(f)
        llama_prompt['model'] = "llama3:70b"
        llama_prompt['options'] = {"temperature": temperature}
        if seed is not None:
            llama_prompt['options']['seed'] = seed
        llama_prompt['stream'] = False
    return llama_prompt

def llama_inject_context(
    llama_prompt: dict[str, str],
    llama_responses: list[dict[str, str]],
) -> dict[str, str]:
    """Inject the context from the previous llama responses."""
    response_end = llama_responses[-1]
    llama_prompt['context'] = response_end['context'] if response_end['done'] else []
    return llama_prompt

def llama_response_to_list(llama_response: dict[str, str]) -> list[dict[str, str]]:
    """Function for converting a llama response"""
    return json.loads(llama_response.content.decode('utf-8').strip())['message']['content']
