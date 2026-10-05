from devin_clone.tools.files import EditFileTool, ReadFileTool, WriteFileTool


def test_write_and_read(tmp_path):
    w = WriteFileTool(tmp_path)
    r = w.run({"path": "a/b/hello.txt", "content": "one\ntwo\nthree\n"})
    assert not r.is_error
    assert (tmp_path / "a" / "b" / "hello.txt").read_text() == "one\ntwo\nthree\n"

    rd = ReadFileTool(tmp_path)
    out = rd.run({"path": "a/b/hello.txt"})
    assert "1\tone" in out.output
    assert "3\tthree" in out.output


def test_read_offset_limit(tmp_path):
    w = WriteFileTool(tmp_path)
    w.run({"path": "big.txt", "content": "\n".join(f"line{i}" for i in range(50))})
    rd = ReadFileTool(tmp_path)
    out = rd.run({"path": "big.txt", "offset": 10, "limit": 5})
    assert "10\tline9" in out.output
    assert "14\tline13" in out.output
    assert "line14" not in out.output
    assert "offset to continue" in out.output


def test_read_missing(tmp_path):
    rd = ReadFileTool(tmp_path)
    assert rd.run({"path": "nope.txt"}).is_error


def test_edit_unique(tmp_path):
    w = WriteFileTool(tmp_path)
    w.run({"path": "f.txt", "content": "alpha beta alpha"})
    e = EditFileTool(tmp_path)
    assert e.run({"path": "f.txt", "old_string": "alpha",
                  "new_string": "x"}).is_error  # ambiguous
    ok = e.run({"path": "f.txt", "old_string": "beta", "new_string": "BETA"})
    assert not ok.is_error
    assert (tmp_path / "f.txt").read_text() == "alpha BETA alpha"
    assert e.run({"path": "f.txt", "old_string": "zzz",
                  "new_string": "y"}).is_error


def test_path_escape_blocked(tmp_path):
    w = WriteFileTool(tmp_path)
    r = w.run({"path": "../escape.txt", "content": "x"})
    assert r.is_error
    assert not (tmp_path.parent / "escape.txt").exists()
    rd = ReadFileTool(tmp_path)
    assert rd.run({"path": "/etc/passwd"}).is_error
