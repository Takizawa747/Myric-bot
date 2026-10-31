import ast, asyncio, json, os, sqlite3, sys, tempfile, threading, time as _time, types
from datetime import datetime, timezone
BOT = __import__("os").environ.get("BOT_SRC", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "bot.py")); SRC = open(BOT, encoding="utf-8").read(); TREE = ast.parse(SRC)
def nm(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return n.name
    if isinstance(n, ast.Assign):
        t = n.targets[0]; return t.id if isinstance(t, ast.Name) else t.elts[0].id if isinstance(t, ast.Tuple) else None
def seg(*names): return "\n\n".join(ast.get_source_segment(SRC, n) for want in names for n in TREE.body if nm(n) == want)
def block(first, last):
    names = [nm(n) for n in TREE.body]; i, j = names.index(first), names.index(last)
    return "\n".join(ast.get_source_segment(SRC, n) for n in TREE.body[i:j + 1])
fails = []
def check(c, m):
    if not c: fails.append(m)
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw)
    def add_field(self, *a, **k): pass
    def set_footer(self, *a, **k): pass
dms = []
class User:
    async def send(self, **kw): dms.append(("banned-user", kw))
async def fetch_user(i): return User()
os.chdir(tempfile.mkdtemp()); json.dump({"banned": ["5"], "servers": []}, open("bot_bans.json", "w"))
DBSRC = block("DB_PATH", "flush_now")
def boot():
    ns = {"os": os, "json": json, "sqlite3": sqlite3, "threading": threading, "_time": _time, "datetime": datetime, "timezone": timezone}
    exec(compile(DBSRC, "db", "exec"), ns)
    ns["BOT_BANS_FILE"] = "bot_bans.json"; ns["bot_bans_db"] = ns["load_json"]("bot_bans.json")
    ns["bot_bans_db"].setdefault("banned", []); ns["bot_bans_db"].setdefault("servers", [])
    ns["save_bot_bans"] = lambda: ns["save_json"]("bot_bans.json", ns["bot_bans_db"])
    ns.update(BOT_CREATOR_ID=1, SUPPORT_LINK="https://discord.gg/x", discord=types.SimpleNamespace(Embed=Embed), is_whitelisted=lambda uid, perm=None: True,
              bot=types.SimpleNamespace(fetch_user=fetch_user), rate_limited=lambda uid: False)
    ns["bot_bans_db"].setdefault("restricted", {}); ns["FEATURE_LABELS"] = {"economy": "💰 Economy", "casino": "🎰 Casino"}
    exec(compile(seg("reload_bans", "global_check", "RESTRICTABLE", "_EXTRA_RESTRICT_LABELS", "restrict_label", "user_restricted", "current_restrictions", "apply_restrictions"), "bot", "exec"), ns); return ns
def flush(ns):
    ch = []
    for name in list(ns["_stores"]):
        ns["touch_all"](name); b = list(ns["_touched"][name]); ns["_touched"][name] = set(); ch += ns["_collect_store"](name, b)
    ns["_write"](ch)
owner_out = []
async def adel(): pass
async def asend(*a, **kw): owner_out.append(kw["embed"].description if kw.get("embed") is not None else a[0])
owner = types.SimpleNamespace(message=types.SimpleNamespace(delete=adel), author=types.SimpleNamespace(id=1, send=asend))
def ctx_of(uid): return types.SimpleNamespace(guild=types.SimpleNamespace(id=100), author=types.SimpleNamespace(id=uid))
async def go():
    ns = boot(); gc = ns["global_check"]; ap, ur, cur, bdb = ns["apply_restrictions"], ns["user_restricted"], ns["current_restrictions"], ns["bot_bans_db"]
    check(await gc(ctx_of(777)) is True, "an unbanned user can use commands")
    check(ap(777, {"all"}) == (True, []) and "777" in bdb["banned"], "a full ban is active immediately (this was the reported bug)")
    check(await gc(ctx_of(777)) is False, "a banned user's commands must be blocked right away")
    check(all(ur(777, f) for f in ns["RESTRICTABLE"]), "a full ban covers every feature")
    check(await gc(ctx_of(1)) is True and await gc(ctx_of(888)) is True, "creator and other users are not affected")
    ns["reload_bans"]()
    check("777" in bdb["banned"] and ns["_stores"]["bot_bans"] is bdb, "reload_bans() must not replace or empty the live data")
    check(ap(888, {"economy", "casino", "bogus"}) == (False, ["economy", "casino"]), "a partial restriction keeps only known features")
    check(ur(888, "economy") and ur(888, "casino") and not ur(888, "leveling") and not ur(888, "tickets"), "only the chosen features are blocked")
    check(await gc(ctx_of(888)) is True, "a partly restricted user is NOT blocked globally")
    check(cur(888) == {"economy", "casino"} and cur(777) == {"all"} and cur(424242) == set(), f"current_restrictions: {cur(888)} {cur(777)}")
    check(ns["restrict_label"]("afk") == "💤 AFK" and ns["restrict_label"]("economy") == "💰 Economy", "restriction labels")
    flush(ns); ns2 = boot(); b2 = ns2["bot_bans_db"]; ap2, ur2 = ns2["apply_restrictions"], ns2["user_restricted"]
    check(sorted(b2["banned"]) == ["5", "777"] and b2["restricted"] == {"888": ["economy", "casino"]}, f"bans and restrictions must survive a restart: {b2}")
    check(await ns2["global_check"](ctx_of(777)) is False and ur2(888, "casino"), "still enforced after restart")
    check(ap2(888, {"leveling"}) == (False, ["leveling"]) and ur2(888, "leveling") and not ur2(888, "economy"), "choosing again REPLACES the old restrictions")
    check(ap2(777, {"poll"}) == (False, ["poll"]) and "777" not in b2["banned"] and ur2(777, "poll") and not ur2(777, "economy"), "a full ban can be narrowed to one feature")
    check(await ns2["global_check"](ctx_of(777)) is True, "a narrowed user may use commands again")
    check(ap2(777, set()) == (False, []) and "777" not in b2["restricted"], "an empty choice lifts everything and leaves no empty entry")
    check(ap2(888, set()) == (False, []) and b2["restricted"] == {}, "lifting the last restriction empties the table")
    flush(ns2); ns3 = boot(); b3 = ns3["bot_bans_db"]
    check(b3["banned"] == ["5"] and b3["restricted"] == {}, f"lifting must persist too: {b3}")
    b3["banned"].append("1"); check(ns3["user_restricted"](1, "economy") is False, "the creator is never restricted, even if listed by mistake")
asyncio.run(go())

# ---------- the notice a restricted user gets ----------
async def notify_tests():
    ns = boot(); ns["L"] = lambda t, *a: t.format(*a) if a else t
    exec(compile(seg("_restrict_notice", "restricted_text", "notify_restricted"), "bot", "exec"), ns)
    sent = []
    async def reply(text, **kw): sent.append((text, kw))
    ctx = types.SimpleNamespace(author=types.SimpleNamespace(id=888), message=types.SimpleNamespace(reply=reply), channel=None)
    await ns["notify_restricted"](ctx, "economy")
    check(len(sent) == 1 and "Economy" in sent[0][0] and sent[0][1] == {"mention_author": False, "silent": True, "delete_after": 10}, f"silent, self-deleting, ping-free notice: {sent}")
    await ns["notify_restricted"](ctx, "economy"); check(len(sent) == 1, "no second notice within a minute")
    await ns["notify_restricted"](ctx, "casino"); check(len(sent) == 2, "another feature may notify")
    ns["_restrict_notice"][(888, "economy")] -= 61; await ns["notify_restricted"](ctx, "economy"); check(len(sent) == 3, "after a minute it may appear again")
asyncio.run(notify_tests())

# ---------- banned users: chat is untouched, a command gets a private notice ----------
sent_dm, deleted, invoked, hp_calls, replies = [], [], [], [], []
class BU:
    def __init__(self, uid): self.id, self.bot = uid, False
    async def send(self, **kw): sent_dm.append((self.id, kw["embed"].description))
async def silent_delete(m): deleted.append(m); return True
async def hp(m): hp_calls.append(m); return m.content == "trap"
async def no(m): return False
_cmd = {"valid": False}
async def get_context(m): return types.SimpleNamespace(valid=_cmd["valid"], command=object() if _cmd["valid"] else None)
async def invoke(ctx): invoked.append(ctx)
omns = dict(bot=types.SimpleNamespace(get_context=get_context, invoke=invoke, user=types.SimpleNamespace(id=999)), bot_bans_db={"banned": ["777"], "servers": []}, BOT_CREATOR_ID=1, set_lang=lambda g: None,
            get_settings=lambda g: {}, handle_honeypot=hp, handle_counting=no, silent_delete=silent_delete, L=lambda t, *a: t.format(*a) if a else t,
            SUPPORT_LINK="https://discord.gg/x", discord=types.SimpleNamespace(Embed=Embed), _time=_time, afk_db={}, is_feature_enabled=lambda *a: False,
            GENERAL_CMDS=set(), is_owner=lambda u: False, handle_whitelist_dm=no, handle_deletedata_dm=no, handle_owner_dm=no, user_restricted=lambda *a: False)
exec(compile(seg("_ban_notice", "notify_bot_banned", "on_message"), "bot", "exec"), omns)
def msg(uid, text, ch=5):
    async def reply(text_, **kw): replies.append((uid, text_, kw))
    return types.SimpleNamespace(author=BU(uid), guild=types.SimpleNamespace(id=100, get_channel=lambda i: None), content=text, mentions=[], channel=types.SimpleNamespace(id=ch), reply=reply)
async def ban_chat_tests():
    om = omns["on_message"]
    _cmd["valid"] = False; await om(msg(777, "hi everyone"))
    check(not deleted and not sent_dm and not replies and not invoked, "normal chat of a banned user must be left alone")
    _cmd["valid"] = True; await om(msg(777, ".ping"))
    check(not sent_dm, "no DM may ever be sent (spam / reports)")
    check(not deleted and not invoked and len(replies) == 1, f"command attempt -> command blocked, message kept, one reply: {replies}")
    uid, text_, kw = replies[0]
    check("banned" in text_ and kw.get("silent") is True and kw.get("delete_after") == 10 and kw.get("mention_author") is False, f"reply must be silent, self-deleting and ping-free: {kw}")
    await om(msg(777, ".ping")); await om(msg(777, ".help")); check(len(replies) == 1, "no second reply within a minute (anti-spam)")
    omns["_ban_notice"][777] -= 61; await om(msg(777, ".ping")); check(len(replies) == 2, "after a minute the notice may appear again")
    await om(msg(888, ".ping")); check(len(invoked) == 1 and not deleted and len(replies) == 2, "a normal user's command still runs")
    _cmd["valid"] = False; invoked.clear(); await om(msg(888, "hello")); check(len(invoked) == 1, "normal user chat goes to the normal pipeline")
    n = len(replies); await om(msg(777, "trap")); check(len(hp_calls) >= 1 and len(replies) == n, "the honeypot still sees banned users' messages")
asyncio.run(ban_chat_tests())
print("ban/unban tests:", "ALL PASSED (full ban, partial restrictions, restart persistence, lifting, creator protected, notices)" if not fails else f"{len(fails)} FAILED")
for f in fails: print("  FAIL:", f)
sys.exit(1 if fails else 0)
