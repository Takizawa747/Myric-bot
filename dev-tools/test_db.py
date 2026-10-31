import ast
BOT = __import__("os").environ.get("BOT_SRC", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "bot.py"))
def block(first, last):
    """Source of the contiguous top-level block first..last, taken from the real bot.py (never from stale copies)."""
    src = open(BOT, encoding="utf-8").read(); tree = ast.parse(src)
    def nm(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return n.name
        if isinstance(n, ast.Assign):
            t = n.targets[0]
            return t.id if isinstance(t, ast.Name) else t.elts[0].id if isinstance(t, ast.Tuple) else None
    names = [nm(n) for n in tree.body]; i, j = names.index(first), names.index(last)
    return "\n".join(ast.get_source_segment(src, n) for n in tree.body[i:j + 1])
import os, json, sqlite3, threading, time as _time, tempfile, sys, threading as th
src = block("DB_PATH", "flush_now")
def fresh():
    ns = {"os": os, "json": json, "sqlite3": sqlite3, "threading": threading, "_time": _time}
    exec(compile(src, "blk_db.py", "exec"), ns); return ns
def flush(ns, full=False):
    ch = []
    for name in list(ns["_stores"]):
        if full: ns["touch_all"](name); ns["_touched"][name].update(ns["_last"][name])
        b = list(ns["_touched"][name]); ns["_touched"][name] = set(); ch += ns["_collect_store"](name, b)
    ns["_write"](ch); return ch
os.chdir(tempfile.mkdtemp())
json.dump({"111": {"prefix": "!", "language": "tr"}, "222": {"prefix": "."}}, open("settings.json", "w"))
json.dump({"111": {"5": {"wallet": 10, "bank": 2, "inventory": []}}}, open("economy.json", "w"))
json.dump({"banned": ["9"], "servers": []}, open("bot_bans.json", "w"))
json.dump({"1": {"7": [{"reason": "x"}]}}, open("warns.json", "w"))
ns = fresh()
S, E, B, W = (ns["load_json"](f) for f in ("settings.json", "economy.json", "bot_bans.json", "warns.json"))
assert S["111"]["language"] == "tr" and E["111"]["5"]["wallet"] == 10 and B["banned"] == ["9"] and W["1"]["7"][0]["reason"] == "x"
assert flush(ns) == [], "nothing changed yet -> nothing may be written"
live = ns["load_json"]("settings.json"); live["111"]["unsaved"] = 1; again = ns["load_json"]("settings.json")
assert again is live and again["111"]["unsaved"] == 1, "a second load_json() must return the same live dict and keep unsaved changes"
del live["111"]["unsaved"]
E["111"]["6"] = {"wallet": 1, "bank": 0, "inventory": ["x"]}; ns["touch"]("economy", "111", "6")
S["222"]["prefix"] = "?"; ns["touch"]("settings", "222")
B["banned"].append("10"); ns["save_json"]("bot_bans.json", B)
t = th.Thread(target=lambda: None); t.start(); t.join()
assert len(flush(ns)) == 3
ns2 = fresh()
S2, E2, B2 = (ns2["load_json"](f) for f in ("settings.json", "economy.json", "bot_bans.json"))
assert S2["222"]["prefix"] == "?" and E2["111"]["6"]["inventory"] == ["x"] and B2["banned"] == ["9", "10"], "reload mismatch"
del E2["111"]["5"]; ns2["touch"]("economy", "111", "5"); flush(ns2)
ns3 = fresh(); E3 = ns3["load_json"]("economy.json")
assert "5" not in E3["111"] and "6" in E3["111"], "deleted row came back (old JSON must not be re-imported)"
E3["111"]["6"]["wallet"] = 999                          # mutation WITHOUT touch -> the safety-net scan must catch it
assert len(flush(ns3, full=True)) == 1
ns4 = fresh(); assert ns4["load_json"]("economy.json")["111"]["6"]["wallet"] == 999
ns5 = fresh(); W5 = ns5["load_json"]("warns.json"); W5.clear(); ns5["touch_all"]("warns"); ns5["_touched"]["warns"].update(ns5["_last"]["warns"]); flush(ns5)
ns6 = fresh(); assert ns6["load_json"]("warns.json") == {}, "an emptied store must stay empty"
ns6["flush_now"]()                                       # sync shutdown path must not raise and must be idempotent
unknown = ns6["load_json"]("some_other.json"); unknown["a"] = 1; ns6["save_json"]("some_other.json", unknown)
assert json.load(open("some_other.json")) == {"a": 1}, "unmapped files keep the plain JSON behaviour"
corrupt = open("broken.json", "w"); corrupt.write("{oops"); corrupt.close()
assert ns6["load_json"]("broken.json") == {} and any(f.startswith("broken.json.corrupt") for f in os.listdir(".")), "corrupt file must be kept aside"
print("DB layer tests: ALL PASSED (migration, incremental write, delete, safety net, empty store, plain fallback, corrupt file)")
