"""Recursive-descent parser producing a dict AST for the Pine subset."""
from __future__ import annotations
from .lexer import tokenize


class PineSyntaxError(Exception):
    pass


class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0
        self._cs = 0

    def cs(self):
        self._cs += 1
        return self._cs

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("EOF", "", -1)

    def nxt(self):
        x = self.t[self.i]
        self.i += 1
        return x

    def at(self, typ, val=None):
        x = self.peek()
        return x[0] == typ and (val is None or x[1] == val)

    def accept(self, typ, val=None):
        if self.at(typ, val):
            return self.nxt()
        return None

    def expect(self, typ, val=None):
        if not self.at(typ, val):
            x = self.peek()
            raise PineSyntaxError(f"line {x[2]}: expected {typ} {val or ''}, got {x[0]} '{x[1]}'")
        return self.nxt()

    def skipnl(self):
        while self.at("NEWLINE") or self.at("INDENT") or self.at("DEDENT"):
            self.nxt()

    # ---- entry ----
    def parse(self):
        out = []
        self.skipnl()
        while not self.at("EOF"):
            out.append(self.stmt())
            self.skipnl()
        return out

    def block(self):
        self.expect("NEWLINE") if self.at("NEWLINE") else None
        self.expect("INDENT")
        body = []
        while not self.at("DEDENT") and not self.at("EOF"):
            body.append(self.stmt())
            while self.at("NEWLINE"):
                self.nxt()
        self.accept("DEDENT")
        return body

    # ---- statements ----
    def stmt(self):
        if self.at("KW", "if"):
            return self.if_stmt()
        if self.at("KW", "for"):
            return self.for_stmt()
        if self.at("KW", "while"):
            return self.while_stmt()
        if self.at("KW", "break"):
            self.nxt()
            return {"t": "break"}
        if self.at("KW", "continue"):
            self.nxt()
            return {"t": "continue"}
        if self.at("KW") and self.peek()[1] in ("import", "export", "type", "enum", "method"):
            # skip declaration line + optional block
            while not self.at("NEWLINE") and not self.at("EOF"):
                self.nxt()
            self.accept("NEWLINE")
            if self.at("INDENT"):
                self.block()
            return {"t": "noop"}

        is_var = False
        if self.at("KW", "var") or self.at("KW", "varip"):
            self.nxt()
            is_var = True

        # optional type annotation:  var/simple/series <type> name = ...
        while self.at("KW") and self.peek()[1] in ("simple", "series", "const"):
            self.nxt()
        if self.at("NAME") and self.peek(1)[0] == "NAME" and self.peek(2)[0] == "OP" \
                and self.peek(2)[1] in ("=", "["):
            self.nxt()

        if self.at("OP", "["):
            self.nxt()
            names = [self.expect("NAME")[1]]
            while self.accept("OP", ","):
                names.append(self.expect("NAME")[1])
            self.expect("OP", "]")
            self.expect("OP", "=")
            e = self.expr()
            return {"t": "massign", "names": names, "expr": e, "var": is_var}

        if self.at("NAME"):
            save = self.i
            names = [self.nxt()[1]]
            while self.at("OP", ",") and self.peek(1)[0] == "NAME":
                self.nxt()
                names.append(self.nxt()[1])
            if self.at("OP", "="):
                self.nxt()
                e = self.expr()
                if len(names) == 1:
                    return {"t": "assign", "name": names[0], "expr": e, "var": is_var}
                return {"t": "massign", "names": names, "expr": e, "var": is_var}
            if len(names) == 1 and self.at("OP", ":="):
                self.nxt()
                return {"t": "reassign", "name": names[0], "expr": self.expr()}
            self.i = save

        e = self.expr()
        if self.at("OP", "=>"):
            self.nxt()
            return self.func_def(e, is_var)
        return {"t": "exprstmt", "expr": e}

    def func_def(self, head, is_var):
        if head["t"] != "call":
            raise PineSyntaxError("invalid function definition")
        params = []
        for nm, val in head["args"]:
            if nm is not None:
                params.append((nm, val))
            elif val["t"] == "name":
                params.append((val["v"], None))
            else:
                raise PineSyntaxError("bad function parameter")
        if self.at("NEWLINE"):
            body = self.block()
            single = False
        else:
            body = self.expr()
            single = True
        return {"t": "func", "name": head["name"], "params": params, "body": body, "single": single}

    def if_stmt(self):
        self.expect("KW", "if")
        cond = self.expr()
        then = self.block()
        elifs = []
        els = None
        while self.at("KW", "else"):
            self.nxt()
            if self.at("KW", "if"):
                self.nxt()
                c = self.expr()
                b = self.block()
                elifs.append((c, b))
            else:
                els = self.block()
                break
        return {"t": "if", "cond": cond, "then": then, "elifs": elifs, "els": els}

    def for_stmt(self):
        self.expect("KW", "for")
        var = self.expect("NAME")[1]
        self.expect("OP", "=")
        frm = self.expr()
        self.expect("KW", "to")
        to = self.expr()
        by = None
        if self.accept("KW", "by"):
            by = self.expr()
        body = self.block()
        return {"t": "for", "var": var, "frm": frm, "to": to, "by": by, "body": body}

    def while_stmt(self):
        self.expect("KW", "while")
        cond = self.expr()
        body = self.block()
        return {"t": "while", "cond": cond, "body": body}

    # ---- expressions ----
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.logic_or()
        if self.accept("OP", "?"):
            a = self.ternary()
            self.expect("OP", ":")
            b = self.ternary()
            return {"t": "tern", "c": c, "a": a, "b": b}
        return c

    def _binl(self, sub, ops):
        e = sub()
        while self.at("OP") and self.peek()[1] in ops:
            op = self.nxt()[1]
            e = {"t": "bin", "op": op, "l": e, "r": sub()}
        return e

    def logic_or(self):
        return self._binl(self.logic_and, {"or"})

    def logic_and(self):
        return self._binl(self.equality, {"and"})

    def equality(self):
        return self._binl(self.comparison, {"==", "!="})

    def comparison(self):
        return self._binl(self.term, {"<", ">", "<=", ">="})

    def term(self):
        return self._binl(self.factor, {"+", "-"})

    def factor(self):
        return self._binl(self.unary, {"*", "/", "%"})

    def unary(self):
        if self.at("OP") and self.peek()[1] in ("not", "-", "+"):
            op = self.nxt()[1]
            return {"t": "un", "op": op, "e": self.unary()}
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.accept("OP", "["):
                idx = self.expr()
                self.expect("OP", "]")
                e = {"t": "index", "e": e, "i": idx}
            elif self.at("OP", ".") and self.peek(1)[0] == "NAME":
                self.nxt()
                e = {"t": "member", "e": e, "name": self.nxt()[1]}
            elif self.accept("OP", "("):
                args = self.args()
                self.expect("OP", ")")
                e = {"t": "call", "name": self._dotted(e), "fn": e, "args": args, "cs": self.cs()}
            else:
                return e

    def _dotted(self, e):
        if e["t"] == "name":
            return e["v"]
        if e["t"] == "member":
            return self._dotted(e["e"]) + "." + e["name"]
        return None

    def args(self):
        out = []
        if self.at("OP", ")"):
            return out
        while True:
            nm = None
            if self.at("NAME") and self.peek(1)[0] == "OP" and self.peek(1)[1] == "=":
                nm = self.nxt()[1]
                self.nxt()
            out.append((nm, self.expr()))
            if not self.accept("OP", ","):
                break
        return out

    def primary(self):
        x = self.peek()
        if x[0] == "NUM":
            self.nxt()
            return {"t": "num", "v": x[1]}
        if x[0] == "STR":
            self.nxt()
            return {"t": "str", "v": x[1]}
        if self.at("KW", "true"):
            self.nxt()
            return {"t": "bool", "v": True}
        if self.at("KW", "false"):
            self.nxt()
            return {"t": "bool", "v": False}
        if self.at("KW", "na"):
            self.nxt()
            return {"t": "na"}
        if self.at("KW", "input"):
            self.nxt()
            return {"t": "name", "v": "input"}
        if self.at("KW", "switch"):
            return self.switch_expr()
        if self.at("KW", "if"):
            return self.if_expr()
        if self.accept("OP", "("):
            e = self.expr()
            self.expect("OP", ")")
            return e
        if x[0] == "NAME":
            self.nxt()
            return {"t": "name", "v": x[1]}
        raise PineSyntaxError(f"line {x[2]}: unexpected {x[0]} '{x[1]}'")

    def switch_expr(self):
        self.expect("KW", "switch")
        subj = None
        if not self.at("NEWLINE"):
            subj = self.expr()
        self.expect("NEWLINE")
        self.expect("INDENT")
        cases = []
        while not self.at("DEDENT") and not self.at("EOF"):
            if self.accept("OP", "=>"):
                cases.append((None, self.expr()))
            else:
                cond = self.expr()
                self.expect("OP", "=>")
                cases.append((cond, self.expr()))
            while self.at("NEWLINE"):
                self.nxt()
        self.accept("DEDENT")
        return {"t": "switch", "subj": subj, "cases": cases}

    def if_expr(self):
        self.expect("KW", "if")
        cond = self.expr()
        then = self.block()
        els = None
        elifs = []
        while self.at("KW", "else"):
            self.nxt()
            if self.at("KW", "if"):
                self.nxt()
                c = self.expr()
                elifs.append((c, self.block()))
            else:
                els = self.block()
                break
        return {"t": "ifexpr", "cond": cond, "then": then, "elifs": elifs, "els": els}


def parse(src: str):
    return Parser(tokenize(src)).parse()
