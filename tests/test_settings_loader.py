import pytest

from agent_platform.settings.loader import (
    SettingsValidationError,
    load_settings_file,
    merge_settings,
    parse_settings,
)
from agent_platform.settings.schema import (
    AgentBehaviorSettings,
    McpServerSettingsEntry,
    ModelSettings,
    WorkspaceSettings,
)


# ----------------------------------------------------------- load_settings_file

def test_load_settings_file_returns_none_for_missing_file(tmp_path):
    assert load_settings_file(tmp_path / "does_not_exist.yaml") is None


def test_load_settings_file_parses_valid_yaml(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("models:\n  planner: phi4-reasoning:plus\n", encoding="utf-8")
    raw = load_settings_file(path)
    assert raw == {"models": {"planner": "phi4-reasoning:plus"}}


def test_load_settings_file_rejects_malformed_yaml(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("models: [this is not\n  valid: yaml:\n", encoding="utf-8")
    with pytest.raises(SettingsValidationError):
        load_settings_file(path)


def test_load_settings_file_never_constructs_arbitrary_python_objects(tmp_path):
    """safe_load, never full load - a YAML tag that would instantiate an
    arbitrary Python object must be rejected, not silently executed."""
    path = tmp_path / "settings.yaml"
    path.write_text("models: !!python/object/apply:os.system ['echo pwned']\n", encoding="utf-8")
    with pytest.raises(SettingsValidationError):
        load_settings_file(path)


# ----------------------------------------------------------------- parse_settings

def test_parse_settings_none_returns_all_defaults():
    settings = parse_settings(None)
    assert settings == WorkspaceSettings()


def test_parse_settings_full_example():
    raw = {
        "models": {"planner": "phi4-reasoning:plus", "coder": "qwen2.5-coder:14b",
                    "reviewer": "phi4-reasoning:plus"},
        "mcp": {"github": {"enabled": True, "capabilities": ["repository.read", "pull_request.read"],
                            "credential": "github"}},
        "agent_behavior": {"max_fix_iterations": 5, "context_compaction_threshold_percent": 80},
    }
    settings = parse_settings(raw)
    assert settings.models.planner == "phi4-reasoning:plus"
    assert settings.models.coder == "qwen2.5-coder:14b"
    assert settings.mcp["github"].capabilities == ("repository.read", "pull_request.read")
    assert settings.mcp["github"].credential_reference == "github"
    assert settings.agent_behavior.max_fix_iterations == 5
    assert settings.agent_behavior.context_compaction_threshold_percent == 80


def test_parse_settings_rejects_unknown_top_level_key():
    with pytest.raises(SettingsValidationError):
        parse_settings({"totally_unknown_section": {}})


def test_parse_settings_rejects_non_mapping_root():
    with pytest.raises(SettingsValidationError):
        parse_settings(["not", "a", "mapping"])


def test_parse_settings_rejects_unknown_model_key():
    with pytest.raises(SettingsValidationError):
        parse_settings({"models": {"planner": "x", "unexpected_field": "y"}})


def test_parse_settings_rejects_non_string_model_value():
    with pytest.raises(SettingsValidationError):
        parse_settings({"models": {"planner": 12345}})


def test_parse_settings_rejects_unknown_mcp_entry_key():
    with pytest.raises(SettingsValidationError):
        parse_settings({"mcp": {"github": {"capabilities": [], "totally_unexpected": True}}})


def test_parse_settings_rejects_non_mapping_mcp_entry():
    with pytest.raises(SettingsValidationError):
        parse_settings({"mcp": {"github": "not-a-mapping"}})


def test_parse_settings_rejects_non_list_capabilities():
    with pytest.raises(SettingsValidationError):
        parse_settings({"mcp": {"github": {"capabilities": "repository.read"}}})


def test_parse_settings_rejects_unknown_agent_behavior_key():
    with pytest.raises(SettingsValidationError):
        parse_settings({"agent_behavior": {"max_fix_iterations": 3, "not_a_real_field": True}})


def test_parse_settings_mcp_entry_defaults():
    settings = parse_settings({"mcp": {"github": {}}})
    entry = settings.mcp["github"]
    assert entry.enabled is True
    assert entry.transport == "stdio"
    assert entry.capabilities == ()
    assert entry.credential_reference is None


# ---------------------------------------------------------------- merge_settings

def test_merge_settings_both_none_returns_defaults():
    assert merge_settings(None, None) == WorkspaceSettings()


def test_merge_settings_workspace_overrides_models_section_wholesale():
    global_ = WorkspaceSettings(models=ModelSettings(planner="global-planner", coder="global-coder"))
    workspace = WorkspaceSettings(models=ModelSettings(planner="workspace-planner"))
    merged = merge_settings(global_, workspace)
    assert merged.models.planner == "workspace-planner"
    assert merged.models.coder is None  # wholesale override, not deep-merged


def test_merge_settings_falls_back_to_global_when_workspace_section_absent():
    global_ = WorkspaceSettings(models=ModelSettings(planner="global-planner"))
    workspace = WorkspaceSettings()  # no models section at all
    merged = merge_settings(global_, workspace)
    assert merged.models.planner == "global-planner"


def test_merge_settings_mcp_section_overrides_wholesale():
    global_ = WorkspaceSettings(mcp={"docs": McpServerSettingsEntry(server_id="docs")})
    workspace = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(server_id="github")})
    merged = merge_settings(global_, workspace)
    assert set(merged.mcp.keys()) == {"github"}


def test_merge_settings_agent_behavior_overrides_wholesale():
    global_ = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(max_fix_iterations=2))
    workspace = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(max_clarification_rounds=7))
    merged = merge_settings(global_, workspace)
    assert merged.agent_behavior.max_clarification_rounds == 7
    assert merged.agent_behavior.max_fix_iterations is None  # wholesale, not deep-merged
