import pandas as pd

def get_leaf_nodes(data, path=None):
    """Flatten out a nested dictionary to a path / value generator."""
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


def leafs_to_df(leafs):
    """Convert the output from `get_leaf_nodes` to a `pandas.DataFrame`."""
    return pd.DataFrame(
        {".".join([str(l) for l in leaf[0]]): [leaf[1]] for leaf in leafs}
    )

def substitute_tags(obj, params: dict[str, any]):
    # Handle string substitution, checking for tags enclosed in < >
    if isinstance(obj, str):
        if obj.startswith("<") and obj.endswith(">"):
            key = obj[1:-1]
            return params[key]
        return obj
    # Handle dictionaries by applying substitution to each value
    elif isinstance(obj, dict):
        return {key: substitute_tags(value, params) for key, value in obj.items()}
    # Handle lists by applying substitution to each element
    elif isinstance(obj, list):
        return [substitute_tags(item, params) for item in obj]
    # Return the object as is if it does not match the above types
    else:
        return obj
