from agent_platform.context.staleness import ContextCache


def test_first_sighting_of_a_path_is_never_stale():
    cache = ContextCache()
    assert cache.check_and_update("app.py", "original content") is False


def test_unchanged_content_on_second_check_is_not_stale():
    cache = ContextCache()
    cache.check_and_update("app.py", "original content")
    assert cache.check_and_update("app.py", "original content") is False


def test_changed_content_on_second_check_is_stale():
    cache = ContextCache()
    cache.check_and_update("app.py", "original content")
    assert cache.check_and_update("app.py", "modified content") is True


def test_staleness_check_updates_the_cache_to_the_new_content():
    cache = ContextCache()
    cache.check_and_update("app.py", "v1")
    cache.check_and_update("app.py", "v2")
    assert cache.check_and_update("app.py", "v2") is False  # now matches the latest seen


def test_different_paths_are_tracked_independently():
    cache = ContextCache()
    cache.check_and_update("a.py", "x")
    assert cache.check_and_update("b.py", "y") is False
