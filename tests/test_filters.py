from gharc.filters import (
    passes_filters,
    fast_string_check,
    prefilter_groups,
    passes_prefilter,
)

def test_fast_string_check():
    # Should return True if ANY token is present
    line = '{"repo": {"name": "apache/spark"}, "type": "PushEvent"}'
    assert fast_string_check(line, ["apache/spark"]) is True
    assert fast_string_check(line, ["pandas-dev/pandas", "apache/spark"]) is True
    
    # Should return False if NO tokens are present
    assert fast_string_check(line, ["kubernetes/kubernetes"]) is False

def test_passes_filters_repo():
    event = {"repo": {"name": "apache/spark"}, "type": "PushEvent"}
    
    # Match
    assert passes_filters(event, repos=["apache/spark"]) is True
    # No Match
    assert passes_filters(event, repos=["pandas/pandas"]) is False
    # No Filter (Pass through)
    assert passes_filters(event, repos=None) is True

def test_passes_filters_type():
    event = {"repo": {"name": "apache/spark"}, "type": "PushEvent"}

    # Match
    assert passes_filters(event, event_types=["PushEvent"]) is True
    # No Match
    assert passes_filters(event, event_types=["PullRequestEvent"]) is False


def test_passes_filters_owner_wildcard():
    spark = {"repo": {"name": "apache/spark"}, "type": "PushEvent"}
    other_owner = {"repo": {"name": "apache-foo/bar"}, "type": "PushEvent"}

    assert passes_filters(spark, repos=["apache/*"]) is True
    # The trailing slash keeps the wildcard from leaking to a similar owner.
    assert passes_filters(other_owner, repos=["apache/*"]) is False


def test_passes_filters_orgs():
    event = {"repo": {"name": "apache/spark"}, "type": "PushEvent"}

    assert passes_filters(event, orgs=["apache"]) is True
    assert passes_filters(event, orgs=["pandas-dev"]) is False


def test_passes_filters_repos_or_orgs_union():
    event = {"repo": {"name": "apache/spark"}, "type": "PushEvent"}

    # Matches because the owner is in orgs, even though repos does not list it.
    assert passes_filters(event, repos=["pytorch/pytorch"], orgs=["apache"]) is True


def test_passes_filters_actors():
    event = {
        "repo": {"name": "apache/spark"},
        "type": "PushEvent",
        "actor": {"login": "dongjoon-hyun"},
    }

    assert passes_filters(event, actors=["dongjoon-hyun"]) is True
    assert passes_filters(event, actors=["someone-else"]) is False


def test_passes_filters_groups_are_anded():
    event = {
        "repo": {"name": "apache/spark"},
        "type": "PushEvent",
        "actor": {"login": "dongjoon-hyun"},
    }

    # Repo matches but the type does not, so the event is rejected.
    assert passes_filters(event, repos=["apache/spark"], event_types=["WatchEvent"]) is False


def test_prefilter_groups_cover_each_group():
    groups = prefilter_groups(
        repos=["apache/spark", "apache/*"],
        event_types=["PushEvent"],
        orgs=["pandas-dev"],
        actors=["bob"],
    )
    # Repos and orgs share a group because they are combined with OR.
    assert groups == [
        ["apache/spark", "apache/", "pandas-dev/"],
        ["PushEvent"],
        ["bob"],
    ]


def test_prefilter_groups_empty_without_filters():
    assert prefilter_groups() == []


def test_passes_prefilter_requires_every_group():
    groups = prefilter_groups(repos=["apache/spark"], event_types=["PushEvent"])
    spark_push = '{"type": "PushEvent", "repo": {"name": "apache/spark"}}'
    other_push = '{"type": "PushEvent", "repo": {"name": "someone/else"}}'
    spark_watch = '{"type": "WatchEvent", "repo": {"name": "apache/spark"}}'

    assert passes_prefilter(spark_push, groups) is True
    # A token from one group alone is not enough to reach the parser.
    assert passes_prefilter(other_push, groups) is False
    assert passes_prefilter(spark_watch, groups) is False


def test_passes_prefilter_admits_everything_without_groups():
    assert passes_prefilter('{"anything": 1}', []) is True


def test_passes_prefilter_works_on_bytes():
    groups = [[b"apache/"], [b"PushEvent"]]
    assert passes_prefilter(b'{"type":"PushEvent","repo":{"name":"apache/x"}}', groups)
    assert not passes_prefilter(b'{"type":"PushEvent","repo":{"name":"other/x"}}', groups)


def test_passes_filters_treats_null_nested_fields_as_no_match():
    event = {"repo": None, "actor": None, "type": "PushEvent"}

    assert passes_filters(event, repos=["apache/spark"]) is False
    assert passes_filters(event, orgs=["apache"]) is False
    assert passes_filters(event, actors=["bob"]) is False
    # A filter that does not look at the null field still applies normally.
    assert passes_filters(event, event_types=["PushEvent"]) is True
