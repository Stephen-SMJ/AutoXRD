import pytest
from tools.file_read import FileReadTool
from tools.glob_tool import GlobTool


@pytest.fixture
def tmp_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("line one\nline two\nline three\n")
    return str(f)


def test_file_read_returns_numbered_content(tmp_file):
    result = FileReadTool().execute(file_path=tmp_file)
    assert not result.is_error
    assert "1\tline one" in result.content
    assert "2\tline two" in result.content


def test_file_read_respects_offset_and_limit(tmp_file):
    result = FileReadTool().execute(file_path=tmp_file, offset=1, limit=1)
    assert not result.is_error
    assert "line two" in result.content
    assert "line one" not in result.content


def test_file_read_missing_file():
    result = FileReadTool().execute(file_path="/nonexistent/path/file.txt")
    assert result.is_error
    assert "not found" in result.content.lower() or "no such" in result.content.lower()


def test_file_read_rejects_relative_path():
    result = FileReadTool().execute(file_path="relative.txt")
    assert result.is_error
    assert "absolute" in result.content.lower()


def test_file_read_rejects_large_image(tmp_path):
    image = tmp_path / "large.png"
    with image.open("wb") as fh:
        fh.truncate(10 * 1024 * 1024 + 1)

    result = FileReadTool().execute(file_path=str(image))

    assert result.is_error
    assert "image too large" in result.content.lower()


def test_file_read_is_read_only():
    assert FileReadTool().is_read_only() is True


def test_glob_finds_files(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    (tmp_path / "c.txt").write_text("x")

    result = GlobTool().execute(pattern="*.py", path=str(tmp_path))
    assert not result.is_error
    assert "a.py" in result.content
    assert "b.py" in result.content
    assert "c.txt" not in result.content


def test_glob_no_matches(tmp_path):
    result = GlobTool().execute(pattern="*.xyz", path=str(tmp_path))
    assert not result.is_error
    assert "No files found" in result.content


def test_glob_missing_dir():
    result = GlobTool().execute(pattern="*.py", path="/no/such/dir")
    assert result.is_error


@pytest.mark.parametrize("pattern", ["/usr/**/numpy*", "../../usr/**/*.py"])
def test_glob_rejects_patterns_that_escape_search_path(tmp_path, pattern):
    result = GlobTool().execute(pattern=pattern, path=str(tmp_path))
    assert result.is_error
    assert "relative" in result.content.lower()


def test_glob_is_read_only():
    assert GlobTool().is_read_only() is True


from tools.grep_tool import GrepTool


def test_grep_finds_pattern(tmp_path):
    (tmp_path / "a.py").write_text("def hello():\n    pass\n")
    (tmp_path / "b.py").write_text("def world():\n    pass\n")

    result = GrepTool().execute(pattern="hello", path=str(tmp_path))
    assert not result.is_error
    assert "a.py" in result.content
    assert "b.py" not in result.content


def test_grep_no_match(tmp_path):
    (tmp_path / "a.py").write_text("nothing here\n")
    result = GrepTool().execute(pattern="xyz123", path=str(tmp_path))
    assert not result.is_error
    assert "No matches" in result.content


def test_grep_case_insensitive(tmp_path):
    (tmp_path / "a.txt").write_text("Hello World\n")
    result = GrepTool().execute(pattern="hello", path=str(tmp_path), **{"-i": True})
    assert not result.is_error
    assert "a.txt" in result.content


def test_grep_is_read_only():
    assert GrepTool().is_read_only() is True


from tools.file_edit import FileEditTool
from tools.file_write import FileWriteTool


def test_file_edit_replaces_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def hello():\n    pass\n")
    FileEditTool.mark_file_read(str(f))

    result = FileEditTool().execute(
        file_path=str(f),
        old_string="    pass",
        new_string='    return "hi"',
    )
    assert not result.is_error
    assert 'return "hi"' in f.read_text()


def test_file_edit_fails_on_duplicate_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("pass\npass\n")
    FileEditTool.mark_file_read(str(f))

    result = FileEditTool().execute(file_path=str(f), old_string="pass", new_string="x")
    assert result.is_error
    assert "2" in result.content  # mentions count


def test_file_edit_replace_all(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\nx = 2\n")
    FileEditTool.mark_file_read(str(f))

    result = FileEditTool().execute(file_path=str(f), old_string="x", new_string="y", replace_all=True)
    assert not result.is_error
    assert "y = 1" in f.read_text()
    assert "y = 2" in f.read_text()


def test_file_edit_missing_file():
    result = FileEditTool().execute(
        file_path="/no/such/file.py", old_string="x", new_string="y"
    )
    assert result.is_error


def test_file_edit_rejects_relative_path():
    result = FileEditTool().execute(
        file_path="code.py", old_string="x", new_string="y"
    )
    assert result.is_error
    assert "absolute" in result.content.lower()


def test_file_edit_string_not_found(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("hello\n")
    FileEditTool.mark_file_read(str(f))
    result = FileEditTool().execute(file_path=str(f), old_string="xyz", new_string="abc")
    assert result.is_error
    assert "not found" in result.content.lower()


def test_file_write_rejects_relative_path():
    result = FileWriteTool().execute(file_path="new.txt", content="hello\n")
    assert result.is_error
    assert "absolute" in result.content.lower()


from tools.bash import BashTool


def test_bash_runs_command():
    result = BashTool().execute(command="echo hello")
    assert not result.is_error
    assert "hello" in result.content


def test_bash_captures_stderr():
    result = BashTool().execute(command="echo err >&2")
    assert "err" in result.content


def test_bash_nonzero_exit_code():
    result = BashTool().execute(command="exit 1")
    assert "exit code: 1" in result.content
    assert result.is_error
    assert result.metadata["returncode"] == 1
    assert result.metadata["timed_out"] is False


def test_bash_timeout():
    result = BashTool().execute(command="sleep 10", timeout=1)
    assert result.is_error
    assert "timed out" in result.content.lower()


def test_bash_is_not_read_only():
    assert BashTool().is_read_only() is False


def test_mkdir_does_not_change_persistent_cwd(tmp_path):
    tool = BashTool(cwd=tmp_path)
    assert not tool.execute(command="mkdir -p run_001").is_error
    result = tool.execute(command="pwd")
    assert result.content.strip() == str(tmp_path)


def test_bash_workspace_cwd_persists_after_cd(tmp_path):
    run_dir = tmp_path / "run_001"
    tool = BashTool(cwd=tmp_path)
    first = tool.execute(command=f"mkdir -p {run_dir} && cd {run_dir} && printf ready")
    assert not first.is_error
    second = tool.execute(command="pwd")
    assert str(run_dir) in second.content


def test_bash_passes_pinned_cwd_to_sandbox(tmp_path):
    class RecordingSandbox:
        def __init__(self):
            self.cwd = None

        def should_sandbox(self, command, dangerously_disable):
            return True

        def wrap(self, command, cwd=None):
            self.cwd = cwd
            return command

    sandbox = RecordingSandbox()
    result = BashTool(sandbox_manager=sandbox, cwd=tmp_path).execute(command="pwd")
    assert not result.is_error
    assert sandbox.cwd == str(tmp_path)


def test_bash_does_not_pass_string_none_to_sandbox():
    class RecordingSandbox:
        def __init__(self):
            self.cwd = "unmodified"

        def should_sandbox(self, command, dangerously_disable):
            return True

        def wrap(self, command, cwd=None):
            self.cwd = cwd
            return command

    sandbox = RecordingSandbox()
    result = BashTool(sandbox_manager=sandbox).execute(command="pwd")
    assert not result.is_error
    assert sandbox.cwd is None
