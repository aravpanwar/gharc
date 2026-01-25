import pytest
from gharc.filters import passes_filters, fast_string_check

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
