from agent_platform.events import EventLog
from agent_platform.context.discovery import (
    classify_file,
    extract_imports,
    is_sensitive_path,
    parse_changed_files,
    resolve_import_to_path,
    walk_project_tree,
)
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def test_parse_changed_files_handles_modified_added_and_untracked():
    output = " M app.py\nA  new_module.py\n?? scratch.txt\n"
    assert parse_changed_files(output) == ("app.py", "new_module.py", "scratch.txt")


def test_parse_changed_files_handles_renames():
    output = "R  old_name.py -> new_name.py\n"
    assert parse_changed_files(output) == ("new_name.py",)


def test_parse_changed_files_ignores_blank_lines():
    assert parse_changed_files("\n  \n M app.py\n") == ("app.py",)


def test_parse_changed_files_on_empty_output():
    assert parse_changed_files("") == ()


def test_classify_file_recognizes_tests():
    assert classify_file("tests/test_app.py") == "test"
    assert classify_file("app_test.py") == "other"  # only the test_*.py convention is recognized


def test_classify_file_recognizes_config():
    assert classify_file("pyproject.toml") == "config"
    assert classify_file("requirements.txt") == "config"
    assert classify_file("requirements-dev.txt") == "config"


def test_classify_file_recognizes_documentation():
    assert classify_file("README.md") == "documentation"
    assert classify_file("docs/guide.rst") == "documentation"


def test_classify_file_default_is_other():
    assert classify_file("src/app.py") == "other"


def test_extract_imports_finds_top_level_import_and_from_import():
    content = "import os\nfrom agent_platform.security.enums import Role\nimport json as j\n"
    names = extract_imports(content)
    assert "os" in names
    assert "agent_platform" in names
    assert "json" in names


def test_extract_imports_on_content_with_no_imports():
    assert extract_imports("x = 1\ny = 2\n") == []


def test_resolve_import_to_path_matches_module_file():
    tree = ["app.py", "utils.py", "tests/test_app.py"]
    assert resolve_import_to_path("utils", tree) == "utils.py"


def test_resolve_import_to_path_matches_package_init():
    tree = ["mypackage/__init__.py", "mypackage/core.py"]
    assert resolve_import_to_path("mypackage", tree) == "mypackage/__init__.py"


def test_resolve_import_to_path_returns_none_for_unresolvable_import():
    tree = ["app.py"]
    assert resolve_import_to_path("numpy", tree) is None


def test_walk_project_tree_finds_all_files_and_skips_noise_dirs(tmp_path):
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "mod.py").write_text("y = 2", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_text("", encoding="utf-8")

    sandbox = FilesystemSandbox(tmp_path.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    tree = walk_project_tree(gateway, Role.PLANNER, SessionMode.AUTO, tmp_path, max_depth=6)
    assert "app.py" in tree
    assert "sub/mod.py" in tree
    assert not any("__pycache__" in p for p in tree)


def test_walk_project_tree_respects_max_depth(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x = 1", encoding="utf-8")
    sandbox = FilesystemSandbox(tmp_path.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    tree = walk_project_tree(gateway, Role.PLANNER, SessionMode.AUTO, tmp_path, max_depth=0)
    assert "a/b/c/deep.py" not in tree


# ---------------------------------- sensitive-file exclusion (structural)

def test_is_sensitive_path_matches_dotenv_and_variants():
    assert is_sensitive_path(".env")
    assert is_sensitive_path(".env.local")
    assert is_sensitive_path(".env.production")


def test_is_sensitive_path_matches_credential_and_key_files():
    assert is_sensitive_path("id_rsa")
    assert is_sensitive_path("id_ed25519")
    assert is_sensitive_path("credentials.json")
    assert is_sensitive_path("secrets.yaml")
    assert is_sensitive_path(".npmrc")
    assert is_sensitive_path(".netrc")
    assert is_sensitive_path("server.pem")
    assert is_sensitive_path("private.key")


def test_is_sensitive_path_is_case_insensitive():
    assert is_sensitive_path(".ENV")
    assert is_sensitive_path("ID_RSA")


def test_is_sensitive_path_does_not_flag_ordinary_files():
    assert not is_sensitive_path("main.py")
    assert not is_sensitive_path("id_rsa.pub")  # public key - not secret
    assert not is_sensitive_path("environment.py")
    assert not is_sensitive_path("keyboard.py")


def test_walk_project_tree_excludes_dotenv_file(tmp_path):
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=sk-supersecret", encoding="utf-8")
    (tmp_path / ".env.local").write_text("DB_PASSWORD=hunter2", encoding="utf-8")
    sandbox = FilesystemSandbox(tmp_path.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    tree = walk_project_tree(gateway, Role.PLANNER, SessionMode.AUTO, tmp_path, max_depth=6)
    assert "app.py" in tree
    assert ".env" not in tree
    assert ".env.local" not in tree


def test_walk_project_tree_excludes_ssh_directory_entirely(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    sandbox = FilesystemSandbox(tmp_path.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    tree = walk_project_tree(gateway, Role.PLANNER, SessionMode.AUTO, tmp_path, max_depth=6)
    assert not any(".ssh" in p for p in tree)


def test_walk_project_tree_excludes_credential_files_in_subdirectories(tmp_path):
    sub = tmp_path / "config"
    sub.mkdir()
    (sub / "credentials.json").write_text('{"key": "secret"}', encoding="utf-8")
    (sub / "settings.py").write_text("DEBUG = True", encoding="utf-8")
    sandbox = FilesystemSandbox(tmp_path.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    tree = walk_project_tree(gateway, Role.PLANNER, SessionMode.AUTO, tmp_path, max_depth=6)
    assert "config/settings.py" in tree
    assert "config/credentials.json" not in tree
