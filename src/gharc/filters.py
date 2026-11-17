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


def prefilter_groups(repos: list = None, event_types: list = None,
                     orgs: list = None, actors: list = None) -> list:
    """Build the substring groups used to skip lines before JSON parsing.

    Returns one list of tokens per active filter group: repositories and owners
    together (they are combined with OR), then event types, then actors. A truly
    matching event contains at least one token from every group, so the check is
    a superset test: it may admit a line the structured filter later rejects,
    but it never drops a real match. With no filters the result is empty and
    every line is parsed.
    """
    groups = []
    repo_tokens = [p[:-1] if p.endswith('/*') else p for p in repos or []]
    repo_tokens += [owner + '/' for owner in orgs or []]
    for tokens in (repo_tokens, list(event_types or []), list(actors or [])):
        if tokens:
            groups.append(tokens)
    return groups


def passes_prefilter(line, groups: list) -> bool:
    """Return True if the line contains a token from every group.

    Works on ``str`` or ``bytes`` as long as the tokens are the same type.
    Requiring every group, rather than any token at all, is what keeps a
    combined filter selective: ``--repos apache/spark --event-types PushEvent``
    would otherwise admit every PushEvent in the archive to the JSON parser.
    """
    return all(any(t in line for t in tokens) for tokens in groups)


def fast_string_check(line: str, tokens: list) -> bool:
    """Return False if none of the tokens appear in the string.

    Avoids expensive JSON parsing for lines that cannot match. An empty token
    list means no filtering, so every line passes.
    """
    if not tokens:
        return True
    return any(t in line for t in tokens)
