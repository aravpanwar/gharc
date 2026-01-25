# src/gharc/filters.py
import json

def passes_filters(event_dict: dict, repos: list = None, event_types: list = None) -> bool:
    """
    Returns True if the event matches ANY of the provided filters.
    If a filter list is None, it is ignored (pass-through).
    """
    # 1. Filter by Repo Name
    if repos:
        repo_name = event_dict.get('repo', {}).get('name')
        if repo_name not in repos:
            return False
            
    # 2. Filter by Event Type
    if event_types:
        if event_dict.get('type') not in event_types:
            return False
            
    return True

def fast_string_check(line: str, tokens: list) -> bool:
    """
    Optimization: Returns False if NONE of the tokens appear in the string.
    Avoids expensive JSON parsing for lines that definitely don't match.
    """
    if not tokens:
        return True
    return any(t in line for t in tokens)