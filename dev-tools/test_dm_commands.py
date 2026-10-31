import ast, asyncio, decimal, math, re, sys, types
BOT = __import__("os").environ.get("BOT_SRC", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "bot.py")); SRC = open(BOT, encoding="utf-8").read(); TREE = ast.parse(SRC)
def nm(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return n.name
    if isinstance(n, ast.Assign):
        t = n.targets[0]; return t.id if isinstance(t, ast.Name) else None
def seg(*names):
    out = [ast.get_source_segment(SRC, n) for want in names for n in TREE.body if nm(n) == want]
    assert len(out) == len(names), f"missing {names}"; return "\n\n".join(out)
fails = []
def check(c, m):
    if not c: fails.append(m)
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw)
sent = []
class Chan:
    async def send(self, content=None, **kw): sent.append(content if content is not None else kw.get("embed"))
def msg(uid=1, text=""): return types.SimpleNamespace(author=types.SimpleNamespace(id=uid), channel=Chan(), content=text)
G1 = types.SimpleNamespace(id=1000)
econ, levels_db, picks = {}, {}, []
def get_econ(gid, uid): return econ.setdefault((gid, uid), {"wallet": 0, "bank": 0, "inventory": []})
def get_user_xp(gid, uid): return levels_db.setdefault(str(gid), {}).setdefault(str(uid), {"xp": 0, "level": 0})
async def pick_guilds(message, uid, guild_arg=None, allow_all=False, only=None):
    picks.append((uid, guild_arg)); return [G1] if guild_arg is None else [types.SimpleNamespace(id=int(guild_arg))]
ns = dict(discord=types.SimpleNamespace(Embed=Embed), re=re, decimal=decimal, get_econ=get_econ, save_econ=lambda: None, get_user_xp=get_user_xp, pick_guilds=pick_guilds,
          guild_label=lambda g: f"G{g.id}", get_level=lambda xp, gid=None: int(math.sqrt(max(0, xp) / 100)), xp_for_level=lambda lv, gid=None: lv * lv * 100,
          levels_db=levels_db, touch=lambda *a: None, save_json=lambda *a: None, LEVELS_FILE="x")
AMT = [nm(n) for n in TREE.body if (nm(n) or "").startswith("_AMOUNT")]
exec(seg(*AMT, "parse_amount", "_id_of", "_money", "_level", "dm_addmoney", "dm_removemoney", "dm_setmoney", "dm_resetmoney",
         "dm_addlevel", "dm_removelevel", "dm_setlevel", "dm_resetlevel", "dm_addxp", "dm_removexp"), ns)
UID, UIDI = "123456789012345678", 123456789012345678
def usage_shown(): return bool(sent) and isinstance(sent[-1], str) and sent[-1].startswith("❌ Usage")
async def money_tests():
    m = msg(); w = lambda: get_econ(1000, UIDI)["wallet"]
    await ns["dm_addmoney"](m, [UID, "5k"]); check(w() == 5000, f"addmoney 5k -> {w()}")
    await ns["dm_removemoney"](m, [UID, "2000"]); check(w() == 3000, "removemoney")
    await ns["dm_removemoney"](m, [UID, "999999"]); check(w() == 0, "removemoney never goes below 0")
    await ns["dm_setmoney"](m, [UID, "777"]); check(w() == 777, "setmoney"); await ns["dm_setmoney"](m, [UID, "0"]); check(w() == 0, "setmoney 0 is allowed")
    get_econ(1000, UIDI)["wallet"], get_econ(1000, UIDI)["bank"] = 40, 50
    await ns["dm_resetmoney"](m, [UID]); check(get_econ(1000, UIDI)["wallet"] == 0 and get_econ(1000, UIDI)["bank"] == 0, "resetmoney clears wallet AND bank")
    n = len(picks)
    for bad in ([UID, "0"], [UID, "-5"], ["abc", "5"], [UID], [], [UID, "lots"]):
        sent.clear(); await ns["dm_addmoney"](m, bad); check(usage_shown() and w() == 0, f"bad input {bad} must show the usage and change nothing")
    check(len(picks) == n, "no server is asked for when the input is invalid")
    await ns["dm_addmoney"](m, [UID, "10", "222"]); check(picks[-1] == (UIDI, "222") and get_econ(222, UIDI)["wallet"] == 10, f"addmoney server id is the 3rd argument: {picks[-1]}")
    await ns["dm_resetmoney"](m, [UID, "222"]); check(picks[-1] == (UIDI, "222"), f"resetmoney server id is the 2nd argument: {picks[-1]}")
async def level_tests():
    m = msg(); lv = lambda: get_user_xp(1000, UIDI)
    await ns["dm_addlevel"](m, [UID, "3"]); check(lv() == {"xp": 900, "level": 3}, f"addlevel 3 -> {lv()}")
    await ns["dm_addlevel"](m, [UID, "2"]); check(lv() == {"xp": 2500, "level": 5}, f"addlevel +2 -> {lv()}")
    await ns["dm_addlevel"](m, [UID]); check(lv()["level"] == 6, "addlevel without a number adds 1")
    await ns["dm_removelevel"](m, [UID, "99"]); check(lv() == {"xp": 0, "level": 0}, "removelevel never goes below 0")
    await ns["dm_setlevel"](m, [UID, "7"]); check(lv() == {"xp": 4900, "level": 7}, "setlevel")
    await ns["dm_addxp"](m, [UID, "100"]); check(lv() == {"xp": 5000, "level": 7}, f"addxp -> {lv()}")
    await ns["dm_removexp"](m, [UID, "4950"]); check(lv() == {"xp": 50, "level": 0}, f"removexp recomputes the level -> {lv()}")
    await ns["dm_removexp"](m, [UID, "99999"]); check(lv()["xp"] == 0, "removexp never goes below 0")
    await ns["dm_resetlevel"](m, [UID]); check(UID not in levels_db.get("1000", {}), "resetlevel deletes the row")
    for bad, fn in (([UID], "dm_setlevel"), ([UID, "-1"], "dm_addlevel"), (["x", "1"], "dm_addlevel"), ([], "dm_resetlevel")):
        sent.clear(); await ns[fn](m, bad); check(usage_shown(), f"{fn} {bad} must show the usage")
    await ns["dm_resetlevel"](m, [UID, "222"]); check(picks[-1] == (UIDI, "222"), f"resetlevel server id is the 2nd argument: {picks[-1]}")
    await ns["dm_addlevel"](m, [UID, "1", "222"]); check(picks[-1] == (UIDI, "222"), f"addlevel server id is the 3rd argument: {picks[-1]}")
asyncio.run(money_tests()); asyncio.run(level_tests())

# ---------- the DM dispatcher ----------
calls = []
def mk(name):
    async def h(message, args): calls.append((name, args))
    return h
async def boom(message, args): raise RuntimeError("kaboom")
WL = {1: None, 50: {"banuser"}, 60: set()}
def is_whitelisted(uid, perm=None):
    if uid == 1: return True
    if uid not in WL: return False
    return perm is None or perm in WL[uid]
dns = dict(discord=types.SimpleNamespace(Embed=Embed), is_whitelisted=is_whitelisted,
           DM_COMMANDS={"banuser": ("banuser", mk("banuser"), "banuser <USER_ID>", "Ban"), "addmoney": ("addmoney", mk("addmoney"), "addmoney <ID> <N>", "Add"),
                        "crash": ("crash", boom, "crash", "x"), "backup": ("backup", mk("backup"), "backup", "creator only")})
exec(seg("DM_ALIASES", "dm_help_embed", "handle_owner_dm"), dns)
async def dispatch_tests():
    h = dns["handle_owner_dm"]
    sent.clear(); m = msg(99, "banuser 5"); check(await h(m) is False and not calls and not sent, "a stranger's DM is not an owner command (it goes to modmail)")
    check(await h(msg(1, "banuser 123")) is True and calls[-1] == ("banuser", ["123"]), f"creator command: {calls}")
    check(await h(msg(1, ".addmoney 1 2")) is True and calls[-1] == ("addmoney", ["1", "2"]), "a leading '.' is accepted")
    check(await h(msg(50, "BANUSER 9")) is True and calls[-1] == ("banuser", ["9"]), "whitelisted user with the permission, any letter case")
    n = len(calls); sent.clear()
    check(await h(msg(50, "addmoney 1 2")) is True and len(calls) == n and "permission" in sent[-1], f"whitelisted user WITHOUT the permission is refused: {sent}")
    check(await h(msg(1, "botban 5")) is True and calls[-1] == ("banuser", ["5"]), "aliases work")
    check(await h(msg(1, "hello there")) is False and await h(msg(1, "   ")) is False, "non-commands fall through to the normal DM handling")
    sent.clear(); check(await h(msg(1, "crash")) is True and any("kaboom" in str(x) for x in sent), "a crashing handler is reported, not raised")
    sent.clear(); await h(msg(50, "help")); d = sent[-1].description
    check("banuser" in d and "addmoney" not in d and "backup" not in d, f"help lists only what the user may use: {d!r}")
    sent.clear(); await h(msg(1, "help")); d = sent[-1].description; check("banuser" in d and "addmoney" in d and "backup" in d, "the creator sees everything")
    sent.clear(); await h(msg(60, "help")); check(sent[-1].description == "You have no commands.", "a whitelisted user without permissions sees an empty list")
asyncio.run(dispatch_tests())

# ---------- list output ----------
bns = dict(bot_bans_db={"banned": ["5"], "restricted": {"6": ["economy", "afk"], "5": ["poll"]}, "servers": []}, restrict_label=lambda f: {"economy": "💰 Economy", "afk": "💤 AFK", "poll": "📋 Poll"}[f])
exec(seg("_send_chunks", "dm_bannedusers"), bns)
async def list_tests():
    sent.clear(); await bns["dm_bannedusers"](msg(1), []); out = sent[-1]
    check("`5` — everything" in out and "`6` — 💰 Economy, 💤 AFK" in out and "Poll" not in out, f"bannedusers output: {out!r}")
    bns["bot_bans_db"].update(banned=[], restricted={}); sent.clear(); await bns["dm_bannedusers"](msg(1), []); check("Nobody" in sent[-1], "empty list message")
    lines = [f"line {i} " + "x" * 90 for i in range(60)]; sent.clear(); await bns["_send_chunks"](Chan(), lines)
    check(len(sent) >= 3 and all(len(x) <= 2000 for x in sent) and "".join(sent).count("line ") == 60, "long lists are split below Discord's 2000-char limit")
asyncio.run(list_tests())
print("DM commands:", "ALL PASSED (money, levels, argument positions, dispatcher, permissions, lists)" if not fails else f"{len(fails)} FAILED")
for f in fails: print("  FAIL:", f)
sys.exit(1 if fails else 0)
