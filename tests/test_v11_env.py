import sys
import tomllib
from pathlib import Path
from typing import cast

import zeit

ROOT = Path(__file__).resolve().parents[1]


def _table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return _table(tomllib.load(fh))


def test_requires_python_at_least_3_14() -> None:
    project = _table(_pyproject()["project"])
    assert project["requires-python"] == ">=3.14"
    assert sys.version_info >= (3, 14)


def test_import_zeit_from_src() -> None:
    package_file = zeit.__file__
    assert package_file is not None
    package_dir = Path(package_file).resolve().parent
    assert package_dir == (ROOT / "src" / "zeit").resolve()


def test_ruff_targets_py314() -> None:
    ruff = _table(_table(_pyproject()["tool"])["ruff"])
    assert ruff["target-version"] == "py314"


def test_basedpyright_strict() -> None:
    basedpyright = _table(_table(_pyproject()["tool"])["basedpyright"])
    assert basedpyright["typeCheckingMode"] == "strict"
    assert basedpyright["pythonVersion"] == "3.14"


def test_makefile_lint_is_check_only() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "ruff check" in makefile
    assert "ruff format --check" in makefile
    assert "basedpyright" in makefile
