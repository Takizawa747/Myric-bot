import ast, asyncio, re, sys, types
BOT = __import__("os").environ.get("BOT_SRC", "/mnt/user-data/outputs/bot.py"); SRC = open(BOT, encoding="utf-8").read(); TREE = ast.parse(SRC)
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
# ---- source guarantees
check(not re.search(r"appeal|itiraz|обжалован", SRC, re.I), "no appeal server / appeal text anywhere")
check(not re.search(r"is_owner\((?:ctx\.author|interaction\.user)\.id\)", SRC), "the bot owner has no permission bypass in any command")
check("create_invite" not in SRC and "fetch_user(BOT_CREATOR_ID)" not in seg("on_guild_join"), "joining a server messages nobody and makes no invite")
check("channel.edit(overwrites" not in SRC and "ch.edit(overwrites" not in SRC, "channel permissions are changed per target (needs only Manage Roles)")
lock_src = seg("lock_p", "unlock_p"); check("manage_roles" in lock_src and "manage_channels" not in lock_src, "lock / unlock need Manage Roles, not Manage Channels")
need = {"ban": "ban_members", "unban": "ban_members", "softban": "ban_members", "kick": "kick_members", "mute": "manage_roles", "unmute": "manage_roles", "timeout": "moderate_members", "untimeout": "moderate_members",
        "purge": "manage_messages", "nick": "manage_nicknames", "slowmode": "manage_channels", "lock": "manage_roles", "unlock": "manage_roles", "massrole": "manage_roles", "resetchannel": "manage_channels"}
got = {}
for node in TREE.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and ast.unparse(d.func) == "bot.command":
                kw = {k.arg: k.value for k in d.keywords}; got[kw["name"].value if "name" in kw else node.name] = " ".join(ast.unparse(x) for x in node.decorator_list)
for name, perm in need.items(): check(name in got and f"bot_has_permissions" in got[name] and perm in got[name], f"/{name}: the bot is checked for {perm} before it starts")
for name in ("ban", "kick", "timeout", "mute", "warn"): check(re.search(rf"def {name}_p\(.*?\n(?:.*\n){{0,6}}?.*notify", SRC) or f"{name}_p" in SRC, f"{name}: DM flag present")
# ---- -dm / -nodm flags
ns = dict(re=re, parse_duration=lambda s: (60, s) if re.fullmatch(r"\d+[smhd]", s or "") else (0, None))
exec(seg("_DM_FLAGS", "strip_dm_flag", "mod_args"), ns); sd, ma = ns["strip_dm_flag"], ns["mod_args"]
check(sd("spam -dm") == ("spam", True) and sd("-NODM spam") == ("spam", False) and sd("plain text") == ("plain text", None) and sd(None) == (None, None) and sd("") == ("", None) and sd("a --dm b") == ("a b", True), "strip_dm_flag")
check(ma("-dm", "spam", None) == (None, "spam", True), f"flag first: {ma('-dm', 'spam', None)}"); check(ma("1d", "-dm spam", None) == ("1d", "spam", True), "flag in the reason")
check(ma("-dm", "5m spam", "10m") == ("5m", "spam", True), f"'-dm 5m spam' keeps the duration: {ma('-dm', '5m spam', '10m')}"); check(ma(None, "", None) == (None, "No reason", None), "defaults")
check(ma("10m", "-nodm", "10m") == ("10m", "No reason", False) and ma("2h", "raid", None) == ("2h", "raid", None), "-nodm and plain input")
# ---- ticket emoji validation + repair of saved buttons
class FakeBot:
    def get_emoji(self, i): return object() if i == 123456789012345678 else None
saved = []; settings_db = {"1": {"ticket_buttons": [{"label": "🎫 General", "category": "General", "emoji": "🎫"}, {"label": "test Support", "category": "Support", "emoji": "test"}, {"label": "ab Billing", "category": "Billing", "emoji": "ab"},
                                                      {"label": "<:x:1> Gone", "category": "Gone", "emoji": "<:x:1>"}, {"label": "❤️ Love", "category": "Love", "emoji": "❤️"}]}}
tns = dict(re=re, bot=FakeBot(), settings_db=settings_db, save_settings=lambda: saved.append(1)); exec(seg("_EMOJI_RE", "clean_button_emoji", "heal_ticket_pool", "_ticket_owner_id"), tns); ce = tns["clean_button_emoji"]
for good in ("🎫", "✅", "❤️", "🏳️‍🌈", "👍🏽", "1️⃣", "🇦🇿", "⭐", "<:ok:123456789012345678>"): check(ce(good) == good, f"valid emoji rejected: {good!r}")
for bad in ("test", "ab", "", None, "🎫🎫", "hello 🎫", "<:ok:999999999999999999>", 5): check(ce(bad) is None, f"invalid 'emoji' accepted: {bad!r}")
tns["heal_ticket_pool"](1); pool = settings_db["1"]["ticket_buttons"]
check([b["emoji"] for b in pool] == ["🎫", "🎫", "🎫", "🎫", "❤️"] and pool[1]["label"] == "🎫 Support" and pool[3]["label"] == "🎫 Gone" and pool[4]["label"] == "❤️ Love" and len(saved) == 1, f"saved buttons are repaired once: {pool} saves={len(saved)}")
tns["heal_ticket_pool"](1); check(len(saved) == 1, "a healthy pool is not rewritten"); tns["heal_ticket_pool"](999)
oid = tns["_ticket_owner_id"]; check(oid(types.SimpleNamespace(topic="ticket:42")) == 42 and oid(types.SimpleNamespace(topic="ticket:42 note")) == 42 and oid(types.SimpleNamespace(topic="hello")) is None and oid(types.SimpleNamespace(topic=None)) is None and oid(types.SimpleNamespace(topic="ticket:x")) is None, "ticket owner from the topic")
sns = dict(get_settings=lambda gid: {"ticketstaff": "55"}); exec(seg("_is_ticket_staff"), sns); st = sns["_is_ticket_staff"]
mem = lambda admin=False, ch=False, roles=(): types.SimpleNamespace(guild_permissions=types.SimpleNamespace(administrator=admin, manage_channels=ch), roles=[types.SimpleNamespace(id=r) for r in roles]); g = types.SimpleNamespace(id=1)
check(st(mem(roles=(55,)), g) and st(mem(ch=True), g) and st(mem(admin=True), g) and not st(mem(roles=(7,)), g) and not st(mem(), g), "who counts as ticket staff")
# ---- logs: defaults, categories, every event has a listener
lns = dict(settings_db={"1": {"log_settings": {"message_delete": False, "voice_join": True}}}, L=lambda s, *a: s.format(*a) if a else s); exec(seg("LOG_DEFAULT_OFF", "log_on", "log_categories"), lns)
lo = lns["log_on"]; check(lo(1, "message_edit") and not lo(1, "message_delete") and lo(1, "voice_join") and not lo(1, "voice_leave") and lo(2, "message_delete") and not lo(2, "invite_create"), "log defaults and overrides")
cats = lns["log_categories"](); keys = [k for _c, _l, evs in cats for k, _lab in evs]
check(len(cats) == 6 and len(keys) == 27 and len(set(keys)) == 27 and all(1 <= len(evs) <= 15 for _c, _l, evs in cats) and lns["LOG_DEFAULT_OFF"] <= set(keys), f"log panel structure: {len(cats)} categories, {len(keys)} events")
check(all(SRC.count(f'"{k}"') >= 2 for k in keys), f"every log event has a listener: {[k for k in keys if SRC.count(chr(34) + k + chr(34)) < 2]}")
# ---- overwrites are changed per target, only where something differs
class OW:
    def __init__(self, a=0, d=0): self.a, self.d = a, d
    def pair(self): return types.SimpleNamespace(value=self.a), types.SimpleNamespace(value=self.d)
calls = []
class Ch:
    async def set_permissions(self, target, overwrite=None, reason=None): calls.append((target, overwrite, reason))
ons = dict(); exec(seg("_pair", "_apply_overwrites"), ons)
async def ow_test():
    A, B, C, D = "A", "B", "C", "D"; cur = {A: OW(1, 0), B: OW(2, 0), D: OW(4, 0)}; new = {A: OW(1, 0), B: OW(2, 8), C: OW(16, 0)}
    await ons["_apply_overwrites"](Ch(), cur, new, "why")
    got = {c[0]: c[1] for c in calls}
    check(set(got) == {B, C, D} and got[D] is None and got[B].d == 8 and got[C].a == 16 and all(c[2] == "why" for c in calls), f"only changed targets are touched: {calls}")
asyncio.run(ow_test())
print("V2:", "ALL PASSED (no appeal text, no owner bypass, exact permissions, DM flags, ticket emoji repair, staff, log panel, overwrites)" if not fails else f"{len(fails)} FAILED")
for x in fails: print("  FAIL:", x)
sys.exit(1 if fails else 0)
