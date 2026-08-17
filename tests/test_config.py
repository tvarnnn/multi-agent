import pytest

from agent_platform.config import ConfigurationError, PlatformConfig
from agent_platform.security.enums import SessionMode


def test_valid_absolute_existing_directory_loads(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.workspace_root == tmp_path.resolve()


def test_relative_path_is_rejected():
    with pytest.raises(ConfigurationError):
        PlatformConfig.load("Projects")


def test_nonexistent_path_is_rejected(tmp_path):
    missing = tmp_path / "DoesNotExist"
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(missing))


def test_file_instead_of_directory_is_rejected(tmp_path):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(f))


def test_platform_config_is_immutable(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    with pytest.raises(Exception):
        config.workspace_root = tmp_path


def test_default_session_mode_and_caps(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.session_mode == SessionMode.AUTO
    assert config.max_output_retries == 3
    assert config.max_clarification_rounds == 3
    assert config.max_fix_iterations == 3


def test_explicit_session_mode_and_caps_are_honored(tmp_path):
    config = PlatformConfig.load(str(tmp_path), session_mode=SessionMode.MANUAL,
                                  max_output_retries=5, max_clarification_rounds=2,
                                  max_fix_iterations=4)
    assert config.session_mode == SessionMode.MANUAL
    assert config.max_output_retries == 5
    assert config.max_clarification_rounds == 2
    assert config.max_fix_iterations == 4


@pytest.mark.parametrize("field,value", [
    ("max_output_retries", 0), ("max_output_retries", -1),
    ("max_clarification_rounds", 0), ("max_fix_iterations", 0),
])
def test_non_positive_caps_are_rejected(tmp_path, field, value):
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), **{field: value})


# --------------------------------------------------------- Phase 10 fields

def test_default_persistence_fields(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.agent_data_dir == ".agent"
    assert config.context_compaction_enabled is True
    assert config.context_compaction_threshold_percent == 85
    assert config.max_conversation_tokens_estimate == 20_000
    assert config.tool_observation_retention == 200
    assert config.recent_message_window == 20


def test_explicit_persistence_fields_are_honored(tmp_path):
    config = PlatformConfig.load(
        str(tmp_path), agent_data_dir=".custom-agent", context_compaction_enabled=False,
        context_compaction_threshold_percent=70, max_conversation_tokens_estimate=5000,
        tool_observation_retention=50, recent_message_window=10,
    )
    assert config.agent_data_dir == ".custom-agent"
    assert config.context_compaction_enabled is False
    assert config.context_compaction_threshold_percent == 70
    assert config.max_conversation_tokens_estimate == 5000
    assert config.tool_observation_retention == 50
    assert config.recent_message_window == 10


@pytest.mark.parametrize("field,value", [
    ("context_compaction_threshold_percent", 0), ("context_compaction_threshold_percent", -1),
    ("context_compaction_threshold_percent", 101), ("context_compaction_threshold_percent", 150),
    ("max_conversation_tokens_estimate", 0), ("max_conversation_tokens_estimate", -1),
    ("tool_observation_retention", 0), ("tool_observation_retention", -1),
    ("recent_message_window", 0), ("recent_message_window", -1),
])
def test_invalid_persistence_fields_are_rejected(tmp_path, field, value):
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), **{field: value})


@pytest.mark.parametrize("bad_dir", ["", "   ", "../escape", "/absolute", "C:\\absolute"])
def test_agent_data_dir_rejects_empty_or_escaping_values(tmp_path, bad_dir):
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), agent_data_dir=bad_dir)


def test_existing_defaults_unaffected_by_new_fields(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.session_mode == SessionMode.AUTO
    assert config.max_output_retries == 3
    assert config.max_clarification_rounds == 3
    assert config.max_fix_iterations == 3
    assert config.max_plan_research_rounds == 3
    assert config.review_mode_allows_test_run is False
