import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".ruff_cache",
    ".basedpyright",
}
SENTENCE_END = re.compile(r"""[.!?]["')\]]*$""")
SECOND_SENTENCE = re.compile(r"""(?<!\d)[.!?]["')\]]*\s+[A-Z]""")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
SPEC_ROW = re.compile(r"^(?:V\d+:|T\d+\||B\d+\||id\|)")
HEADING = re.compile(r"^#{1,6}\s")
TABLE = re.compile(r"^\s*\|")
TABLE_SEP = re.compile(r"^[\s:-|]+$")
HR = re.compile(r"^-{3,}$")
BLOCKQUOTE = re.compile(r"^\s*>")


def _project_markdown() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if SKIP_DIR_NAMES.intersection(path.parts):
            continue
        files.append(path)
    return sorted(files)


def _is_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def _is_block_start(line: str) -> bool:
    stripped = line.strip()
    if stripped == "":
        return True
    return bool(
        HEADING.match(line)
        or TABLE.match(line)
        or (TABLE_SEP.match(stripped) and "|" in stripped)
        or LIST_ITEM.match(line)
        or BLOCKQUOTE.match(line)
        or SPEC_ROW.match(line)
        or HR.match(stripped)
    )


def _is_prose(line: str) -> bool:
    stripped = line.strip()
    if stripped == "":
        return False
    if HEADING.match(line) or TABLE.match(line) or SPEC_ROW.match(line):
        return False
    if TABLE_SEP.match(stripped) and "|" in stripped:
        return False
    if HR.match(stripped) or BLOCKQUOTE.match(line):
        return False
    return True


def _ends_sentence(line: str) -> bool:
    return bool(SENTENCE_END.search(line.rstrip()))


def _prose_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    in_fence = False
    for index, raw in enumerate(text.splitlines(), start=1):
        if _is_fence(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append((index, raw))
    return lines


def test_project_has_markdown_files() -> None:
    names = {path.name for path in _project_markdown()}
    assert "README.md" in names
    assert "SPEC.md" in names


def test_markdown_sentences_do_not_wrap() -> None:
    violations: list[str] = []
    for path in _project_markdown():
        rows = _prose_lines(path.read_text())
        for (line_no, current), (_, nxt) in zip(rows, rows[1:], strict=False):
            if not _is_prose(current):
                continue
            if _is_block_start(nxt):
                continue
            if _ends_sentence(current):
                continue
            rel = path.relative_to(ROOT)
            violations.append(f"{rel}:{line_no} wraps into next line")
    assert violations == []


def test_markdown_one_sentence_per_line() -> None:
    violations: list[str] = []
    for path in _project_markdown():
        for line_no, current in _prose_lines(path.read_text()):
            if not _is_prose(current) and not LIST_ITEM.match(current):
                continue
            if not SECOND_SENTENCE.search(current):
                continue
            rel = path.relative_to(ROOT)
            violations.append(f"{rel}:{line_no} has a second sentence")
    assert violations == []
