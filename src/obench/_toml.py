"""Minimal TOML reader used only when neither ``tomllib`` nor ``tomli`` exists.

HPC login nodes often ship Python 3.9/3.10 without ``tomli`` and without
internet access for pip. This parser supports the TOML subset used by the
configuration files in this repository: tables, arrays of tables, dotted and
quoted keys, basic/literal (multi-line) strings, integers, floats, booleans,
arrays and inline tables. Dates and times are rejected with a clear error.
"""

import re

__all__ = ["loads", "TOMLDecodeError"]


class TOMLDecodeError(ValueError):
    pass


_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_NUMBER = re.compile(
    r"[+-]?(?:0|[1-9](?:_?[0-9])*)(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?"
)
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def loads(text):
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text):
        self.s = text.replace("\r\n", "\n")
        self.i = 0
        self.n = len(self.s)

    # -- helpers -----------------------------------------------------------
    def error(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        raise TOMLDecodeError("line %d: %s" % (line, msg))

    def peek(self, k=1):
        return self.s[self.i:self.i + k]

    def skip_ws(self):
        while self.i < self.n and self.s[self.i] in " \t":
            self.i += 1

    def skip_comment(self):
        if self.peek() == "#":
            while self.i < self.n and self.s[self.i] != "\n":
                self.i += 1

    def skip_blank(self):
        """Skip whitespace, newlines and comments."""
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\n":
                self.i += 1
            elif c == "#":
                self.skip_comment()
            else:
                break

    def expect(self, token):
        if not self.s.startswith(token, self.i):
            self.error("expected %r" % token)
        self.i += len(token)

    def expect_eol(self):
        self.skip_ws()
        self.skip_comment()
        if self.i < self.n:
            if self.s[self.i] != "\n":
                self.error("unexpected text %r" % self.s[self.i:self.i + 20])
            self.i += 1

    # -- document ----------------------------------------------------------
    def parse(self):
        root = {}
        current = root
        while True:
            self.skip_blank()
            if self.i >= self.n:
                return root
            if self.peek(2) == "[[":
                self.i += 2
                self.skip_ws()
                keys = self.parse_key()
                self.skip_ws()
                self.expect("]]")
                current = self.array_table(root, keys)
            elif self.peek() == "[":
                self.i += 1
                self.skip_ws()
                keys = self.parse_key()
                self.skip_ws()
                self.expect("]")
                current = self.table(root, keys)
            else:
                keys = self.parse_key()
                self.skip_ws()
                self.expect("=")
                self.skip_ws()
                self.assign(current, keys, self.parse_value())
            self.expect_eol()

    def descend(self, table, key):
        node = table.setdefault(key, {})
        if isinstance(node, list):
            node = node[-1]
        if not isinstance(node, dict):
            self.error("key %r is already a value, not a table" % key)
        return node

    def table(self, root, keys):
        node = root
        for k in keys:
            node = self.descend(node, k)
        return node

    def array_table(self, root, keys):
        node = root
        for k in keys[:-1]:
            node = self.descend(node, k)
        arr = node.setdefault(keys[-1], [])
        if not isinstance(arr, list):
            self.error("key %r is not an array of tables" % keys[-1])
        arr.append({})
        return arr[-1]

    def assign(self, table, keys, value):
        for k in keys[:-1]:
            table = self.descend(table, k)
        if keys[-1] in table:
            self.error("duplicate key %r" % keys[-1])
        table[keys[-1]] = value

    # -- keys and values ---------------------------------------------------
    def parse_key(self):
        keys = []
        while True:
            c = self.peek()
            if c == '"':
                keys.append(self.basic_string())
            elif c == "'":
                keys.append(self.literal_string())
            else:
                m = _BARE_KEY.match(self.s, self.i)
                if not m:
                    self.error("invalid key")
                keys.append(m.group())
                self.i = m.end()
            self.skip_ws()
            if self.peek() != ".":
                return keys
            self.i += 1
            self.skip_ws()

    def parse_value(self):
        c = self.peek()
        if self.peek(3) == '"""':
            return self.ml_basic_string()
        if c == '"':
            return self.basic_string()
        if self.peek(3) == "'''":
            return self.ml_literal_string()
        if c == "'":
            return self.literal_string()
        if c == "[":
            return self.array()
        if c == "{":
            return self.inline_table()
        for word, value in (("true", True), ("false", False)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return value
        m = _NUMBER.match(self.s, self.i)
        if m:
            if self.s[m.end():m.end() + 1] in ("-", ":"):
                self.error("dates and times are not supported")
            self.i = m.end()
            text = m.group().replace("_", "")
            if any(ch in text for ch in ".eE"):
                return float(text)
            return int(text)
        self.error("invalid value")

    def array(self):
        self.i += 1
        items = []
        while True:
            self.skip_blank()
            if self.peek() == "]":
                self.i += 1
                return items
            items.append(self.parse_value())
            self.skip_blank()
            if self.peek() == ",":
                self.i += 1
            elif self.peek() == "]":
                self.i += 1
                return items
            else:
                self.error("expected ',' or ']' in array")

    def inline_table(self):
        self.i += 1
        table = {}
        self.skip_ws()
        if self.peek() == "}":
            self.i += 1
            return table
        while True:
            self.skip_ws()
            keys = self.parse_key()
            self.skip_ws()
            self.expect("=")
            self.skip_ws()
            self.assign(table, keys, self.parse_value())
            self.skip_ws()
            if self.peek() == ",":
                self.i += 1
            elif self.peek() == "}":
                self.i += 1
                return table
            else:
                self.error("expected ',' or '}' in inline table")

    def escape(self):
        self.i += 1  # backslash
        c = self.peek()
        if c in _ESCAPES:
            self.i += 1
            return _ESCAPES[c]
        if c in ("u", "U"):
            width = 4 if c == "u" else 8
            digits = self.s[self.i + 1:self.i + 1 + width]
            if len(digits) != width or not all(d in "0123456789abcdefABCDEF" for d in digits):
                self.error("invalid unicode escape")
            self.i += 1 + width
            return chr(int(digits, 16))
        self.error("invalid escape sequence")

    def basic_string(self):
        self.i += 1
        out = []
        while True:
            if self.i >= self.n or self.s[self.i] == "\n":
                self.error("unterminated string")
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                out.append(self.escape())
            else:
                out.append(c)
                self.i += 1

    def ml_basic_string(self):
        self.i += 3
        if self.peek() == "\n":
            self.i += 1
        out = []
        while True:
            if self.i >= self.n:
                self.error("unterminated multi-line string")
            if self.peek(3) == '"""':
                self.i += 3
                return "".join(out)
            c = self.s[self.i]
            if c == "\\":
                rest = re.match(r"\\[ \t]*\n[ \t\n]*", self.s[self.i:])
                if rest:  # line-ending backslash trims following whitespace
                    self.i += rest.end()
                else:
                    out.append(self.escape())
            else:
                out.append(c)
                self.i += 1

    def literal_string(self):
        self.i += 1
        end = self.s.find("'", self.i)
        if end < 0 or "\n" in self.s[self.i:end]:
            self.error("unterminated literal string")
        value = self.s[self.i:end]
        self.i = end + 1
        return value

    def ml_literal_string(self):
        self.i += 3
        if self.peek() == "\n":
            self.i += 1
        end = self.s.find("'''", self.i)
        if end < 0:
            self.error("unterminated multi-line literal string")
        value = self.s[self.i:end]
        self.i = end + 3
        return value
