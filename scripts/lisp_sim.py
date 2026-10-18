#!/usr/bin/env python3
"""lisp_sim.py - AutoLISP subset interpreter with an AutoCAD stub.

Purpose: execute a generated .lsp file outside AutoCAD so that
  * syntax/runtime errors (unbound functions, arity, bad types) surface early,
  * every entmake list is validated against DXF group-code rules,
  * the entities the script WOULD create are captured for preview/overlay.

It is not a full AutoLISP implementation. It covers the subset used by
lsp_runtime.lsp plus common hand-written code. Unsupported functions raise
an error naming the function, which is itself a useful signal.

CLI:
  python lisp_sim.py file.lsp C:COMMAND [--json out.json]
"""
import math, re, sys, json

# ----------------------------------------------------------------- data types
class Sym:
    __slots__ = ('name',)
    _tab = {}
    def __new__(cls, name):
        name = name.upper()
        s = cls._tab.get(name)
        if s is None:
            s = object.__new__(cls); s.name = name; cls._tab[name] = s
        return s
    def __repr__(self): return self.name

class Pair:
    """Dotted pair (car . cdr) with atomic cdr."""
    __slots__ = ('car', 'cdr')
    def __init__(self, a, d): self.car, self.cdr = a, d
    def __repr__(self): return f"({lrepr(self.car)} . {lrepr(self.cdr)})"
    def __eq__(self, o): return isinstance(o, Pair) and lequal(self.car, o.car) and lequal(self.cdr, o.cdr)

class EName:
    _n = 0
    def __init__(self):
        EName._n += 1; self.id = EName._n
    def __repr__(self): return f"<Entity name: {self.id:x}>"

class VlaObj:
    def __init__(self, kind, **kw): self.kind = kind; self.__dict__.update(kw)
    def __repr__(self): return f"#<VLA-OBJECT {self.kind}>"

class CatchErr:
    def __init__(self, msg): self.msg = msg

class LispError(Exception): pass

NIL = None
T = Sym('T')

def lrepr(x):
    if x is None: return 'nil'
    if isinstance(x, str): return '"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(x, float): return repr(x)
    if isinstance(x, list): return '(' + ' '.join(lrepr(i) for i in x) + ')'
    return repr(x)

def lequal(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 1e-12
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(lequal(x, y) for x, y in zip(a, b))
    return a == b

def truthy(x): return x is not None

# ------------------------------------------------------------------ reader
_ESC = {'\\': '\\', '"': '"', 'n': '\n', 'r': '\r', 't': '\t', 'e': '\x1b'}

def tokenize(src):
    toks, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == '\n': line += 1; i += 1; continue
        if c in ' \t\r\f': i += 1; continue
        if c == ';':
            if src.startswith(';|', i):
                j = src.find('|;', i + 2)
                if j < 0: raise LispError(f"line {line}: unterminated block comment")
                line += src.count('\n', i, j); i = j + 2; continue
            while i < n and src[i] != '\n': i += 1
            continue
        if c in "()'":
            toks.append((c, line)); i += 1; continue
        if c == '"':
            j, buf = i + 1, []
            while True:
                if j >= n: raise LispError(f"line {line}: unterminated string")
                ch = src[j]
                if ch == '\\':
                    nx = src[j + 1] if j + 1 < n else ''
                    if nx in _ESC: buf.append(_ESC[nx]); j += 2; continue
                    if nx.isdigit():
                        m = re.match(r'[0-7]{1,3}', src[j + 1:])
                        buf.append(chr(int(m.group(0), 8))); j += 1 + len(m.group(0)); continue
                    buf.append(nx); j += 2; continue    # AutoLISP keeps unknown escape char
                if ch == '"': break
                if ch == '\n': line += 1
                buf.append(ch); j += 1
            toks.append(('STR', ''.join(buf), line)); i = j + 1; continue
        j = i
        while j < n and src[j] not in ' \t\r\n\f()\';"': j += 1
        toks.append(('ATOM', src[i:j], line)); i = j
    return toks

_num_int = re.compile(r'^[+-]?\d+$')
_num_real = re.compile(r'^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$')

def parse_atom(s):
    if _num_int.match(s):
        v = int(s)
        return v
    if _num_real.match(s): return float(s)
    if s.upper() == 'NIL': return None
    return Sym(s)

def read_all(src):
    toks = tokenize(src); pos = 0; out = []
    def rd():
        nonlocal pos
        if pos >= len(toks): raise LispError("unexpected end of input (missing ')')")
        t = toks[pos]; pos += 1
        if t[0] == '(':
            items = []
            while True:
                if pos >= len(toks): raise LispError(f"line {t[1]}: '(' never closed")
                if toks[pos][0] == ')': pos += 1; break
                if toks[pos][0] == 'ATOM' and toks[pos][1] == '.':
                    pos += 1; cdr = rd()
                    if pos >= len(toks) or toks[pos][0] != ')':
                        raise LispError(f"line {t[1]}: bad dotted pair")
                    pos += 1
                    if len(items) != 1: raise LispError(f"line {t[1]}: dotted list unsupported")
                    if isinstance(cdr, list): return items + cdr
                    return Pair(items[0], cdr)
                items.append(rd())
            return items if items else None
        if t[0] == ')': raise LispError(f"line {t[1]}: unexpected ')'")
        if t[0] == "'": return [Sym('QUOTE'), rd()]
        if t[0] == 'STR': return t[1]
        return parse_atom(t[1])
    while pos < len(toks):
        line = toks[pos][-1]
        out.append((rd(), line))
    return out

# ------------------------------------------------------------- AutoCAD stub
LINETYPE_LIB = {'DOT', 'DOT2', 'DOTX2', 'DASHED', 'DASHED2', 'DASHEDX2', 'HIDDEN', 'HIDDEN2',
                'HIDDENX2', 'CENTER', 'CENTER2', 'CENTERX2', 'PHANTOM', 'PHANTOM2', 'DASHDOT',
                'DASHDOT2', 'BORDER', 'DIVIDE', 'ACAD_ISO02W100', 'ACAD_ISO03W100'}

HATCH_LIB = {'SOLID', 'ANGLE', 'ANSI31', 'ANSI32', 'ANSI33', 'ANSI34', 'ANSI35', 'ANSI36', 'ANSI37',
             'ANSI38', 'AR-B816', 'AR-B816C', 'AR-B88', 'AR-BRELM', 'AR-BRSTD', 'AR-CONC', 'AR-HBONE',
             'AR-PARQ1', 'AR-RROOF', 'AR-RSHKE', 'AR-SAND', 'BOX', 'BRASS', 'BRICK', 'BRSTONE', 'CLAY',
             'CORK', 'CROSS', 'DASH', 'DOLMIT', 'DOTS', 'EARTH', 'ESCHER', 'FLEX', 'GRASS', 'GRATE',
             'GRAVEL', 'HEX', 'HONEY', 'HOUND', 'INSUL', 'LINE', 'MUDST', 'NET', 'NET3', 'PLAST',
             'PLASTI', 'SACNCR', 'SQUARE', 'STARS', 'STEEL', 'SWAMP', 'TRANS', 'TRIANG', 'ZIGZAG'}

DIMVARS = {
    'DIMSCALE': 1.0, 'DIMTXT': 0.18, 'DIMASZ': 0.18, 'DIMEXO': 0.0625, 'DIMEXE': 0.18,
    'DIMGAP': 0.09, 'DIMDLE': 0.0, 'DIMTAD': 0, 'DIMJUST': 0, 'DIMTIH': 1, 'DIMTOH': 1,
    'DIMTIX': 0, 'DIMATFIT': 3, 'DIMTOFL': 0, 'DIMLUNIT': 2, 'DIMDEC': 4, 'DIMFRAC': 0,
    'DIMZIN': 0, 'DIMLFAC': 1.0, 'DIMRND': 0.0, 'DIMTXSTY': 'Standard', 'DIMBLK': '',
    'DIMLDRBLK': '', 'DIMCLRD': 0, 'DIMCLRE': 0, 'DIMCLRT': 0, 'DIMSE1': 0, 'DIMSE2': 0,
    'DIMTMOVE': 0, 'DIMCEN': 0.09, 'DIMTVP': 0.0, 'DIMLWD': -2, 'DIMLWE': -2, 'DIMSOXD': 0,
    'DIMSAH': 0, 'DIMTFAC': 1.0, 'DIMAUNIT': 0, 'DIMADEC': 0, 'DIMDSEP': '.', 'DIMTDEC': 4,
    'DIMUPT': 0, 'DIMTOFL': 0,
}
SYSVARS = dict(DIMVARS)
SYSVARS.update({'CMDECHO': 1, 'OSMODE': 0, 'CLAYER': '0', 'MEASUREMENT': 0, 'LTSCALE': 1.0,
                'PSLTSCALE': 1, 'INSUNITS': 1, 'TEXTSIZE': 0.2, 'TEXTSTYLE': 'Standard',
                'CELTSCALE': 1.0, 'DIMSTYLE': 'Standard', 'ANGBASE': 0.0, 'ANGDIR': 0,
                'LUNITS': 2, 'LUPREC': 4, 'PLINEGEN': 0, 'ACADVER': '24.3s (LMS Tech)',
                'DIMASSOC': 2, 'EXPERT': 0, 'FILEDIA': 1, 'QAFLAGS': 0})

# group-code value classes
def code_kind(c):
    if 0 <= c <= 9 or c in (100, 102, 105) or 300 <= c <= 369 or 390 <= c <= 399 \
       or 410 <= c <= 419 or 430 <= c <= 439 or 470 <= c <= 481 or c == 999 or 1000 <= c <= 1009:
        return 'str'
    if 10 <= c <= 18 or 110 <= c <= 112 or c == 210 or 1010 <= c <= 1013:
        return 'pt'
    if 38 <= c <= 59 or 140 <= c <= 149 or 460 <= c <= 469 or 1040 <= c <= 1042:
        return 'real'
    if 60 <= c <= 79 or 90 <= c <= 99 or 170 <= c <= 179 or 270 <= c <= 289 or 290 <= c <= 299 \
       or 370 <= c <= 389 or 400 <= c <= 409 or 420 <= c <= 429 or 440 <= c <= 459 or 1060 <= c <= 1071:
        return 'int'
    if 20 <= c <= 37 or 211 <= c <= 239:
        return 'real'
    return 'any'

class Acad:
    def __init__(self):
        self.sysvars = dict(SYSVARS)
        self.tables = {'LAYER': {'0': {}}, 'STYLE': {'STANDARD': {'3': 'txt'}},
                       'LTYPE': {'CONTINUOUS': {}, 'BYLAYER': {}, 'BYBLOCK': {}},
                       'DIMSTYLE': {'STANDARD': dict(DIMVARS)}}
        self.active_dimstyle = 'Standard'
        self.ents = []        # list of dicts {ename, type, data(list of group items)}
        self.by_ename = {}
        self.errors, self.warnings, self.log, self.commands = [], [], [], []

    # -- validation of an entmake list
    def validate(self, lst):
        probs = []
        if not isinstance(lst, list) or not lst:
            return ['entmake argument is not a non-empty list'], None
        items = []
        for it in lst:
            if isinstance(it, Pair):
                code, val = it.car, it.cdr
            elif isinstance(it, list) and it and isinstance(it[0], int):
                code, val = it[0], it[1:]
            else:
                probs.append(f'bad group item {lrepr(it)}'); continue
            if not isinstance(code, int):
                probs.append(f'non-integer group code {lrepr(code)}'); continue
            k = code_kind(code)
            if k == 'pt':
                if not (isinstance(val, list) and 2 <= len(val) <= 3 and all(isinstance(v, (int, float)) for v in val)):
                    probs.append(f'group {code} expects point list, got {lrepr(val)}')
                elif any(isinstance(v, int) for v in val):
                    self.warnings.append(f'group {code} point has integer coordinate {lrepr(val)}')
            elif k == 'real':
                if isinstance(val, int) and not isinstance(val, bool):
                    self.warnings.append(f'group {code} given integer {val} (emit reals)')
                elif not isinstance(val, float):
                    probs.append(f'group {code} expects real, got {lrepr(val)}')
            elif k == 'int':
                if not isinstance(val, int):
                    probs.append(f'group {code} expects integer, got {lrepr(val)}')
            elif k == 'str':
                if not isinstance(val, str):
                    probs.append(f'group {code} expects string, got {lrepr(val)}')
            items.append((code, val))
        if not items or items[0][0] != 0:
            probs.append('first group must be (0 . type)')
            return probs, items
        return probs, items

    def entmake(self, lst):
        probs, items = self.validate(lst)
        if items is None:
            self.errors.append('entmake: ' + probs[0]); return None
        etype = items[0][1].upper() if items and items[0][0] == 0 else '?'
        codes = {}
        for c, v in items: codes.setdefault(c, []).append(v)
        g = lambda c: codes.get(c, [None])[0]
        req = {'LINE': [10, 11], 'CIRCLE': [10, 40], 'ARC': [10, 40, 50, 51], 'TEXT': [10, 40, 1],
               'LWPOLYLINE': [90, 10], 'LEADER': [10, 76], 'SOLID': [10, 11, 12],
               'LAYER': [2], 'STYLE': [2, 3], 'MTEXT': [10, 1], 'POINT': [10], 'HATCH': [10]}
        for c in req.get(etype, []):
            if c not in codes: probs.append(f'{etype}: missing group {c}')
        if etype == 'LWPOLYLINE':
            n10 = len(codes.get(10, []))
            if g(90) is not None and g(90) != n10: probs.append(f'LWPOLYLINE: 90={g(90)} but {n10} vertices')
            if 42 in codes and len(codes[42]) != n10: probs.append('LWPOLYLINE: bulge count != vertex count')
            if n10 < 2: probs.append('LWPOLYLINE: fewer than 2 vertices')
            # AcDbPolyline marker must precede vertex data
            idx = [i for i, (c, v) in enumerate(items) if c == 100 and v == 'AcDbPolyline']
            first10 = next((i for i, (c, v) in enumerate(items) if c == 10), None)
            if not idx or (first10 is not None and idx[0] > first10):
                probs.append('LWPOLYLINE: (100 . "AcDbPolyline") must precede vertices')
        if etype == 'LEADER':
            n10 = len(codes.get(10, []))
            if g(76) != n10: probs.append(f'LEADER: 76={g(76)} but {n10} vertices')
            if n10 < 2: probs.append('LEADER: needs >= 2 vertices')
            ds = g(3)
            if ds and ds.upper() not in self.tables['DIMSTYLE']: probs.append(f'LEADER: dimstyle {ds} missing')
        if etype == 'TEXT':
            if (g(72) or 0) != 0 or (g(73) or 0) != 0:
                if 11 not in codes: probs.append('TEXT: justified text needs group 11')
            if isinstance(g(40), (int, float)) and g(40) <= 0: probs.append('TEXT: height <= 0')
        if etype in ('CIRCLE', 'ARC') and isinstance(g(40), (int, float)) and g(40) <= 0:
            probs.append(f'{etype}: radius <= 0')
        st = g(7)
        if st and st.upper() not in self.tables['STYLE']:
            probs.append(f'{etype}: text style {st} not defined (entmake would fail)')
        lt = g(6)
        if lt and etype != 'LTYPE' and lt.upper() not in self.tables['LTYPE']:
            probs.append(f'{etype}: linetype {lt} not loaded (entmake would fail)')
        lay = g(8)
        if lay and etype not in ('LAYER', 'STYLE', 'LTYPE') and lay.upper() not in self.tables['LAYER']:
            self.warnings.append(f'{etype} on layer {lay} not created beforehand (AutoCAD auto-creates it)')
            self.tables['LAYER'][lay.upper()] = {}
        if probs:
            for p in probs: self.errors.append('entmake ' + etype + ': ' + p)
            return None
        if etype in ('LAYER', 'STYLE', 'LTYPE', 'DIMSTYLE'):
            name = g(2)
            if name.upper() in self.tables[etype]:
                self.errors.append(f'entmake {etype}: {name} already exists (entmake returns nil)')
                return None
            self.tables[etype][name.upper()] = {str(c): v for c, v in items}
            return items[0][1] and lst  # entmake returns the list
        e = EName()
        rec = {'ename': e, 'type': etype, 'items': items}
        self.ents.append(rec); self.by_ename[e] = rec
        return lst

    def entget(self, e):
        rec = self.by_ename.get(e)
        if rec is None: return None
        out = [Pair(-1, e)]
        for c, v in rec['items']:
            out.append([c] + v if isinstance(v, list) else Pair(c, v))
        return out

    def entmod(self, lst):
        e = None; items = []
        for it in lst:
            if isinstance(it, Pair) and it.car == -1: e = it.cdr; continue
            if isinstance(it, Pair): items.append((it.car, it.cdr))
            elif isinstance(it, list): items.append((it[0], it[1:]))
        rec = self.by_ename.get(e)
        if rec is None: self.errors.append('entmod: unknown entity'); return None
        rec['items'] = items
        return lst

# -------------------------------------------------------------- interpreter
class Func:
    def __init__(self, name, params, locs, body):
        self.name, self.params, self.locs, self.body = name, params, locs, body
    def __repr__(self): return f"#<SUBR @ {self.name}>"

class Interp:
    def __init__(self, acad=None):
        self.acad = acad or Acad()
        self.glob = {}
        self.frames = []
        self.depth = 0
        self.out = []
        self._install()

    # -- environment
    def lookup(self, s):
        for f in reversed(self.frames):
            if s in f: return f[s]
        return self.glob.get(s)
    def assign(self, s, v):
        for f in reversed(self.frames):
            if s in f: f[s] = v; return v
        self.glob[s] = v; return v

    # -- eval
    def ev(self, x):
        if isinstance(x, Sym):
            if x is T: return T
            return self.lookup(x)
        if not isinstance(x, list):
            return x
        head = x[0]
        if isinstance(head, Sym):
            sf = self.special.get(head.name)
            if sf: return sf(x)
        fn = self.ev(head) if isinstance(head, (Sym, list)) else head
        if fn is None:
            raise LispError(f"no function definition: {head}")
        args = [self.ev(a) for a in x[1:]]
        return self.call(fn, args, head)

    def to_func(self, fn, where=None):
        if isinstance(fn, Sym):
            v = self.lookup(fn)
            if v is None: raise LispError(f"no function definition: {fn}")
            return self.to_func(v, fn)
        if isinstance(fn, list) and fn and fn[0] is Sym('LAMBDA'):
            return self.make_lambda(fn)
        if callable(fn) or isinstance(fn, Func): return fn
        raise LispError(f"bad function: {lrepr(fn)} ({where})")

    def call(self, fn, args, where=None):
        fn = self.to_func(fn, where)
        if isinstance(fn, Func):
            if len(args) != len(fn.params):
                raise LispError(f"{fn.name}: too {'few' if len(args) < len(fn.params) else 'many'} arguments "
                                f"(got {len(args)}, expected {len(fn.params)})")
            frame = {p: a for p, a in zip(fn.params, args)}
            for l in fn.locs: frame[l] = None
            self.frames.append(frame); self.depth += 1
            if self.depth > 400: raise LispError("stack overflow")
            try:
                r = None
                for b in fn.body: r = self.ev(b)
                return r
            finally:
                self.frames.pop(); self.depth -= 1
        return fn(*args)

    def parse_params(self, plist, name):
        params, locs, seen_slash = [], [], False
        for p in (plist or []):
            if p is Sym('/'): seen_slash = True; continue
            if not isinstance(p, Sym): raise LispError(f"{name}: bad parameter {lrepr(p)}")
            if p.name in ('T', 'NIL', 'PI'):
                raise LispError(f"{name}: '{p.name}' used as parameter/local (protected symbol)")
            (locs if seen_slash else params).append(p)
        return params, locs

    def make_lambda(self, x):
        params, locs = self.parse_params(x[1], 'lambda')
        return Func('lambda', params, locs, x[2:])

    # -- special forms
    def _install(self):
        S = {}
        def sf(name):
            def d(f): S[name] = f; return f
            return d
        @sf('QUOTE')
        def _(x): return x[1]
        @sf('FUNCTION')
        def _(x): return x[1]
        @sf('SETQ')
        def _(x):
            if len(x) % 2 != 1: raise LispError("setq: odd number of arguments")
            v = None
            for i in range(1, len(x), 2):
                s = x[i]
                if not isinstance(s, Sym): raise LispError(f"setq: bad symbol {lrepr(s)}")
                if s.name in ('T', 'PI', 'NIL'): raise LispError(f"setq: attempt to set protected symbol {s.name}")
                v = self.assign(s, self.ev(x[i + 1]))
            return v
        @sf('DEFUN')
        def _(x):
            name = x[1]; params, locs = self.parse_params(x[2], name.name)
            f = Func(name.name, params, locs, x[3:])
            if name.name.startswith('C:') and params:
                raise LispError(f"{name.name}: command functions cannot take arguments")
            self.assign(name, f); return name
        @sf('LAMBDA')
        def _(x): return self.make_lambda(x)
        @sf('IF')
        def _(x):
            if len(x) not in (3, 4): raise LispError("if: too many/few arguments")
            if truthy(self.ev(x[1])): return self.ev(x[2])
            return self.ev(x[3]) if len(x) == 4 else None
        @sf('COND')
        def _(x):
            for cl in x[1:]:
                if not isinstance(cl, list): raise LispError("cond: bad clause")
                v = self.ev(cl[0])
                if truthy(v):
                    for b in cl[1:]: v = self.ev(b)
                    return v
            return None
        @sf('PROGN')
        def _(x):
            r = None
            for b in x[1:]: r = self.ev(b)
            return r
        @sf('AND')
        def _(x):
            for b in x[1:]:
                if not truthy(self.ev(b)): return None
            return T
        @sf('OR')
        def _(x):
            for b in x[1:]:
                if truthy(self.ev(b)): return T
            return None
        @sf('WHILE')
        def _(x):
            r = None; n = 0
            while truthy(self.ev(x[1])):
                for b in x[2:]: r = self.ev(b)
                n += 1
                if n > 2_000_000: raise LispError("while: runaway loop")
            return r
        @sf('REPEAT')
        def _(x):
            n = self.ev(x[1]); r = None
            if not isinstance(n, int): raise LispError(f"repeat: bad count {lrepr(n)}")
            for _i in range(n):
                for b in x[2:]: r = self.ev(b)
            return r
        @sf('FOREACH')
        def _(x):
            s = x[1]; lst = self.ev(x[2]) or []
            if not isinstance(lst, list): raise LispError(f"foreach: not a list: {lrepr(lst)}")
            frame = {s: None}; self.frames.append(frame); r = None
            try:
                for it in lst:
                    frame[s] = it
                    for b in x[3:]: r = self.ev(b)
            finally:
                self.frames.pop()
            return r
        @sf('VL-LOAD-COM')
        def _(x): return None
        self.special = S
        B = self.glob
        def b(name):
            def d(f): B[Sym(name)] = f; return f
            return d
        num = (int, float)
        def chk(v, kinds, fname):
            if not isinstance(v, kinds) or isinstance(v, bool): raise LispError(f"{fname}: bad argument type: {lrepr(v)}")
            return v
        def arith(op, args, fname):
            for a in args: chk(a, num, fname)
            return op(args)
        def _add(a):
            r = 0
            for v in a: r = r + v
            return r
        B[Sym('+')] = lambda *a: arith(_add, a, '+')
        def _sub(a):
            if not a: return 0
            if len(a) == 1: return -a[0]
            r = a[0]
            for v in a[1:]: r = r - v
            return r
        B[Sym('-')] = lambda *a: arith(_sub, a, '-')
        def _mul(a):
            r = 1
            for v in a: r = r * v
            return r
        B[Sym('*')] = lambda *a: arith(_mul, a, '*')
        def _div(a):
            if not a: return 0
            r = a[0]
            for v in a[1:]:
                if v == 0: raise LispError("divide by zero")
                if isinstance(r, int) and isinstance(v, int):
                    q = abs(r) // abs(v); r = q if (r >= 0) == (v >= 0) else -q
                else: r = r / v
            return r
        B[Sym('/')] = lambda *a: arith(_div, a, '/')
        B[Sym('1+')] = lambda a: chk(a, num, '1+') + 1
        B[Sym('1-')] = lambda a: chk(a, num, '1-') - 1
        B[Sym('ABS')] = lambda a: abs(chk(a, num, 'abs'))
        B[Sym('MIN')] = lambda *a: min(chk(v, num, 'min') for v in a) if all(isinstance(v, int) for v in a) else float(min(chk(v, num, 'min') for v in a))
        B[Sym('MAX')] = lambda *a: max(chk(v, num, 'max') for v in a) if all(isinstance(v, int) for v in a) else float(max(chk(v, num, 'max') for v in a))
        B[Sym('REM')] = lambda a, c: math.fmod(a, c) if isinstance(a, float) or isinstance(c, float) else int(math.fmod(a, c))
        B[Sym('FLOAT')] = lambda a: float(chk(a, num, 'float'))
        B[Sym('FIX')] = lambda a: int(chk(a, num, 'fix'))
        B[Sym('SQRT')] = lambda a: math.sqrt(chk(a, num, 'sqrt'))
        B[Sym('SIN')] = lambda a: math.sin(chk(a, num, 'sin'))
        B[Sym('COS')] = lambda a: math.cos(chk(a, num, 'cos'))
        B[Sym('ATAN')] = lambda a, c=None: math.atan(a) if c is None else math.atan2(a, c)
        B[Sym('EXPT')] = lambda a, c: a ** c
        B[Sym('EXP')] = lambda a: math.exp(a)
        B[Sym('LOG')] = lambda a: math.log(a)
        B[Sym('PI')] = math.pi
        def cmp(op):
            def f(*a):
                for x_, y_ in zip(a, a[1:]):
                    if isinstance(x_, str) != isinstance(y_, str) and op is not None:
                        raise LispError(f"comparison: bad argument type {lrepr(x_)} {lrepr(y_)}")
                    if not op(x_, y_): return None
                return T
            return f
        B[Sym('=')] = cmp(lambda p, q: lequal(p, q) if not isinstance(p, str) else p == q)
        B[Sym('/=')] = lambda p, q: T if not ((p == q) if isinstance(p, str) else lequal(p, q)) else None
        B[Sym('<')] = cmp(lambda p, q: p < q)
        B[Sym('>')] = cmp(lambda p, q: p > q)
        B[Sym('<=')] = cmp(lambda p, q: p <= q)
        B[Sym('>=')] = cmp(lambda p, q: p >= q)
        B[Sym('EQ')] = lambda p, q: T if (p is q or (isinstance(p, (int, float, str)) and p == q)) else None
        B[Sym('EQUAL')] = lambda p, q, fuzz=0.0: T if (lequal(p, q) if not fuzz else abs(p - q) <= fuzz) else None
        B[Sym('NOT')] = lambda a: T if a is None else None
        B[Sym('NULL')] = lambda a: T if a is None else None
        B[Sym('NUMBERP')] = lambda a: T if isinstance(a, num) else None
        B[Sym('LISTP')] = lambda a: T if (a is None or isinstance(a, (list, Pair))) else None
        B[Sym('ATOM')] = lambda a: None if isinstance(a, (list, Pair)) else T
        B[Sym('BOUNDP')] = lambda s: T if self.lookup(s) is not None else None
        def _type(a):
            if a is None: return None
            return Sym({int: 'INT', float: 'REAL', str: 'STR', list: 'LIST', Sym: 'SYM',
                        EName: 'ENAME', VlaObj: 'VLA-OBJECT', Func: 'USUBR'}.get(type(a), 'SUBR'))
        B[Sym('TYPE')] = _type
        # lists
        def car(a):
            if a is None: return None
            if isinstance(a, Pair): return a.car
            if isinstance(a, list): return a[0]
            raise LispError(f"bad argument type: consp {lrepr(a)}")
        def cdr(a):
            if a is None: return None
            if isinstance(a, Pair): return a.cdr
            if isinstance(a, list): return a[1:] or None
            raise LispError(f"bad argument type: consp {lrepr(a)}")
        B[Sym('CAR')] = car; B[Sym('CDR')] = cdr
        for nm in ['CAAR', 'CADR', 'CDAR', 'CDDR', 'CAADR', 'CADDR', 'CDDDR', 'CADAR', 'CDADR', 'CADDDR']:
            ops = nm[1:-1][::-1]
            def mk(ops):
                def f(a):
                    for o in ops: a = car(a) if o == 'A' else cdr(a)
                    return a
                return f
            B[Sym(nm)] = mk(ops)
        B[Sym('LIST')] = lambda *a: list(a) if a else None
        def cons(a, d):
            if d is None: return [a]
            if isinstance(d, list): return [a] + d
            return Pair(a, d)
        B[Sym('CONS')] = cons
        def append(*a):
            r = []
            for l in a:
                if l is None: continue
                if not isinstance(l, list): raise LispError(f"append: bad list {lrepr(l)}")
                r += l
            return r or None
        B[Sym('APPEND')] = append
        B[Sym('REVERSE')] = lambda a: (a[::-1] if a else None)
        def length(a):
            if a is None: return 0
            if not isinstance(a, list): raise LispError(f"length: bad list {lrepr(a)}")
            return len(a)
        B[Sym('LENGTH')] = length
        def nth(i, a):
            if not isinstance(i, int): raise LispError(f"nth: bad index {lrepr(i)}")
            if a is None: return None
            if not isinstance(a, list): raise LispError(f"nth: bad list {lrepr(a)}")
            return a[i] if 0 <= i < len(a) else None
        B[Sym('NTH')] = nth
        B[Sym('LAST')] = lambda a: a[-1] if a else None
        def member(x_, a):
            if a is None: return None
            for i, v in enumerate(a):
                if lequal(v, x_): return a[i:]
            return None
        B[Sym('MEMBER')] = member
        def assoc(k, a):
            for it in (a or []):
                kk = it.car if isinstance(it, Pair) else (it[0] if isinstance(it, list) else None)
                if lequal(kk, k): return it
            return None
        B[Sym('ASSOC')] = assoc
        def subst(new, old, a):
            if a is None: return None
            return [new if lequal(v, old) else v for v in a]
        B[Sym('SUBST')] = subst
        def mapcar(f, *ls):
            f = self.to_func(f, 'mapcar')
            ls = [l or [] for l in ls]
            n = min(len(l) for l in ls) if ls else 0
            r = [self.call(f, [l[i] for l in ls]) for i in range(n)]
            return r or None
        B[Sym('MAPCAR')] = mapcar
        B[Sym('APPLY')] = lambda f, a: self.call(f, list(a or []))
        B[Sym('EVAL')] = lambda a: self.ev(a)
        B[Sym('VL-REMOVE-IF')] = lambda f, a: [v for v in (a or []) if not truthy(self.call(f, [v]))] or None
        B[Sym('VL-REMOVE-IF-NOT')] = lambda f, a: [v for v in (a or []) if truthy(self.call(f, [v]))] or None
        B[Sym('VL-SORT')] = lambda a, f: a
        # strings
        def strcat(*a):
            for s in a:
                if not isinstance(s, str): raise LispError(f"strcat: bad argument type: stringp {lrepr(s)}")
            return ''.join(a)
        B[Sym('STRCAT')] = strcat
        B[Sym('STRLEN')] = lambda s='': len(s)
        B[Sym('STRCASE')] = lambda s, lower=None: s.lower() if lower else s.upper()
        B[Sym('SUBSTR')] = lambda s, st, ln=None: s[st - 1:(st - 1 + ln) if ln else None]
        def itoa(i):
            if not isinstance(i, int): raise LispError(f"itoa: bad argument type: fixnump {lrepr(i)}")
            return str(i)
        B[Sym('ITOA')] = itoa
        B[Sym('ATOI')] = lambda s: int(re.match(r'\s*[+-]?\d*', s).group(0) or 0) if re.match(r'\s*[+-]?\d', s) else 0
        B[Sym('ATOF')] = lambda s: float(re.match(r'\s*[+-]?[\d.]*', s).group(0) or 0)
        def rtos(n, mode=2, prec=4):
            chk(n, num, 'rtos')
            return f"{float(n):.{prec}f}"
        B[Sym('RTOS')] = rtos
        def angtos(a, mode=0, prec=4):
            return f"{math.degrees(a):.{prec}f}".rstrip('0').rstrip('.')
        B[Sym('ANGTOS')] = angtos
        B[Sym('CHR')] = lambda i: chr(i)
        B[Sym('ASCII')] = lambda s: ord(s[0]) if s else 0
        B[Sym('VL-PRINC-TO-STRING')] = lambda a: a if isinstance(a, str) else lrepr(a)
        def wcmatch(s, pat):
            for p in pat.split(','):
                rx = ''
                for ch in p:
                    rx += {'*': '.*', '?': '.', '#': r'\d', '@': '[A-Za-z]', '.': r'[^A-Za-z0-9]'}.get(ch, re.escape(ch))
                if re.fullmatch(rx, s): return T
            return None
        B[Sym('WCMATCH')] = wcmatch
        # output
        def princ(*a):
            if a: self.out.append(a[0] if isinstance(a[0], str) else lrepr(a[0]))
            return a[0] if a else None
        B[Sym('PRINC')] = princ; B[Sym('PRIN1')] = princ; B[Sym('PRINT')] = princ
        B[Sym('PROMPT')] = princ; B[Sym('TERPRI')] = lambda: None
        B[Sym('ALERT')] = lambda s: princ('[ALERT] ' + s)
        def _exit(*a): raise LispError("quit / exit abort")
        B[Sym('EXIT')] = _exit; B[Sym('QUIT')] = _exit
        # error trapping
        def catch_apply(f, args):
            try: return self.call(f, list(args or []))
            except LispError as e: return CatchErr(str(e))
        B[Sym('VL-CATCH-ALL-APPLY')] = catch_apply
        B[Sym('VL-CATCH-ALL-ERROR-P')] = lambda a: T if isinstance(a, CatchErr) else None
        B[Sym('VL-CATCH-ALL-ERROR-MESSAGE')] = lambda a: a.msg
        # user input: defaults
        B[Sym('GETPOINT')] = lambda *a: None
        B[Sym('GETREAL')] = lambda *a: None
        B[Sym('GETINT')] = lambda *a: None
        B[Sym('GETDIST')] = lambda *a: None
        B[Sym('GETSTRING')] = lambda *a: ''
        B[Sym('GETKWORD')] = lambda *a: None
        B[Sym('INITGET')] = lambda *a: None
        B[Sym('TRANS')] = lambda p, a, c, d=None: p
        # AutoCAD data
        A = self.acad
        def getvar(n):
            k = n.upper()
            if k not in A.sysvars: A.warnings.append(f'getvar: unknown variable {n} (sim)')
            return A.sysvars.get(k)
        def setvar(n, v):
            k = n.upper()
            if k not in A.sysvars: raise LispError(f'setvar rejected: {n}')
            cur = A.sysvars[k]
            if isinstance(cur, float) and isinstance(v, int): v = float(v)
            if isinstance(cur, int) and not isinstance(v, int): raise LispError(f'setvar rejected: {n} expects integer')
            if isinstance(cur, str) and not isinstance(v, str): raise LispError(f'setvar rejected: {n} expects string')
            if k == 'DIMTXSTY' and v.upper() not in A.tables['STYLE']: raise LispError(f'setvar rejected: style {v} missing')
            if k == 'CLAYER' and v.upper() not in A.tables['LAYER']: raise LispError(f'setvar rejected: layer {v} missing')
            A.sysvars[k] = v; return v
        B[Sym('GETVAR')] = getvar; B[Sym('SETVAR')] = setvar
        def tblsearch(t, n, nxt=None):
            tb = A.tables.get(t.upper())
            if tb is None: raise LispError(f'tblsearch: bad table {t}')
            r = tb.get(n.upper())
            return [Pair(0, t.upper()), Pair(2, n)] if r is not None else None
        B[Sym('TBLSEARCH')] = tblsearch
        B[Sym('ENTMAKE')] = lambda l=None: A.entmake(l)
        B[Sym('ENTLAST')] = lambda: A.ents[-1]['ename'] if A.ents else None
        B[Sym('ENTGET')] = lambda e, apps=None: A.entget(e)
        B[Sym('ENTMOD')] = lambda l: A.entmod(l)
        B[Sym('ENTUPD')] = lambda e: e
        def command(*a):
            A.commands.append([lrepr(x_) for x_ in a])
            if len(a) >= 5 and str(a[0]).upper().endswith('DIMEDIT') and str(a[1]).upper().endswith('O'):
                rec = A.by_ename.get(a[2])
                if rec is not None:
                    rec['items'] = [(c, v) for c, v in rec['items'] if c != 52] + [(52, math.radians(float(a[4])))]
            return None
        B[Sym('COMMAND')] = command
        # ActiveX
        doc = VlaObj('Document'); ms = VlaObj('ModelSpace'); app = VlaObj('Application')
        lts = VlaObj('Linetypes'); dss = VlaObj('DimStyles')
        B[Sym('VLAX-GET-ACAD-OBJECT')] = lambda: app
        B[Sym('VLA-GET-ACTIVEDOCUMENT')] = lambda o: doc
        B[Sym('VLA-GET-MODELSPACE')] = lambda o: ms
        B[Sym('VLA-GET-LINETYPES')] = lambda o: lts
        B[Sym('VLA-GET-DIMSTYLES')] = lambda o: dss
        B[Sym('VLA-STARTUNDOMARK')] = lambda o: None
        B[Sym('VLA-ENDUNDOMARK')] = lambda o: None
        def vla_load(o, name, f):
            if name.upper() in A.tables['LTYPE']: raise LispError(f'Linetype {name} already loaded')
            if name.upper() not in LINETYPE_LIB: raise LispError(f'Linetype {name} not found in {f}')
            A.tables['LTYPE'][name.upper()] = {'file': f}; return None
        B[Sym('VLA-LOAD')] = vla_load
        def ds_obj(name): return VlaObj('DimStyle', name=name)
        def vla_item(o, name):
            if o is dss:
                if name.upper() not in A.tables['DIMSTYLE']: raise LispError(f'Key not found: {name}')
                return ds_obj(name)
            raise LispError('vla-item: unsupported collection (sim)')
        B[Sym('VLA-ITEM')] = vla_item
        def vla_add(o, name):
            if o is dss:
                if name.upper() in A.tables['DIMSTYLE']: raise LispError(f'Duplicate record name: {name}')
                A.tables['DIMSTYLE'][name.upper()] = dict(DIMVARS); return ds_obj(name)
            raise LispError('vla-add: unsupported collection (sim)')
        B[Sym('VLA-ADD')] = vla_add
        def copyfrom(ds, src):
            A.tables['DIMSTYLE'][ds.name.upper()] = {k: A.sysvars[k] for k in DIMVARS}; return None
        B[Sym('VLA-COPYFROM')] = copyfrom
        B[Sym('VLA-GET-ACTIVEDIMSTYLE')] = lambda o: ds_obj(A.active_dimstyle)
        def put_active(o, ds):
            if not isinstance(ds, VlaObj) or ds.kind != 'DimStyle': raise LispError('ActiveDimStyle: bad object')
            A.active_dimstyle = ds.name
            for k, v in A.tables['DIMSTYLE'][ds.name.upper()].items(): A.sysvars[k] = v
            A.sysvars['DIMSTYLE'] = ds.name; return None
        B[Sym('VLA-PUT-ACTIVEDIMSTYLE')] = put_active
        def p3(v):
            if isinstance(v, tuple): return list(v)
            raise LispError('expected variant point from vlax-3d-point')
        def vlax3d(*a):
            if len(a) == 1:
                p = a[0]
                if not (isinstance(p, list) and len(p) in (2, 3)): raise LispError(f'vlax-3d-point: bad point {lrepr(p)}')
                p = list(p) + [0.0] * (3 - len(p))
            else: p = list(a) + [0.0] * (3 - len(a))
            return tuple(float(c) for c in p)
        B[Sym('VLAX-3D-POINT')] = vlax3d
        def mkdim(kind, p1, p2, dl, rot):
            e = EName()
            dv = {k: A.sysvars[k] for k in DIMVARS}
            items = [(0, 'DIMENSION'), (8, A.sysvars['CLAYER']), (3, A.active_dimstyle),
                     (13, p3(p1)), (14, p3(p2)), (10, p3(dl)), (50, float(rot)), (52, 0.0), (1, ''),
                     (70, 0 if kind == 'ROT' else 1)]
            rec = {'ename': e, 'type': 'DIMENSION', 'items': items, 'dimvars': dv}
            A.ents.append(rec); A.by_ename[e] = rec
            return VlaObj('Dimension', ename=e)
        def add_rot(o, p1, p2, dl, rot):
            if o is not ms: raise LispError('AddDimRotated: owner must be ModelSpace')
            chk(rot, num, 'AddDimRotated rotation'); return mkdim('ROT', p1, p2, dl, rot)
        def add_ali(o, p1, p2, dl):
            if o is not ms: raise LispError('AddDimAligned: owner must be ModelSpace')
            return mkdim('ALI', p1, p2, dl, 0.0)
        B[Sym('VLA-ADDDIMROTATED')] = add_rot
        B[Sym('VLA-ADDDIMALIGNED')] = add_ali
        def setprop(code, check=None):
            def f(o, v):
                if not isinstance(o, VlaObj) or o.kind not in ('Dimension', 'Hatch') or (o.kind == 'Hatch' and code != 8):
                    raise LispError('property put on unsupported object (sim)')
                if not isinstance(v, str): raise LispError(f'property expects string, got {lrepr(v)}')
                if check: check(v)
                rec = A.by_ename[o.ename]
                rec['items'] = [(c, x_) for c, x_ in rec['items'] if c != code] + [(code, v)]
                if code == 3: rec['dimvars'] = dict(A.tables['DIMSTYLE'][v.upper()])
                return None
            return f
        def chk_layer(v):
            if v.upper() not in A.tables['LAYER']: raise LispError(f'Key not found: layer {v}')
        def chk_ds(v):
            if v.upper() not in A.tables['DIMSTYLE']: raise LispError(f'Key not found: dimstyle {v}')
        B[Sym('VLA-PUT-LAYER')] = setprop(8, chk_layer)
        B[Sym('VLA-PUT-TEXTOVERRIDE')] = setprop(1)
        B[Sym('VLA-PUT-STYLENAME')] = setprop(3, chk_ds)
        B[Sym('VLAX-VLA-OBJECT->ENAME')] = lambda o: o.ename
        def ename2obj(e):
            rec = A.by_ename.get(e)
            if rec is None: raise LispError('vlax-ename->vla-object: bad entity name')
            kind = {'DIMENSION': 'Dimension', 'HATCH': 'Hatch'}.get(rec['type'], 'Entity')
            return VlaObj(kind, ename=e)
        B[Sym('VLAX-ENAME->VLA-OBJECT')] = ename2obj
        # --- hatch support (AddHatch + AppendOuterLoop/AppendInnerLoop + Evaluate)
        B[Sym('VLAX-VBOBJECT')] = 9
        B[Sym(':VLAX-FALSE')] = Sym(':VLAX-FALSE'); B[Sym(':VLAX-TRUE')] = Sym(':VLAX-TRUE')
        def mk_sa(t, *bounds):
            if t != 9: raise LispError('vlax-make-safearray: only vlax-vbObject supported (sim)')
            if len(bounds) != 1 or not isinstance(bounds[0], Pair): raise LispError('vlax-make-safearray: bad bounds')
            n = bounds[0].cdr - bounds[0].car + 1
            if n < 1: raise LispError('vlax-make-safearray: empty bounds')
            return VlaObj('SafeArray', n=n, items=None)
        def sa_fill(sa, lst):
            if not (isinstance(sa, VlaObj) and sa.kind == 'SafeArray'): raise LispError('vlax-safearray-fill: not a safearray')
            if not isinstance(lst, list) or len(lst) != sa.n: raise LispError('vlax-safearray-fill: wrong number of elements')
            for o in lst:
                if not isinstance(o, VlaObj): raise LispError('vlax-safearray-fill: element is not a VLA object')
            sa.items = lst; return sa
        def mk_var(v, *t):
            return VlaObj('Variant', value=v)
        B[Sym('VLAX-MAKE-SAFEARRAY')] = mk_sa; B[Sym('VLAX-SAFEARRAY-FILL')] = sa_fill
        B[Sym('VLAX-MAKE-VARIANT')] = mk_var
        def add_hatch(o, ptype, name, assoc, *rest):
            if o is not ms: raise LispError('AddHatch: owner must be ModelSpace')
            if ptype not in (0, 1, 2): raise LispError('AddHatch: bad pattern type')
            if not isinstance(name, str): raise LispError('AddHatch: pattern name must be a string')
            if ptype == 1 and name.upper() not in HATCH_LIB: raise LispError(f'AddHatch: pattern {name} not in acad.pat')
            if assoc not in (Sym(':VLAX-FALSE'), Sym(':VLAX-TRUE')): raise LispError('AddHatch: associativity must be :vlax-false/:vlax-true')
            e = EName()
            items = [(0, 'HATCH'), (8, A.sysvars['CLAYER']), (2, name.upper()), (41, 1.0), (52, 0.0), (91, 0)]
            rec = {'ename': e, 'type': 'HATCH', 'items': items, 'loops': [], 'evaluated': False}
            A.ents.append(rec); A.by_ename[e] = rec
            return VlaObj('Hatch', ename=e)
        B[Sym('VLA-ADDHATCH')] = add_hatch
        def hrec(h, fname):
            if not (isinstance(h, VlaObj) and h.kind == 'Hatch'): raise LispError(f'{fname}: not a hatch object')
            return A.by_ename[h.ename]
        def hput(code, fname):
            def f(h, v):
                rec = hrec(h, fname)
                if not isinstance(v, (int, float)) or isinstance(v, bool): raise LispError(f'{fname}: expects a number')
                if code == 41 and v <= 0: raise LispError(f'{fname}: scale must be > 0')
                rec['items'] = [(c, x_) for c, x_ in rec['items'] if c != code] + [(code, float(v))]
                return None
            return f
        B[Sym('VLA-PUT-PATTERNSCALE')] = hput(41, 'PatternScale')
        B[Sym('VLA-PUT-PATTERNANGLE')] = hput(52, 'PatternAngle')
        def loop_verts(var, fname):
            if not (isinstance(var, VlaObj) and var.kind == 'Variant'): raise LispError(f'{fname}: expects a variant')
            sa = var.value
            if not (isinstance(sa, VlaObj) and sa.kind == 'SafeArray' and sa.items): raise LispError(f'{fname}: expects a filled object safearray')
            out = []
            for o in sa.items:
                rec = A.by_ename.get(getattr(o, 'ename', None))
                if rec is None: raise LispError(f'{fname}: boundary object was deleted')
                if rec['type'] != 'LWPOLYLINE': raise LispError(f'{fname}: boundary must be LWPOLYLINE in this runtime')
                d = {}
                for c, v in rec['items']: d.setdefault(c, []).append(v)
                if not (d.get(70, [0])[0] & 1): raise LispError(f'{fname}: boundary polyline is not closed')
                bs = d.get(42, [0.0] * len(d[10]))
                out.append([(v[0], v[1], b) for v, b in zip(d[10], bs)])
            return out
        def app_outer(h, var):
            rec = hrec(h, 'AppendOuterLoop')
            if rec['loops']: raise LispError('AppendOuterLoop: outer loop already appended')
            rec['loops'] += loop_verts(var, 'AppendOuterLoop'); return None
        def app_inner(h, var):
            rec = hrec(h, 'AppendInnerLoop')
            if not rec['loops']: raise LispError('AppendInnerLoop: append the outer loop first')
            rec['loops'] += loop_verts(var, 'AppendInnerLoop'); return None
        B[Sym('VLA-APPENDOUTERLOOP')] = app_outer; B[Sym('VLA-APPENDINNERLOOP')] = app_inner
        def evaluate(h):
            rec = hrec(h, 'Evaluate')
            if not rec['loops']: raise LispError('Evaluate: hatch has no boundary')
            rec['evaluated'] = True
            rec['items'] = [(c, x_) for c, x_ in rec['items'] if c != 91] + [(91, len(rec['loops']))]
            return None
        B[Sym('VLA-EVALUATE')] = evaluate
        def vla_delete(o):
            rec = A.by_ename.pop(getattr(o, 'ename', None), None)
            if rec is None: raise LispError('vla-Delete: object already erased')
            A.ents.remove(rec); return None
        B[Sym('VLA-DELETE')] = vla_delete

    # -- load / run
    def load(self, src):
        for form, line in read_all(src):
            try:
                self.ev(form)
            except LispError as e:
                raise LispError(f"load error in top-level form at line {line}: {e}")

    def run_command(self, cmd):
        f = self.lookup(Sym(cmd))
        if f is None: raise LispError(f"command {cmd} not defined")
        try:
            r = self.call(f, [])
            for rec in self.acad.ents:
                if rec['type'] == 'HATCH' and not rec.get('evaluated'):
                    self.acad.errors.append('HATCH created but never evaluated (no boundary)')
            return r
        except LispError as e:
            handler = self.lookup(Sym('*ERROR*'))
            self.acad.errors.append(f'runtime error: {e}')
            if isinstance(handler, Func):
                try: self.call(handler, [str(e)])
                except LispError as e2: self.acad.errors.append(f'*error* handler failed: {e2}')
            return None


def simulate(path_or_src, command, is_src=False):
    src = path_or_src if is_src else open(path_or_src, encoding='utf-8', errors='replace').read()
    it = Interp()
    try:
        it.load(src)
    except LispError as e:
        it.acad.errors.append(str(e))
        return it
    it.run_command(command)
    return it


def to_plain(v):
    if isinstance(v, (list, tuple)): return [to_plain(x) for x in v]
    if isinstance(v, (int, float, str)) or v is None: return v
    return repr(v)


def entities_plain(it):
    out = []
    for r in it.acad.ents:
        d = {'type': r['type'], 'items': [[c, to_plain(v)] for c, v in r['items']]}
        if 'dimvars' in r: d['dimvars'] = r['dimvars']
        out.append(d)
    return out


def summary(it):
    from collections import Counter
    A = it.acad
    by = Counter((r['type'], dict(r['items']).get(8, '?')) for r in A.ents)
    lines = ['entities: %d' % len(A.ents)]
    for (t, l), n in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        lines.append(f'  {l:<24} {t:<12} {n}')
    lines.append('layers: ' + ', '.join(sorted(k for k in A.tables['LAYER'] if k != '0')))
    lines.append('linetypes: ' + ', '.join(sorted(A.tables['LTYPE'])))
    lines.append('dimstyles: ' + ', '.join(sorted(A.tables['DIMSTYLE'])))
    lines.append(f'errors: {len(A.errors)}  warnings: {len(A.warnings)}  command calls: {len(A.commands)}')
    for e in A.errors[:30]: lines.append('  ERROR ' + e)
    from collections import Counter as C2
    for w, n in C2(A.warnings).most_common(15): lines.append(f'  warn  {w}' + (f'  (x{n})' if n > 1 else ''))
    out = ''.join(x for x in it.out if isinstance(x, str)).strip()
    if out: lines.append('command-line output:\n' + out)
    return '\n'.join(lines)


if __name__ == '__main__':
    # A pipe on Windows uses the ANSI code page (cp1252); drawing text can contain
    # characters it cannot encode (private-use symbol glyphs, U+2248). Escape them
    # instead of crashing, so the tools behave the same on every platform.
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, 'reconfigure'):
            _s.reconfigure(errors='backslashreplace')
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lsp'); ap.add_argument('command', help='e.g. C:UB-CBGUTTERPAN')
    ap.add_argument('--json', help='write captured entities as JSON')
    a = ap.parse_args()
    it = simulate(a.lsp, a.command)
    print(summary(it))
    if a.json:
        json.dump({'entities': entities_plain(it), 'errors': it.acad.errors, 'warnings': it.acad.warnings},
                  open(a.json, 'w'), indent=1)
    sys.exit(1 if it.acad.errors else 0)
