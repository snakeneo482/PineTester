"""Indentation-aware tokenizer for a Pine v5 subset."""
from __future__ import annotations
import re

KW = {"if", "else", "for", "to", "by", "while", "var", "varip", "true", "false",
      "na", "switch", "break", "continue", "import", "as", "export", "type",
      "method", "enum", "series", "simple", "const", "input"}

OPS2 = {"==", "!=", ">=", "<=", ":=", "=>", "+=", "-=", "*=", "/=", "%="}
OPS1 = set("+-*/%()[].,?:<>=")
CONT_OPS = {"+", "-", "*", "/", "%", "?", ":", "and", "or", "not", "==", "!=",
            ">=", "<=", "<", ">", "=", ":=", "=>", ",", ".", "(", "["}


def tokenize(src: str):
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    n = len(src)
    i = 0
    line = 1
    toks = []
    indent_stack = [0]
    at_line_start = True
    paren = 0

    def last_sig():
        for t in reversed(toks):
            if t[0] in ("NEWLINE", "INDENT", "DEDENT"):
                continue
            return t
        return None

    while i < n:
        c = src[i]

        if at_line_start and paren == 0:
            j = i
            ind = 0
            while j < n and src[j] in " \t":
                ind += 4 if src[j] == "\t" else 1
                j += 1
            if j >= n:
                break
            if src[j] == "\n":
                i = j + 1
                line += 1
                continue
            if src[j] == "/" and j + 1 < n and src[j + 1] == "/":
                while j < n and src[j] != "\n":
                    j += 1
                i = j
                continue
            if ind > indent_stack[-1]:
                indent_stack.append(ind)
                toks.append(("INDENT", "", line))
            else:
                while ind < indent_stack[-1]:
                    indent_stack.pop()
                    toks.append(("DEDENT", "", line))
            i = j
            at_line_start = False
            continue

        if c == "\n":
            line += 1
            i += 1
            if paren > 0:
                continue
            ls = last_sig()
            if ls and ls[0] == "OP" and ls[1] in CONT_OPS:
                while i < n and src[i] in " \t":
                    i += 1
                continue
            if toks and toks[-1][0] != "NEWLINE":
                toks.append(("NEWLINE", "", line))
            at_line_start = True
            continue

        if c in " \t":
            i += 1
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        if c in ('"', "'"):
            q = c
            j = i + 1
            buf = []
            while j < n and src[j] != q:
                if src[j] == "\\" and j + 1 < n:
                    buf.append({"n": "\n", "t": "\t"}.get(src[j + 1], src[j + 1]))
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            i = j + 1
            toks.append(("STR", "".join(buf), line))
            at_line_start = False
            continue

        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = re.match(r"(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", src[i:])
            s = m.group(0)
            i += len(s)
            toks.append(("NUM", float(s), line))
            at_line_start = False
            continue

        if c.isalpha() or c == "_":
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", src[i:])
            s = m.group(0)
            i += len(s)
            if s in ("and", "or", "not"):
                toks.append(("OP", s, line))
            elif s in KW:
                toks.append(("KW", s, line))
            else:
                toks.append(("NAME", s, line))
            at_line_start = False
            continue

        two = src[i:i + 2]
        if two in OPS2:
            toks.append(("OP", two, line))
            i += 2
            at_line_start = False
            continue
        if c in "([":
            paren += 1
            toks.append(("OP", c, line))
            i += 1
            at_line_start = False
            continue
        if c in ")]":
            paren = max(0, paren - 1)
            toks.append(("OP", c, line))
            i += 1
            at_line_start = False
            continue
        if c in OPS1:
            toks.append(("OP", c, line))
            i += 1
            at_line_start = False
            continue
        i += 1  # skip unknown

    if toks and toks[-1][0] != "NEWLINE":
        toks.append(("NEWLINE", "", line))
    while len(indent_stack) > 1:
        indent_stack.pop()
        toks.append(("DEDENT", "", line))
    toks.append(("EOF", "", line))
    return toks
