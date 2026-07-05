# src/gharc/filters.py


def _repo_owner(repo_name: str):
    """Return the owner portion of an ``owner/name`` repository string."""
    if not repo_name:
        return None
    return repo_name.split('/', 1)[0]


def _repo_selected(repo_name, repos, orgs) -> bool:
    """True if a repo name is picked by the --repos or --orgs selectors."""
    if repo_name is None:
        return False
    if repos:
        for pattern in repos:
            if pattern.endswith('/*'):
                # "apache/*" keeps the trailing slash so it cannot also match
                # a different owner such as "apache-foo/bar".
                if repo_name.startswith(pattern[:-1]):
                    return True
            elif repo_name == pattern:
                return True
    if orgs and _repo_owner(repo_name) in orgs:
        return True
    return False


def passes_filters(event_dict: dict, repos: list = None, event_types: list = None,
                   orgs: list = None, actors: list = None) -> bool:
    """Return True if an event matches every active filter group.

    Repository selection combines ``repos`` and ``orgs``: an event passes the
    repository group when its name matches any entry in ``repos`` (exact, or an
    ``owner/*`` wildcard) or its owner appears in ``orgs``. Event type and actor
    are separate groups that must also match when given. A group left as None is
    ignored (pass-through).
    """
    if repos or orgs:
        repo_name = event_dict.get('repo', {}).get('name')
        if not _repo_selected(repo_name, repos, orgs):
            return False

    if event_types and event_dict.get('type') not in event_types:
        return False

    if actors:
        actor_login = event_dict.get('actor', {}).get('login')
        if actor_login not in actors:
            return False

    return True


def prefilter_tokens(repos: list = None, event_types: list = None,
                     orgs: list = None, actors: list = None) -> list:
    """Build the substrings used to skip lines before JSON parsing.

    A truly matching event always contains at least one of these tokens, so the
    check is a superset test: it may admit a line the structured filter later
    rejects, but it never drops a real match. With no filters the list is empty
    and every line is parsed.
    """
    tokens = []
    for pattern in repos or []:
        tokens.append(pattern[:-1] if pattern.endswith('/*') else pattern)
    for owner in orgs or []:
        tokens.append(owner + '/')
    for event_type in event_types or []:
        tokens.append(event_type)
    for actor in actors or []:
        tokens.append(actor)
    return tokens


def fast_string_check(line: str, tokens: list) -> bool:
    """Return False if none of the tokens appear in the string.

    Avoids expensive JSON parsing for lines that cannot match. An empty token
    list means no filtering, so every line passes.
    """
    if not tokens:
        return True
    return any(t in line for t in tokens)
