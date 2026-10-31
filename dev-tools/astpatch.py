import ast, re

def read(p): return open(p, encoding="utf-8").read()
def write(p, s): open(p, "w", encoding="utf-8").write(s)

def _span(n):
    start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
    return start, n.end_lineno

def tops(src, name):
    return [n for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name]

def assigns(src, name):
    out = []
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets): out.append(n)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name: out.append(n)
    return out

def _replace_nodes(src, nodes, new_src):
    lines = src.split("\n")
    for i, n in reversed(list(enumerate(nodes))):
        s, e = _span(n)
        if i == 0 and new_src is not None: lines[s-1:e] = new_src.rstrip("\n").split("\n")
        else: del lines[s-1:e]
    return "\n".join(lines)

def replace_top(src, name, new_src):
    nodes = tops(src, name) or assigns(src, name)
    if not nodes: return src, False
    return _replace_nodes(src, nodes, new_src), True

def delete_top(src, name):
    nodes = tops(src, name) or assigns(src, name)
    if not nodes: return src, 0
    return _replace_nodes(src, nodes, None), len(nodes)

def func_text(src, name):
    nodes = tops(src, name)
    if not nodes: return None
    s, e = _span(nodes[0]); return "\n".join(src.split("\n")[s-1:e])

def patch_in_func(src, name, old, new, regex=False):
    nodes = tops(src, name)
    if not nodes: return src, False
    lines = src.split("\n"); s, e = _span(nodes[0])
    body = "\n".join(lines[s-1:e])
    if regex:
        nb, n = re.subn(old, new, body, count=1)
        if n == 0: return src, False
    else:
        if old not in body: return src, False
        nb = body.replace(old, new, 1)
    lines[s-1:e] = nb.split("\n")
    return "\n".join(lines), True

def _deco_name_kw(n, kinds):
    for d in n.decorator_list:
        if isinstance(d, ast.Call) and ast.unparse(d.func) in kinds:
            nm = n.name
            for kw in d.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant): nm = kw.value.value
            return ast.unparse(d.func), nm
    return None, None

def delete_command(src, kind, cmdname):
    tree = ast.parse(src); nodes = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            k, nm = _deco_name_kw(n, {kind})
            if k and nm == cmdname: nodes.append(n)
    if not nodes: return src, 0
    return _replace_nodes(src, nodes, None), len(nodes)

def append_block(src, block):
    return src.rstrip("\n") + "\n\n\n" + block.strip("\n") + "\n"
