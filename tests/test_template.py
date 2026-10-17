import pytest

from obench.config import ConfigError
from obench.template import render_params, substitute


def test_substitute_keeps_shell_variables():
    assert substitute("{a} ${HOME} $X {b}", {"a": 1, "b": [1, 2]}) == "1 ${HOME} $X 1 2"


def test_unknown_placeholder_lists_known_names():
    with pytest.raises(ConfigError, match=r"(?s)unknown placeholder \{nope\}.*known: a"):
        substitute("{nope}", {"a": 1})


def test_params_arithmetic_and_order():
    params = {"per": 128, "nz": "={per} * {total_devices}", "cells": "64 64 {nz}"}
    out = render_params(params, {"total_devices": 4})
    assert out == {"per": 128, "nz": 512, "cells": "64 64 512"}


def test_expressions_are_arithmetic_only():
    with pytest.raises(ConfigError):
        render_params({"x": "=__import__('os')"}, {})
    assert render_params({"x": "=max(2, 3) // 2"}, {}) == {"x": 1}


def test_params_any_order_and_cycles():
    assert render_params({"path": "/d/{system}", "system": "61k"}, {}) == {"path": "/d/61k", "system": "61k"}
    with pytest.raises(ConfigError, match="cycle"):
        render_params({"a": "{b}", "b": "{a}"}, {})
