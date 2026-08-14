"""Minimal JSONC (JSON with comments / trailing commas) reader + surgical editor.

Parses a JSONC file preserving the raw text so that edits only touch the
specific keys involved, keeping comments and formatting intact.
"""

import json
import re


class JsoncError(ValueError):
    pass


# ---------------------------------------------------------------- tokenizer

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<linecomment>//[^\n]*)
  | (?P<blockcomment>/\*.*?\*/)
  | (?P<lbrace>\{)
  | (?P<rbrace>\})
  | (?P<lbracket>\[)
  | (?P<rbracket>\])
  | (?P<colon>:)
  | (?P<comma>,)
  | (?P<string>"(?:\\.|[^"\\])*")
  | (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<true>true)
  | (?P<false>false)
  | (?P<null>null)
    """,
    re.VERBOSE | re.DOTALL,
)

_STRIP = re.compile(r"\\\\(.)|\\\"", re.DOTALL)


def _tokenize(text):
    tokens = []  # (kind, value, start, end)
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise JsoncError("unexpected character at offset %d" % pos)
        kind = m.lastgroup
        if kind in ("ws", "linecomment", "blockcomment"):
            pos = m.end()
            continue
        tokens.append((kind, m.group(), m.start(), m.end()))
        pos = m.end()
    return tokens


def _parse_string(raw):
    # raw includes the surrounding double quotes
    body = raw[1:-1]
    body = re.sub(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})',
                  lambda m: json.loads('"%s"' % m.group(0)), body)
    return body


# ------------------------------------------------------------------ parser

class Node:
    __slots__ = ("kind", "start", "end", "value", "children")

    def __init__(self, kind, start, end, value=None, children=None):
        self.kind = kind          # 'object' | 'array' | 'primitive'
        self.start = start        # offset of first char in raw text
        self.end = end            # offset just past last char
        self.value = value        # python value for primitives
        self.children = children  # for object: [(keystr, Node)], for array: [Node]


def _parse(tokens):
    idx = 0

    def peek():
        if idx < len(tokens):
            return tokens[idx]
        return None

    def parse_value():
        nonlocal idx
        tok = peek()
        if tok is None:
            raise JsoncError("unexpected end of input")
        kind, raw, s, e = tok
        if kind in ("string", "number", "true", "false", "null"):
            idx += 1
            if kind == "string":
                val = _parse_string(raw)
            elif kind == "number":
                val = float(raw) if ("." in raw or "e" in raw or "E" in raw) else int(raw)
            elif kind == "true":
                val = True
            elif kind == "false":
                val = False
            else:
                val = None
            return Node("primitive", s, e, val)
        if kind == "lbrace":
            return parse_object()
        if kind == "lbracket":
            return parse_array()
        raise JsoncError("unexpected token '%s' at offset %d" % (raw, s))

    def parse_object():
        nonlocal idx
        open_tok = tokens[idx]
        idx += 1
        children = []
        while True:
            tok = peek()
            if tok is None:
                raise JsoncError("unterminated object")
            if tok[0] == "rbrace":
                idx += 1
                return Node("object", open_tok[2], tok[3], children=children)
            if tok[0] == "comma":
                idx += 1
                continue
            if tok[0] != "string":
                raise JsoncError("expected object key at offset %d" % tok[2])
            key = _parse_string(tok[1])
            idx += 1
            colon = peek()
            if colon is None or colon[0] != "colon":
                raise JsoncError("expected ':' after key at offset %d" % tok[2])
            idx += 1
            val = parse_value()
            children.append((key, val))

    def parse_array():
        nonlocal idx
        open_tok = tokens[idx]
        idx += 1
        children = []
        while True:
            tok = peek()
            if tok is None:
                raise JsoncError("unterminated array")
            if tok[0] == "rbracket":
                idx += 1
                return Node("array", open_tok[2], tok[3], children=children)
            if tok[0] == "comma":
                idx += 1
                continue
            children.append(parse_value())

    root = parse_value()
    if idx != len(tokens):
        raise JsoncError("trailing content at offset %d" % tokens[idx][2])
    return root


def _to_python(node):
    if node.kind == "object":
        return {k: _to_python(v) for k, v in node.children}
    if node.kind == "array":
        return [_to_python(c) for c in node.children]
    return node.value


def parse(text):
    """Return (Node, python_value)."""
    root = _parse(_tokenize(text))
    return root, _to_python(root)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse(text)


# -------------------------------------------------------------- surgical edit

def _find_object(node, path):
    """Walk path through objects/arrays, return the final child Node or None."""
    cur = node
    for part in path:
        if isinstance(part, int):
            if cur.kind != "array" or part >= len(cur.children):
                return None
            cur = cur.children[part]
        else:
            if cur.kind != "object":
                return None
            found = None
            for k, v in cur.children:
                if k == part:
                    found = v
                    break
            if found is None:
                return None
            cur = found
    return cur


def _node_to_json(value):
    return json.dumps(value, ensure_ascii=False)


def set_value(text, path, value):
    """Surgically set value at dotted/nested path. Returns updated text.

    path is a list; string entries index into objects, ints into arrays.
    Intermediate objects are created automatically when missing.
    """
    if not path:
        raise JsoncError("empty path")
    key = path[-1]
    parents = path[:-1]

    # Walk as far as the existing structure allows, creating missing
    # intermediate objects on the fly.
    node = parse(text)[0]
    cur_text = text
    for i, part in enumerate(parents):
        nxt = _find_object(node, [part])
        if nxt is None:
            cur_text = _insert_key(cur_text, node, part, {})
            node = parse(cur_text)[0]
            node = _find_object(node, parents[: i + 1])
        else:
            node = nxt
    if node.kind != "object":
        raise JsoncError("cannot set key on non-object")

    new = _node_to_json(value)
    for k, v in node.children:
        if k == key:
            # replace the value span
            return cur_text[: v.start] + new + cur_text[v.end :]
    # key does not exist: insert before closing brace
    return _insert_key(cur_text, node, key, new)


def _insert_key(text, parent, key, new):
    indent = _indent_at(text, parent.start)
    child_indent = indent + "  "
    closing = parent.end - 1  # offset of '}'
    if parent.children:
        # Determine whether a comma already precedes the closing brace.
        last_end = parent.children[-1][1].end
        tail = text[last_end:closing]
        if tail.lstrip().startswith(","):
            return text[:closing] + '  %s"%s": %s\n%s' % (
                child_indent, key, new, indent) + text[closing:]
        # Insert comma + newline right after the last value; the existing
        # gap (whitespace/comments) before '}' is preserved.
        if not tail.strip():
            return text[:last_end] + ",\n" + child_indent + '"%s": %s' % (
                key, new) + text[last_end:]
        return text[:last_end] + ", " + text[last_end:closing] + '  %s"%s": %s\n%s' % (
            child_indent, key, new, indent) + text[closing:]
    # empty object: replace the whitespace-only gap inside braces
    gap = text[parent.start + 1 : closing]
    if not gap.strip():
        return text[: parent.start + 1] + "\n" + child_indent + '"%s": %s' % (
            key, new) + "\n" + indent + text[closing:]
    return text[:closing] + '\n  %s"%s": %s\n%s' % (
        child_indent, key, new, indent) + text[closing:]


def delete_key(text, path):
    """Surgically remove a key from an object. Returns updated text."""
    root = parse(text)[0]
    key = path[-1]
    parents = path[:-1]
    parent = _find_object(root, parents) if parents else root
    if parent is None or parent.kind != "object":
        raise JsoncError("path not found")
    for i, (k, v) in enumerate(parent.children):
        if k == key:
            start = v.start
            end = v.end
            key_start = text.rfind('"%s"' % k, parent.start, start)
            if key_start < 0:
                key_start = start
            # include trailing comma if present
            after = text[end:].lstrip()
            if after.startswith(","):
                end = end + text[end:].find(",") + 1
            # strip leading whitespace of the removed line back to line start
            line_start = key_start
            while line_start > parent.start and text[line_start - 1] in " \t":
                line_start -= 1
            if line_start > parent.start and text[line_start - 1] == "\n":
                key_start = line_start
                end = end
            else:
                key_start = line_start
            newtext = text[:key_start] + text[end:]
            # remove a now-dangling comma (previous sibling trailing comma)
            before = newtext[parent.start:key_start]
            m = re.search(r",\s*$", before)
            if m:
                newtext = newtext[: parent.start + m.start()] + newtext[parent.start + m.end():]
            # collapse blank lines introduced inside the parent object
            seg = newtext[parent.start:parent.end]
            seg = re.sub(r"\n[ \t]*\n", "\n", seg)
            return newtext[: parent.start] + seg + newtext[parent.end:]
    raise JsoncError("key %r not found" % key)


def _indent_at(text, offset):
    """Return the indentation string of the line containing offset."""
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    return line[: len(line) - len(line.lstrip())]
