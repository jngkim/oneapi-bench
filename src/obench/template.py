"""Placeholder substitution for commands, parameters and paths.

``{name}`` is replaced by a variable from the run context. Shell syntax such
as ``${HOME}`` is left untouched. A value that starts with ``=`` is evaluated
as arithmetic after substitution, e.g. ``"=256 * {total_devices}"``; only
numbers, + - * / // % **, parentheses and min/max/int/round are allowed.
"""

import ast
import operator
import re

from .config import ConfigError

_PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_]*)\}")

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_FUNCS = {"min": min, "max": max, "int": int, "round": round}


class UnknownPlaceholder(ConfigError):
    def __init__(self, message, name):
        ConfigError.__init__(self, message)
        self.name = name


def placeholders(text):
    return set(_PLACEHOLDER.findall(text))


def substitute(text, variables, where="template"):
    def repl(match):
        key = match.group(1)
        if key not in variables:
            raise UnknownPlaceholder("%s: unknown placeholder {%s}\n  known: %s"
                                     % (where, key, ", ".join(sorted(variables))), key)
        return _format(variables[key])
    return _PLACEHOLDER.sub(repl, text)


def _format(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return " ".join(_format(v) for v in value)
    return str(value)


def evaluate(expr, where="expression"):
    try:
        tree = ast.parse(expr.strip(), mode="eval")
        return _eval(tree.body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise ConfigError("%s: cannot evaluate '%s': %s" % (where, expr, exc))


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords):
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("only arithmetic is allowed")


def render_value(value, variables, where):
    """Render one parameter value: substitute, then evaluate '=expr'."""
    if isinstance(value, list):
        return [render_value(v, variables, where) for v in value]
    if not isinstance(value, str):
        return value
    text = substitute(value, variables, where)
    if text.startswith("="):
        result = evaluate(text[1:], where)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return result
    return text


def render_params(params, variables, where="params"):
    """Render parameters; they may refer to each other in any order."""
    out = {}
    scope = dict(variables)
    pending = dict(params)
    while pending:
        progress = False
        for key in list(pending):
            try:
                out[key] = render_value(pending[key], scope, "%s.%s" % (where, key))
            except UnknownPlaceholder as exc:
                if exc.name in pending and exc.name != key:
                    continue  # depends on a parameter not rendered yet
                raise
            scope[key] = out[key]
            del pending[key]
            progress = True
        if not progress:
            raise ConfigError("%s: parameters refer to each other in a cycle: %s"
                              % (where, ", ".join(sorted(pending))))
    return {key: out[key] for key in params}
