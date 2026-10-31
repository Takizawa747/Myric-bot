import ast, os, json, sqlite3, threading, time as _time, tempfile
BOT = __import__("os").environ.get("BOT_SRC", "/mnt/user-data/outputs/bot.py")
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
db_src, core = block("DB_PATH", "flush_now"), block("_DD_NESTED", "dd_delete_user")
os.chdir(tempfile.mkdtemp())
U, V, G1, G2 = "100000000000000001", "100000000000000002", "900000000000000001", "900000000000000002"
files = {
    "economy": {G1: {U: {"wallet": 5, "bank": 9, "inventory": ["x"], "last_daily": 1, "last_rob": 2}, V: {"wallet": 7, "last_daily": 3}}, G2: {U: {"wallet": 9, "bank": 0, "inventory": []}}},
    "giveaways": {G1: {"1": {"participants": [U, V], "ended": False}}}, "polls": {G1: {"m1": {"votes": {U: 0, V: 1}, "closed": False}}},
    "warns": {G1: {U: [{"reason": "a"}]}}, "bot_bans": {"banned": [U], "servers": [G2]}, "whitelist": {U: {"perms": ["say_no_watermark"]}},
    "schedule": {"tasks": [{"type": "unban", "guild": G1, "target": U, "at": 1.0}]}, "levels": {G1: {U: {"xp": 5}}}, "msgstats": {G1: {U: {"t": 3, "d": {"1": 3}}}}, "flag_scores": {G1: {U: {"total": 2}}},
    "role_persist": {G1: {U: {"roles": ["1"]}}}, "settings": {G1: {"prefix": "!"}}, "modlogs": {G1: {U: [{"action": "ban"}]}}}
for k, v in files.items(): json.dump(v, open(f"{k}.json", "w"))
def boot():
    ns = {"os": os, "json": json, "sqlite3": sqlite3, "threading": threading, "_time": _time}
    exec(compile(db_src, "db", "exec"), ns)
    for k in files: ns[k + "_db"] = ns["load_json"](k + ".json")
    ns.update(afk_db={int(U): {"reason": "x"}}, active_bj={int(U): {}}, xp_cooldown={f"{G1}_{U}": 1.0}, _cmd_hits={int(U): 1}, _dm_rate={}, _modmail_cd={})
    exec(compile(core, "core", "exec"), ns); return ns
def flush(ns):
    ch = []
    for name in list(ns["_stores"]):
        ns["touch_all"](name); b = list(ns["_touched"][name]); ns["_touched"][name] = set(); ch += ns["_collect_store"](name, b)
    ns["_write"](ch)
ns = boot()
c = ns["dd_user_counts"](U)
assert c["economy"] == 2 and c["wallet"] == 2 and c["bank"] == 1 and c["inventory"] == 1 and c["cooldowns"] == 1 and c["levels"] == 1 and c["msgstats"] == 1 and c["flag_scores"] == 1 \
    and c["role_persist"] == 1 and c["giveaways"] == 1 and c["poll_votes"] == 1 and c["afk"] == 1 and c["games"] == 1 and c["limits"] == 2, c
assert len(ns["DD_USER"]) == 14 and set(c) == set(ns["DD_USER"]), "every category needs a label and a counter"
r = ns["dd_delete_user"](U, ["wallet", "bank", "inventory", "cooldowns", "giveaways", "poll_votes", "afk", "games", "limits"]); flush(ns)
assert r == {"wallet": 2, "bank": 1, "inventory": 1, "cooldowns": 1, "giveaways": 1, "poll_votes": 1, "afk": 1, "games": 1, "limits": 2}, r
ns2 = boot(); p = ns2["economy_db"][G1][U]                    # partial deletes keep the profile, only the chosen fields are gone
assert p["wallet"] == 0 and p["bank"] == 0 and p["inventory"] == [] and not any(k.startswith("last_") for k in p), p
assert ns2["economy_db"][G1][V] == {"wallet": 7, "last_daily": 3}, "other users must stay untouched"
assert U not in ns2["giveaways_db"][G1]["1"]["participants"] and V in ns2["giveaways_db"][G1]["1"]["participants"]
assert U not in ns2["polls_db"][G1]["m1"]["votes"] and ns2["polls_db"][G1]["m1"]["votes"] == {V: 1}
r = ns2["dd_delete_user"](U, ["economy", "levels", "msgstats", "flag_scores", "role_persist"]); flush(ns2)
ns3 = boot()
assert U not in ns3["economy_db"].get(G1, {}) and U not in ns3["economy_db"].get(G2, {}) and ns3["economy_db"][G1][V]["wallet"] == 7
assert U not in ns3["levels_db"].get(G1, {}) and U not in ns3["msgstats_db"].get(G1, {}) and U not in ns3["flag_scores_db"].get(G1, {}) and U not in ns3["role_persist_db"].get(G1, {})
# moderation records, bans, whitelist and timers are never touched by a data deletion
assert U in ns3["warns_db"][G1] and U in ns3["modlogs_db"][G1] and ns3["bot_bans_db"]["banned"] == [U] and U in ns3["whitelist_db"] and len(ns3["schedule_db"]["tasks"]) == 1
print("deletedata tests: ALL PASSED (14 categories, partial resets, persistence after restart, moderation records untouched)")
