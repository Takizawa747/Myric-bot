import ast, asyncio, re, sys, types
from datetime import datetime, timezone
BOT = __import__("os").environ.get("BOT_SRC", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "bot.py")); SRC = open(BOT, encoding="utf-8").read(); TREE = ast.parse(SRC)
def nm(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return n.name
    if isinstance(n, ast.Assign):
        t = n.targets[0]; return t.id if isinstance(t, ast.Name) else None
def seg(*names):
    out = [ast.get_source_segment(SRC, n) for want in names for n in TREE.body if nm(n) == want]
    assert len(out) == len(names), f"missing {names}"; return "\n\n".join(out)
def assigned(name): return next(n for n in TREE.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
fails = []
def check(c, m):
    if not c: fails.append(m)
# ---- 1) things top.gg reviewers and the guidelines look at
check("create_invite" not in SRC, "the bot must never create invite links")
check(re.search(r'SUPPORT_LINK\s*=\s*"https://discord\.gg/[A-Za-z0-9]+"', SRC) is not None and "https://https" not in SRC, "SUPPORT_LINK must be one valid https link")
bad = sorted(set(w.lower() for w in re.findall(r"\b(cigarette|cigar|beer|vodka|whiskey|whisky|weed|cocaine|heroin|meth|marijuana|cannabis|opium|lsd|syringe|narcotic|ecstasy)\b", SRC, re.I)))
check(not bad, f"drug / alcohol / tobacco terms must not appear anywhere in the bot: {bad}")
check(not re.search(r"\b(porn|hentai|nude)\b", SRC, re.I), "no adult content")
check("Intents.all()" not in SRC and "intents.presences" not in SRC, "the presence intent is not needed and must not be requested")
check("administrator=True" not in SRC and "permissions=8" not in SRC and "Permissions(administrator" not in SRC, "the bot must never ask for Administrator")
check("activity=discord.Game" in SRC and '"__all__"' in SRC and "<@!{bot.user.id}>" in SRC and "when_mentioned" in SRC, "status, 'All commands' help page and mention handling exist")
check(not re.search(r"\b(eval|exec)\(", SRC.replace("exec(compile", "")), "no eval/exec commands")
# ---- 2) help: the /setup list matches the registered subcommands; every prefix command is documented in all 3 languages
subs = sorted(re.findall(r'^@setup_group\.command\(name="(\w+)"', SRC, re.M)); listed = sorted(x.strip() for x in ast.literal_eval(assigned("_SETUP_LIST").value).split("`/setup`")[1].split("·"))
check(listed == subs, f"/setup list is out of date: stale {sorted(set(listed) - set(subs))}, missing {sorted(set(subs) - set(listed))}")
prefix = {}
for node in TREE.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and ast.unparse(d.func) == "bot.command":
                kw = {k.arg: k.value for k in d.keywords}
                prefix[kw["name"].value if "name" in kw else node.name] = [e.value for e in kw["aliases"].elts] if "aliases" in kw else []
hn = assigned("HELP_TEXT")
for k, v in zip(hn.value.keys, hn.value.values):
    blob = ast.get_source_segment(SRC, v)
    miss = [n for n, al in prefix.items() if f"{{p}}{n}" not in blob and not any(f"{{p}}{a}" in blob for a in al)]
    check(not miss, f"help [{k.value}] does not mention these commands: {miss}")
# ---- 3) behaviour
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw); self.footer = types.SimpleNamespace(text=None)
    def set_footer(self, text=None, **k): self.footer = types.SimpleNamespace(text=text); return self
class Command:
    def __init__(self, name): self.name = name
class Group:
    def __init__(self, name, subs): self.name, self.commands = name, [Command(s) for s in subs]
class Clock:
    t = 20000 * 86400.0 + 3600
    def time(self): return self.t
clock, touched, settings_db, msgstats_db, bans = Clock(), [], {}, {}, {"dm_optout": []}
Forbidden = type("Forbidden", (Exception,), {})
ns = dict(discord=types.SimpleNamespace(Embed=Embed, MessageType=types.SimpleNamespace(default="default", reply="reply"), Forbidden=Forbidden), _time=clock, datetime=datetime, timezone=timezone,
          L=lambda s, *a: s.format(*a) if a else s, bot_bans_db=bans, save_bot_bans=lambda: None, msgstats_db=msgstats_db, settings_db=settings_db, touch=lambda *a: touched.append(a),
          get_settings=lambda gid: settings_db.setdefault(str(gid), {}), save_settings=lambda: None, app_commands=types.SimpleNamespace(Command=Command, Group=Group),
          bot=types.SimpleNamespace(commands=[types.SimpleNamespace(name=n, hidden=h) for n, h in (("ban", False), ("secret", True), ("help", False))],
                                    tree=types.SimpleNamespace(get_commands=lambda: [Command("ping"), Command("rank"), Group("setup", ["vc", "log"]), Group("rroles", ["create"])])))
ns["is_feature_enabled"] = lambda gid, f: gid == 1 and f == "dmnotices"
exec(seg("dm_is_off", "dm_optout_set", "send_dm", "dms_reply", "build_all_commands_text", "MSG_KEEP_DAYS", "_msg_day", "counts_as_message", "count_message", "msg_counts", "msg_stats_text", "msg_stats_footer"), ns)
sent = []
class U:
    def __init__(self, uid): self.id = uid
    async def send(self, **kw): sent.append((self.id, kw))
async def dm_tests():
    u, e = U(5), Embed(description="x")
    check(await ns["send_dm"](u, embed=e, notify=True) is True and sent[-1][1]["embed"] is e and "anonymous" in e.footer.text and "/dms off" in e.footer.text, "a staff DM says it is anonymous and how to stop it")
    e2 = Embed(); e2.set_footer(text="mine"); await ns["send_dm"](u, embed=e2, notify=True); check(e2.footer.text == "mine", "an existing footer is kept")
    ns["dm_optout_set"](5, True); ns["dm_optout_set"](5, True); n = len(sent)
    check(bans["dm_optout"] == ["5"] and ns["dm_is_off"](5) and not ns["dm_is_off"](6), "opt-out is stored once")
    check(await ns["send_dm"](u, embed=Embed(), notify=True) is False and len(sent) == n, "opted-out people get nothing")
    check(await ns["send_dm"](u, embed=Embed(), essential=True) is True and len(sent) == n + 1, "'essential' bypasses the opt-out")
    ns["dm_optout_set"](5, False); check(bans["dm_optout"] == [] and await ns["send_dm"](u, embed=Embed(), notify=True) is True, "turning DMs on again works")
    async def bad(**kw): raise RuntimeError("dms closed")
    u2 = U(7); u2.send = bad
    try: await ns["send_dm"](u2, embed=Embed(), notify=True); check(False, "a failing DM must raise so callers can ignore it")
    except RuntimeError: pass
    check("**off**" in ns["dms_reply"](True) and "**on**" in ns["dms_reply"](False), "replies")
async def dm_policy_tests():
    u = U(31); n = len(sent)
    check(await ns["send_dm"](u, embed=Embed()) is False and len(sent) == n, "NOTHING is sent unless the person running the action asked for it")
    check(await ns["send_dm"](u, embed=Embed(), guild=types.SimpleNamespace(id=2)) is False, "a server without 'Moderation DMs' sends nothing")
    check(await ns["send_dm"](u, embed=Embed(), guild=types.SimpleNamespace(id=1)) is True, "a server that switched 'Moderation DMs' on may send")
    check(await ns["send_dm"](u, embed=Embed(), guild=types.SimpleNamespace(id=1), notify=False) is False, "-nodm beats the server default")
asyncio.run(dm_tests()); asyncio.run(dm_policy_tests())
t = ns["build_all_commands_text"]("."); check("`.ban`" in t and "`.help`" in t and "secret" not in t and "`/ping`" in t and "`/rank`" in t and "**/setup**: `log` `vc`" in t and "**/rroles**: `create`" in t, f"all-commands page: {t!r}")
ns["bot"].commands += [types.SimpleNamespace(name=f"cmd{i}" * 3, hidden=False) for i in range(900)]; check(len(ns["build_all_commands_text"](".")) <= 4000, "the page never exceeds the embed limit")
# ---- message counts: rolling windows, pruning, since-date
mc, count, D = ns["msg_counts"], ns["count_message"], lambda n: setattr(clock, "t", clock.t + n * 86400)
for _ in range(3): count(1, 42)
check(mc(1, 42) == {"today": 3, "week": 3, "month": 3, "total": 3} and ("msgstats", "1", "42") in touched, f"first day: {mc(1, 42)}")
since = settings_db["1"]["msgcount_since"]; check(re.fullmatch(r"\d{4}-\d\d-\d\d", since) is not None, "the 'counted since' date is recorded")
D(1); count(1, 42); count(1, 42); check(mc(1, 42) == {"today": 2, "week": 5, "month": 5, "total": 5}, f"second day: {mc(1, 42)}")
D(6); count(1, 42); check(mc(1, 42) == {"today": 1, "week": 3, "month": 6, "total": 6}, f"day 7 (week window = days 1..7): {mc(1, 42)}")
D(23); count(1, 42); r = msgstats_db["1"]["42"]
check(mc(1, 42) == {"today": 1, "week": 1, "month": 4, "total": 7} and len(r["d"]) <= 30 and str(20000) not in r["d"], f"day 30 (month window = days 1..30, day 0 pruned): {mc(1, 42)} {r['d']}")
check(settings_db["1"]["msgcount_since"] == since and ns["msg_stats_footer"](1).startswith("Messages counted since") and ns["msg_stats_footer"](999) is None, "'since' never moves")
check(mc(1, 999) == {"today": 0, "week": 0, "month": 0, "total": 0} and mc(2, 42)["total"] == 0, "unknown users and other servers are separate")
r["t"] = 1234567; check("**1,234,567**" in ns["msg_stats_text"](1, 42) and "Today" in ns["msg_stats_text"](1, 42), "numbers use thousands separators")
cm = ns["counts_as_message"]; check(cm(types.SimpleNamespace(type="default")) and cm(types.SimpleNamespace(type="reply")) and not cm(types.SimpleNamespace(type="user_join")) and not cm(types.SimpleNamespace()), "only real chat messages count")
# ---- the prefix, with mentions
pns = dict(re=re, OWNER_ONLY_CMDS=set(), settings_db={"1": {"prefix": "!"}}, commands=types.SimpleNamespace(when_mentioned=lambda b, m: ["<@9> ", "<@!9> "]))
exec(seg("_base_prefix", "get_prefix"), pns); gm = lambda gid, txt: types.SimpleNamespace(guild=types.SimpleNamespace(id=gid) if gid else None, content=txt)
check(pns["get_prefix"](None, gm(1, "!ping")) == ["<@9> ", "<@!9> ", "!", "."] and pns["get_prefix"](None, gm(2, "x")) == ["<@9> ", "<@!9> ", "."] and pns["get_prefix"](None, gm(None, "x")) == ["<@9> ", "<@!9> ", "."], "prefixes: mention + custom + dot")
# ---- permission problems get a clear message (prefix and slash)
class CheckFailure(Exception): pass
class MissingPermissions(CheckFailure):
    def __init__(self, p): self.missing_permissions = p
class BotMissingPermissions(CheckFailure):
    def __init__(self, p): self.missing_permissions = p
class NoPrivateMessage(CheckFailure): pass
class CommandNotFound(Exception): pass
class CommandOnCooldown(Exception):
    def __init__(self, ra): self.retry_after = ra
class MissingRequiredArgument(Exception):
    def __init__(self): self.param = types.SimpleNamespace(name="amount")
class BadArgument(Exception): pass
class Wrapped(Exception):
    def __init__(self, o): self.original = o
reports, out = [], []
async def _report_error(where, user, guild, error): reports.append((where, str(error)))
async def csend(text, delete_after=None): out.append(text)
ctx = types.SimpleNamespace(send=csend, prefix=".", command="x", author=None, guild=None)
cns = dict(L=ns["L"], discord=ns["discord"], _report_error=_report_error, commands=types.SimpleNamespace(MissingPermissions=MissingPermissions, BotMissingPermissions=BotMissingPermissions, NoPrivateMessage=NoPrivateMessage,
          CommandNotFound=CommandNotFound, CheckFailure=CheckFailure, CommandOnCooldown=CommandOnCooldown, MissingRequiredArgument=MissingRequiredArgument, BadArgument=BadArgument))
exec(seg("on_command_error"), cns)
async def err_tests():
    h = cns["on_command_error"]
    for err, expect in ((MissingPermissions(["ban_members"]), "Ban Members"), (BotMissingPermissions(["manage_roles", "kick_members"]), "I need the **Manage Roles, Kick Members**"), (NoPrivateMessage(), "only works in servers"),
                        (CommandOnCooldown(2.2), "3s"), (MissingRequiredArgument(), "amount"), (BadArgument(), "Invalid"), (Wrapped(Forbidden()), "permission"), (Exception("boom"), "Something went wrong")):
        out.clear(); reports.clear(); await h(ctx, err)
        check(len(out) == 1 and expect in out[0], f"{type(err).__name__}: {out}")
        check(bool(reports) == (type(err) is Exception), f"{type(err).__name__} reported to the owner: {reports}")
    for quiet in (CommandNotFound(), CheckFailure()):
        out.clear(); await h(ctx, quiet); check(out == [], f"{type(quiet).__name__} must stay silent")
asyncio.run(err_tests())
class AppErr(Exception): pass
class AMissing(AppErr, CheckFailure):
    def __init__(self, p): self.missing_permissions = p
class ABotMissing(AppErr, CheckFailure):
    def __init__(self, p): self.missing_permissions = p
class ACheck(AppErr, CheckFailure): pass
class ANoPrivate(ACheck): pass
class ACooldown(AppErr):
    def __init__(self, ra): self.retry_after = ra
class AWrapped(AppErr):
    def __init__(self, o): self.original = o
class Resp:
    def __init__(self, done): self.done = done
    def is_done(self): return self.done
    async def send_message(self, text, ephemeral=False): out.append(("response", text, ephemeral))
class Follow:
    async def send(self, text, ephemeral=False): out.append(("followup", text, ephemeral))
ans = dict(L=ns["L"], discord=types.SimpleNamespace(Forbidden=Forbidden, Interaction=object), _report_error=_report_error, app_commands=types.SimpleNamespace(AppCommandError=AppErr, MissingPermissions=AMissing, BotMissingPermissions=ABotMissing, CheckFailure=ACheck,
           NoPrivateMessage=ANoPrivate, CommandOnCooldown=ACooldown))
exec(seg("on_app_command_error"), ans)
async def app_tests():
    h = ans["on_app_command_error"]
    ia = lambda done: types.SimpleNamespace(response=Resp(done), followup=Follow(), command=types.SimpleNamespace(qualified_name="setup vc"), user=None, guild=None)
    for err, expect in ((AMissing(["manage_guild"]), "Manage Guild"), (ABotMissing(["ban_members"]), "I need the **Ban Members**"), (ACooldown(1.0), "2s"), (ANoPrivate(), "only works in servers"), (AWrapped(Forbidden()), "permission"), (AppErr("x"), "Something went wrong")):
        out.clear(); reports.clear(); await h(ia(False), err)
        check(len(out) == 1 and out[0][0] == "response" and out[0][2] is True and expect in out[0][1], f"{type(err).__name__}: {out}")
        check(bool(reports) == (type(err) is AppErr), f"{type(err).__name__} reported: {reports}")
    out.clear(); await h(ia(True), AppErr("x")); check(out and out[0][0] == "followup", "an already-answered interaction uses a followup")
    out.clear(); await h(ia(False), ACheck()); check(out == [], "a plain check failure stays silent (the check answered)")
asyncio.run(app_tests())
print("top.gg compliance:", "ALL PASSED (no invites, valid support link, no drug/alcohol terms, no admin, help complete, DM opt-out, message counts, errors)" if not fails else f"{len(fails)} FAILED")
for x in fails: print("  FAIL:", x)
sys.exit(1 if fails else 0)
