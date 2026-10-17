"""The fallback TOML parser must agree with the standard library."""

import sys

import pytest

from conftest import REPO
from obench import _toml

tomllib = pytest.importorskip("tomllib" if sys.version_info >= (3, 11) else "tomli")

SAMPLES = [
    'a = 1\nb = -2.5e3\nc = true\nd = "x\\ty\\u00e9"\ne = \'lit\\eral\'\n',
    '[t]\nx.y = 1\n"quoted key" = 2\n[t.sub]\nz = [1, 2,\n  3, # comment\n]\n',
    '[[arr]]\nname = "a"\n[[arr]]\nname = "b"\n[arr.inner]\nk = 1\n',
    'inline = { a = 1, b = { c = "d" } }\nempty = {}\nlist = [[1, 2], ["a"]]\n',
    'ml = """\nline1\nline2 \\\n   continued"""\nlit = \'\'\'\nraw \\n\'\'\'\n',
    'n = 1_000\nf = 0.5\nneg = -0\n# only a comment\n\n',
]


@pytest.mark.parametrize("text", SAMPLES)
def test_matches_stdlib(text):
    assert _toml.loads(text) == tomllib.loads(text)


def test_repository_files_parse_identically():
    files = list(REPO.glob("apps/*/app.toml")) + list(REPO.glob("apps/*/workloads/*.toml")) \
        + list(REPO.glob("sites/*.toml")) + list(REPO.glob("templates/**/*.toml"))
    assert files
    for path in files:
        text = path.read_text()
        assert _toml.loads(text) == tomllib.loads(text), path


@pytest.mark.parametrize("text", ["a = 1\na = 2\n", "a = \n", "a = \"open\n", "d = 1979-05-27\n",
                                  "[t]\nx = 1\n[t.x]\n", "a = [1 2]\n"])
def test_errors(text):
    with pytest.raises(_toml.TOMLDecodeError):
        _toml.loads(text)
