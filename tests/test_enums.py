from agent_platform.security.enums import Role, SessionMode, ToolPermission


def test_role_members():
    assert {r.name for r in Role} == {"PLANNER", "CODER", "REVIEWER"}


def test_session_mode_members():
    assert {m.name for m in SessionMode} == {"AUTO", "CONFIRMATION", "MANUAL"}


def test_tool_permission_members():
    assert {p.name for p in ToolPermission} == {"ALLOW", "CONFIRM", "DENY"}
