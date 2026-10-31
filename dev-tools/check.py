import ast, sys, re, builtins, symtable, string, collections
PATH = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/outputs/bot.py"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 60
src = open(PATH, encoding="utf-8").read()
errs, warns = [], []
try:
    tree = ast.parse(src, PATH); compile(src, PATH, "exec")
except SyntaxError as e:
    print(f"SYNTAX ERROR line {e.lineno}: {e.msg}"); sys.exit(2)

defs = collections.defaultdict(list)
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): defs[n.name].append(n.lineno)
for k, v in defs.items():
    if len(v) > 1: errs.append(f"DUP-DEF {k} at lines {v}")

# undefined global names (scope-aware)
st = symtable.symtable(src, PATH, "exec")
mod_names = {s.get_name() for s in st.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
def _decl(t):
    for c in t.get_children():
        for s in c.get_symbols():
            if s.is_declared_global() and s.is_assigned(): mod_names.add(s.get_name())
        _decl(c)
_decl(st)
BI = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
und = collections.defaultdict(set)
def _walk(t, path):
    for c in t.get_children():
        p = path + [c.get_name()]
        for s in c.get_symbols():
            nm = s.get_name()
            if s.is_referenced() and s.is_global() and nm not in mod_names and nm not in BI: und[nm].add(".".join(p[-2:]))
        _walk(c, p)
_walk(st, [])
for nm, where in sorted(und.items()): errs.append(f"UNDEFINED {nm} (in {', '.join(sorted(where)[:3])})")

# import-time ordering
def bindings(node):
    names = set()
    def visit(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name); return
        if isinstance(n, ast.Import):
            for a in n.names: names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names: names.add(a.asname or a.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)): names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name: names.add(n.name)
        for ch in ast.iter_child_nodes(n): visit(ch)
    visit(node); return names
class Loads(ast.NodeVisitor):
    def __init__(self): self.names = set()
    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Load): self.names.add(n.id)
    def _func(self, n):
        for d in n.decorator_list: self.visit(d)
        a = n.args
        for d in a.defaults + [x for x in a.kw_defaults if x is not None]: self.visit(d)
        for arg in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
            if arg.annotation: self.visit(arg.annotation)
        if n.returns: self.visit(n.returns)
    visit_FunctionDef = _func; visit_AsyncFunctionDef = _func
    def visit_Lambda(self, n):
        for d in n.args.defaults: self.visit(d)
    def visit_ClassDef(self, n):
        for b in n.bases: self.visit(b)
        for k in n.keywords: self.visit(k.value)
        for d in n.decorator_list: self.visit(d)
        for s in n.body: self.visit(s)
    def _comp(self, n):
        sub = Loads(); stores = set()
        for g in n.generators:
            for t in ast.walk(g.target):
                if isinstance(t, ast.Name): stores.add(t.id)
            sub.visit(g.iter)
            for i in g.ifs: sub.visit(i)
        for f in ("elt", "key", "value"):
            if hasattr(n, f): sub.visit(getattr(n, f))
        self.names |= (sub.names - stores)
    visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _comp
defined = set(BI)
for n in tree.body:
    v = Loads(); v.visit(n)
    for m in sorted(v.names - defined): errs.append(f"ORDER line {n.lineno}: '{m}' used at import time before it is defined")
    defined |= bindings(n)

# registrations
def dcall(d): return (ast.unparse(d.func), d) if isinstance(d, ast.Call) else (ast.unparse(d), None)
KINDS = ("bot.command", "bot.tree.command", "setup_group.command", "rroles_group.command")
cmds = collections.defaultdict(list); prefix_names = set(); n_ev = 0
for n in ast.walk(tree):
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
    params = [a.arg for a in n.args.args + n.args.kwonlyargs]
    for d in n.decorator_list:
        f, call = dcall(d)
        if f == "bot.event": n_ev += 1
        if f in KINDS:
            name, aliases, desc = n.name, [], None
            if call:
                for kw in call.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant): name = kw.value.value
                    if kw.arg == "aliases" and isinstance(kw.value, (ast.List, ast.Tuple)): aliases = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant): desc = kw.value.value
            for nm in [name] + (aliases if f == "bot.command" else []):
                cmds[(f, nm)].append(n.name)
                if f == "bot.command": prefix_names.add(nm)
            if f != "bot.command":
                if not re.match(r"^[a-z0-9_-]{1,32}$", name): errs.append(f"SLASH-NAME '{name}' invalid")
                if desc is not None and len(desc) > 100: errs.append(f"SLASH-DESC {name}: {len(desc)} chars (>100)")
        if call is not None and f.endswith("app_commands.describe"):
            for kw in call.keywords:
                if kw.arg not in params: errs.append(f"DESCRIBE {n.name}: unknown parameter '{kw.arg}'")
                elif isinstance(kw.value, ast.Constant) and len(kw.value.value) > 100: errs.append(f"DESCRIBE {n.name}.{kw.arg} >100 chars")
        if call is not None and f.endswith("app_commands.choices"):
            for kw in call.keywords:
                if kw.arg not in params: errs.append(f"CHOICES {n.name}: unknown parameter '{kw.arg}'")
                if isinstance(kw.value, ast.List) and len(kw.value.elts) > 25: errs.append(f"CHOICES {n.name}.{kw.arg} >25")
for (f, nm), fns in cmds.items():
    if len(fns) > 1: errs.append(f"DUP-CMD {f} '{nm}' -> {fns}")
n_setup = sum(1 for (f, _n) in cmds if f == "setup_group.command")
if n_setup > 25: errs.append(f"SETUP group has {n_setup} subcommands (max 25)")
n_slash = sum(1 for (f, _n) in cmds if f == "bot.tree.command")

# translations
trans = None
for n in tree.body:
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TRANSLATIONS" for t in n.targets):
        try: trans = ast.literal_eval(n.value)
        except Exception as e: errs.append(f"TRANS cannot read TRANSLATIONS: {e}")
def fields(s):
    try: return [(f[2] or "") for f in string.Formatter().parse(s) if f[1] is not None]
    except Exception: return None
if trans:
    ks = {l: set(trans[l]) for l in trans}; allk = set().union(*ks.values())
    for l in trans:
        if allk - ks[l]: errs.append(f"TRANS {l} missing keys {sorted(allk - ks[l])}")
    for k in trans.get("en", {}):
        for l in trans:
            if k in trans[l] and isinstance(trans[l][k], str) and isinstance(trans["en"][k], str) and fields(trans[l][k]) != fields(trans["en"][k]):
                errs.append(f"TRANS placeholder mismatch key '{k}' ({l})")
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "t" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            if n.args[1].value not in trans["en"]: errs.append(f"TRANS key '{n.args[1].value}' used at line {n.lineno} but not defined")

# phrase table (L)
table = None
for n in tree.body:
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_PHRASE_TABLE" for t in n.targets) and isinstance(n.value, ast.Constant): table = n.value.value
used = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "L" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str): used.add(n.args[0].value)
keys = set()
if table is not None:
    for raw in table.split("\n"):
        p = raw.rstrip("\r").split(" ||| ")
        if len(p) != 3 or not p[0]: continue
        en = p[0].replace("\\n", "\n"); keys.add(en)
        for i, lang in ((1, "tr"), (2, "ru")):
            if fields(en) != fields(p[i].replace("\\n", "\n")): errs.append(f"PHRASE placeholder mismatch ({lang}): {en[:50]!r}")
    miss = sorted(used - keys)
    if miss: warns.append(f"PHRASE {len(miss)} of {len(used)} L() templates have no TR/RU translation, e.g. {[m[:40] for m in miss[:6]]}")
    else: warns.append(f"PHRASE all {len(used)} L() templates translated")

# help text mentions
for n in ast.walk(tree):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        for w in re.findall(r"`\{p\}([a-z\-]+)", n.value):
            if w not in prefix_names: errs.append(f"HELP mentions {{p}}{w} but no such command (line {n.lineno})")

# leftovers
for pat, label in ((r"buckshot", "buckshot"), (r"SPECIAL_USERS|is_special\(", "special-users"), (r"yuDtu2BCNt|sfJcHsMu3m|B8eDMvRy95|tBHyRAv5SV", "old invite")):
    hits = [i + 1 for i, l in enumerate(src.split("\n")) if re.search(pat, l, re.I)]
    if hits: warns.append(f"LEFTOVER {label}: lines {hits[:6]}")

print(f"{PATH.split('/')[-1]}: {len(src.splitlines())} lines | prefix cmds {len(prefix_names)} | slash {n_slash} | /setup subs {n_setup} | events {n_ev}")
for e in errs[:LIMIT]: print("ERR ", e)
for w in warns[:12]: print("WARN", w)
print(f"errors={len(errs)} warnings={len(warns)}")
sys.exit(1 if errs else 0)
