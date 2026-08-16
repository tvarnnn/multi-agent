import pytest

from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def sandbox(workspace):
    return FilesystemSandbox(workspace)


# Property: any number of "../" segments sufficient to escape the *active
# project scope* must be denied, regardless of how deep the legitimate
# prefix looks. Scoped to MyProj (not just the workspace root) because a
# single ".." from MyProj legitimately lands back in the workspace root
# itself, which is a correct ALLOW when nothing narrower is in scope -
# the property this test actually checks is project-scope containment.
@pytest.mark.parametrize("depth", list(range(1, 21)))
def test_traversal_depth_matrix_is_always_denied(sandbox, workspace, depth):
    scope = (workspace / "MyProj").resolve()
    traversal = "../" * depth + "outside.txt"
    decision = sandbox.authorize(traversal, scope_root=scope)
    assert not decision.allowed


# Property: mixing slash styles doesn't change the outcome.
@pytest.mark.parametrize("traversal", [
    "..\\..\\outside.txt",
    "../..\\outside.txt",
    "..\\../outside.txt",
    "MyProj/../..\\outside.txt",
])
def test_traversal_with_mixed_separators_is_denied(sandbox, traversal):
    decision = sandbox.authorize(traversal)
    assert not decision.allowed


# Property: every reserved device name is denied regardless of case,
# extension, or position in a longer path.
_RESERVED = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]


@pytest.mark.parametrize("name", _RESERVED)
@pytest.mark.parametrize("case_fn", [str.upper, str.lower, str.title])
@pytest.mark.parametrize("suffix", ["", ".txt", ".py", "."])
def test_reserved_device_name_matrix(sandbox, name, case_fn, suffix):
    decision = sandbox.authorize(f"MyProj/{case_fn(name)}{suffix}")
    assert not decision.allowed


# Property: trailing dots/spaces on a component (a well-known Windows
# quirk where CreateFile strips them) must not create a bypass - a
# request that would otherwise be denied stays denied with these appended.
@pytest.mark.parametrize("mutator", [
    lambda s: s + ".",
    lambda s: s + " ",
    lambda s: s + "..",
    lambda s: s + "  ",
])
def test_traversal_with_trailing_dot_or_space_is_still_denied(sandbox, mutator):
    decision = sandbox.authorize(mutator("MyProj/../../outside.txt"))
    assert not decision.allowed


# Property: absolute escape attempts at varying depth outside the
# workspace are all denied.
@pytest.mark.parametrize("suffix", [
    "Outside",
    "Outside/deeper",
    "Outside/deeper/still",
])
def test_absolute_escape_depth_matrix(sandbox, workspace, suffix):
    outside_root = workspace.parent / "NotProjects"
    decision = sandbox.authorize(str(outside_root / suffix))
    assert not decision.allowed


# Property: near-miss sibling directory names (prefix or suffix overlap
# with the real workspace name) are all denied - guards the relative_to
# containment approach across more than one concrete sibling name.
@pytest.mark.parametrize("sibling_name", [
    "ProjectsEvil", "ProjectsX", "XProjects", "Project", "Projects2",
    "Projects.evil", "Projects-backup",
])
def test_sibling_name_matrix_is_denied(sandbox, workspace, sibling_name):
    sibling = workspace.parent / sibling_name / "file.txt"
    decision = sandbox.authorize(str(sibling))
    assert not decision.allowed


# Property: malformed / empty-ish inputs are all denied, never raise.
@pytest.mark.parametrize("raw", ["", " ", "\t", "\n", "\x00", "a\x00b", "   \x00   "])
def test_malformed_input_matrix_is_denied_not_raised(sandbox, raw):
    decision = sandbox.authorize(raw)
    assert not decision.allowed
