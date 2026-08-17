from agent_platform.context.limits import DEFAULT_LIMITS, ContextLimits, estimate_tokens


def test_default_limits_are_all_positive():
    for value in (DEFAULT_LIMITS.max_files, DEFAULT_LIMITS.max_total_bytes,
                  DEFAULT_LIMITS.max_tokens_estimate, DEFAULT_LIMITS.max_individual_file_bytes,
                  DEFAULT_LIMITS.max_retrieval_depth, DEFAULT_LIMITS.max_search_results):
        assert value > 0


def test_custom_limits_override_defaults():
    limits = ContextLimits(max_files=5)
    assert limits.max_files == 5
    assert limits.max_total_bytes == DEFAULT_LIMITS.max_total_bytes


def test_estimate_tokens_is_deterministic_and_positive():
    text = "def hello():\n    return 'world'\n"
    assert estimate_tokens(text) == estimate_tokens(text)
    assert estimate_tokens(text) > 0


def test_estimate_tokens_scales_with_length():
    assert estimate_tokens("x" * 4000) > estimate_tokens("x" * 40)
