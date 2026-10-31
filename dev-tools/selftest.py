import ast, asyncio, contextvars, re, string, sys, types, collections
SRC = open(__import__("os").environ.get("BOT_SRC", "/mnt/user-data/outputs/bot.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
def seg(*names):
    out = []
    for n in TREE.body:
        nm = getattr(n, "name", None)
        if nm is None and isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name): nm = n.targets[0].id
        if nm in names: out.append(ast.get_source_segment(SRC, n))
    assert len(out) == len(names), f"missing: {set(names) - {getattr(n, 'name', None) for n in TREE.body}}"
    return "\n\n".join(out)

# ---------------- fake discord ----------------
NAMES = ["view_channel", "send_messages", "add_reactions", "create_public_threads", "create_private_threads", "send_messages_in_threads",
         "use_application_commands", "embed_links", "attach_files", "send_polls", "send_voice_messages", "administrator", "ban_members", "manage_messages"]
class Permissions:
    VALID_FLAGS = {n: 1 << i for i, n in enumerate(NAMES)}
    def __init__(self, value=0): self.value = value
class PermissionOverwrite:
    def __init__(self): object.__setattr__(self, "_v", {})
    def __getattr__(self, n):
        if n in Permissions.VALID_FLAGS: return self._v.get(n)
        raise AttributeError(n)
    def __setattr__(self, n, v):
        if n not in Permissions.VALID_FLAGS: raise ValueError(f"no permission called {n}")
        self._v.pop(n, None) if v is None else self._v.__setitem__(n, v)
    def pair(self):
        a = sum(Permissions.VALID_FLAGS[n] for n, v in self._v.items() if v is True); d = sum(Permissions.VALID_FLAGS[n] for n, v in self._v.items() if v is False)
        return Permissions(a), Permissions(d)
    @classmethod
    def from_pair(cls, allow, deny):
        o = cls()
        for n, bit in Permissions.VALID_FLAGS.items():
            if allow.value & bit: o._v[n] = True
            elif deny.value & bit: o._v[n] = False
        return o
    def is_empty(self): return not self._v
class Member:
    def __init__(self, mid, admin=False, guild=None):
        self.id, self.guild, self.sent = mid, guild, []
        self.guild_permissions = types.SimpleNamespace(administrator=admin)
    async def send(self, **kw): self.sent.append(kw)
    def __str__(self): return f"user{self.id}"
    mention = property(lambda s: f"<@{s.id}>")
class Role:
    def __init__(self, rid, guild): self.id, self.guild = rid, guild
    def is_default(self): return self.id == self.guild.id
    def __eq__(self, o): return isinstance(o, Role) and o.id == self.id
    def __hash__(self): return hash(("r", self.id))
class Forbidden(Exception): pass
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw)
discord = types.SimpleNamespace(Permissions=Permissions, PermissionOverwrite=PermissionOverwrite, Member=Member, Role=Role, Forbidden=Forbidden, Embed=Embed,
                                AllowedMentions=types.SimpleNamespace(none=lambda: "none"))
class Guild:
    def __init__(self, gid=1000): self.id = gid; self.name = "TestGuild"; self.default_role = Role(gid, self); self.roles = {}; self.owner_id = 1; self.banned = []; self.me = Member(5); self.members = {5: self.me}
    def role(self, rid): self.roles[rid] = self.roles.get(rid) or Role(rid, self); return self.roles[rid]
    def get_role(self, rid): return self.default_role if rid == self.id else self.roles.get(rid)
    def get_member(self, mid): return self.members.get(mid)
    async def ban(self, member, **kw): self.banned.append((member, kw))
class Chan:
    def __init__(self, guild, ows=None, cid=50): self.guild, self.id, self.edits = guild, cid, 0; self._ow = {t: (o.pair()[0].value, o.pair()[1].value) for t, o in (ows or {}).items()}
    @property
    def overwrites(self): return {t: PermissionOverwrite.from_pair(Permissions(a), Permissions(d)) for t, (a, d) in self._ow.items()}
    async def edit(self, overwrites=None, reason=None):
        self._ow = {t: (o.pair()[0].value, o.pair()[1].value) for t, o in overwrites.items()}; self.edits += 1
    async def set_permissions(self, target, overwrite=None, reason=None):
        self.edits += 1
        if overwrite is None: self._ow.pop(target, None)
        else: self._ow[target] = (overwrite.pair()[0].value, overwrite.pair()[1].value)
def ow(**kw):
    o = PermissionOverwrite()
    for k, v in kw.items(): setattr(o, k, v)
    return o
def snap(ch): return {t.id: v for t, v in ch._ow.items()}
fails = []
def check(cond, msg):
    if not cond: fails.append(msg)

# ---------------- 1) lock / unlock ----------------
SETTINGS = {}
ns = dict(discord=discord, get_settings=lambda gid: SETTINGS.setdefault(gid, {}), save_settings=lambda: None)
exec(seg("_LOCK_PERMS", "_lock_perm_names", "_ow_copy", "_pair", "_held", "_apply_overwrites", "lock_channel", "unlock_channel", "hide_channel", "unhide_channel"), ns)
async def lock_tests():
    g = Guild(); staff, members = g.role(11), g.role(12)
    # A: no overwrites at all
    ch = Chan(g); await ns["lock_channel"](ch, []); e = ch.overwrites[g.default_role]
    check(ch.edits == 1, "lock must be ONE api call")
    check(all(getattr(e, p) is False for p in ns["_lock_perm_names"]()), "@everyone must be denied every message permission")
    check(e.view_channel is None, "lock must never touch view_channel")
    await ns["unlock_channel"](ch); check(ch._ow == {}, "unlock must restore an empty overwrite list")
    # B: private channel with an explicit allow for Members; staff may keep writing
    ch = Chan(g, {g.default_role: ow(view_channel=False), members: ow(send_messages=True)}); before = snap(ch)
    await ns["lock_channel"](ch, [staff])
    now = ch.overwrites
    check(now[g.default_role].view_channel is False and now[g.default_role].send_messages is False, "@everyone keeps view=False and gets send=False")
    check(now[members].send_messages is True, "other roles' own overwrites are not touched")
    check(now[staff].send_messages is True and now[staff].add_reactions is True and now[staff].use_application_commands is True, "chosen role may write")
    await ns["unlock_channel"](ch); check(snap(ch) == before, f"unlock must restore the exact original: {snap(ch)} != {before}")
    # C: locking twice (different roles) must not lose the original snapshot
    ch = Chan(g, {g.default_role: ow(send_messages=True)}); before = snap(ch)
    await ns["lock_channel"](ch, [staff]); await ns["lock_channel"](ch, [members]); await ns["unlock_channel"](ch)
    check(snap(ch) == before, "double lock + unlock must restore the original")
    # D: channel locked by an old version has no snapshot -> only @everyone's message limits are cleared
    ch = Chan(g, {g.default_role: ow(view_channel=True, send_messages=False, add_reactions=False)}); SETTINGS[g.id] = {}
    await ns["unlock_channel"](ch); e = ch.overwrites[g.default_role]
    check(e.send_messages is None and e.add_reactions is None and e.view_channel is True, "legacy unlock clears only message perms")
asyncio.run(lock_tests())

# ---------------- 2b) lockdown, mass lock ----------------
from datetime import datetime, timezone
class PChan(Chan):
    """A channel that also knows what each target may do (permissions_for), like a real one."""
    def __init__(self, guild, ows=None, can=None, cid=50):
        super().__init__(guild, ows, cid); self.can = can or {}
    def permissions_for(self, target):
        have = self.can.get(target, set(NAMES))
        return types.SimpleNamespace(**{n: n in have for n in NAMES})
    def overwrites_for(self, target): return self.overwrites.get(target, PermissionOverwrite())
class Cat(PChan): pass
discord.CategoryChannel = Cat

async def hide_tests():
    g = Guild(4000); staff, members, mods = g.role(11), g.role(12), g.role(13)
    inv = Member(77); g.members[77] = inv; me_ = g.me
    ch = PChan(g, {g.default_role: ow(send_messages=True), members: ow(send_messages=True, attach_files=False)}, cid=61); before = snap(ch)
    await ns["hide_channel"](ch, [members], [staff], [inv]); now = ch.overwrites
    check(ch.edits >= 3, "lockdown changes each target with the per-target permission endpoint (needs just Manage Roles)")
    check(now[g.default_role].view_channel is False and now[g.default_role].send_messages is True, "@everyone loses view only")
    check(now[members].view_channel is True and now[members].send_messages is False and now[members].attach_files is False, "see-only role: may look, may not write")
    check(now[staff].view_channel is True and now[staff].send_messages is True and now[staff].add_reactions is True, "write role keeps view + write")
    check(now[inv].view_channel is True and now[inv].send_messages is True, "the person who started it keeps access")
    check(now[me_].view_channel is True, "the bot keeps viewing")
    check(await ns["unhide_channel"](ch) is True and snap(ch) == before, f"unhide must restore the exact original: {snap(ch)} != {before}")
    # nobody gains access they did not have (private staff channels stay private)
    ch = PChan(g, {g.default_role: ow(view_channel=False)}, can={staff: {"send_messages"}, inv: {"view_channel", "send_messages"}}, cid=62); before = snap(ch)
    await ns["hide_channel"](ch, [members], [staff], [inv]); now = ch.overwrites
    check(staff not in now, "a role that could not even SEE this channel must not gain access")
    check(now[inv].view_channel is True and now[inv].send_messages is True and now[inv].create_private_threads is None and now[inv].add_reactions is None, "the starter only keeps permissions they really had")
    await ns["unhide_channel"](ch); check(snap(ch) == before, "restore after the escalation guard")
    ch = PChan(g, {g.default_role: ow(send_messages=True)}, cid=63); before = snap(ch)
    await ns["hide_channel"](ch, [], [staff], [inv]); await ns["hide_channel"](ch, [members], [mods], [inv]); await ns["unhide_channel"](ch)
    check(snap(ch) == before, "double lockdown + unlockdown must restore the original")
    ch = PChan(g, cid=64); check(await ns["unhide_channel"](ch) is False and ch.edits == 0, "unhide without a snapshot does nothing")
    ch = PChan(g, {g.default_role: ow(send_messages=True)}, cid=65); before = snap(ch)       # layers undone newest-first restore exactly
    await ns["lock_channel"](ch, [staff], [inv]); await ns["hide_channel"](ch, [], [staff], [inv])
    await ns["unhide_channel"](ch); await ns["unlock_channel"](ch); check(snap(ch) == before, "lock -> lockdown -> unlockdown -> unlock must restore the original")
    ch = PChan(g, {g.default_role: ow(send_messages=True)}, cid=66); before = snap(ch)
    await ns["hide_channel"](ch, [], [staff], [inv]); await ns["lock_channel"](ch, [staff], [inv])
    await ns["unlock_channel"](ch); e = ch.overwrites[g.default_role]
    check(e.view_channel is False and e.send_messages is True, "unlocking while the lockdown is on must keep the lockdown")
    await ns["unhide_channel"](ch); check(snap(ch) == before, "lockdown -> lock -> unlock -> unlockdown must restore the original")
    ch = PChan(g, {g.default_role: ow(send_messages=True)}, can={staff: {"send_messages", "add_reactions"}}, cid=67)         # lock never hands out NEW write rights
    await ns["lock_channel"](ch, [staff, mods]); now = ch.overwrites
    check(now[staff].send_messages is True and now[staff].add_reactions is True and now[staff].attach_files is None, "a locked channel's 'may still write' role keeps only what it had")
asyncio.run(hide_tests())

mlogs = []
async def fake_sleep(s): pass
async def fake_send_log(guild, embed): mlogs.append(embed.description)
MSET = {}
mns = dict(discord=discord, get_settings=lambda gid: MSET.setdefault(gid, {}), save_settings=lambda: None, asyncio=types.SimpleNamespace(sleep=fake_sleep),
           L=lambda t, *a: t.format(*a) if a else t, send_log=fake_send_log, datetime=datetime, timezone=timezone)
exec(seg("_mass_busy", "_MASS_KEYS", "_mass_active_order", "_LOCK_PERMS", "_lock_perm_names", "_ow_copy", "_pair", "_held", "_apply_overwrites", "lock_channel", "unlock_channel",
         "hide_channel", "unhide_channel", "can_mass_lock", "_mass_guard", "run_mass_lock", "run_mass_unlock"), mns)
def mguild(gid, n_text=3):
    g = Guild(gid); inv = Member(77); g.members[77] = inv; g.inv = inv
    inv.guild_permissions = types.SimpleNamespace(administrator=False, manage_guild=True)
    g.me.guild_permissions = types.SimpleNamespace(administrator=False, manage_channels=True, manage_roles=True)
    g.categories = [Cat(g, cid=gid * 100 + 1), Cat(g, cid=gid * 100 + 2)]
    g.text_channels = [PChan(g, {g.default_role: ow(send_messages=True)}, cid=gid * 100 + 10 + i) for i in range(n_text)]
    g.forums = [PChan(g, cid=gid * 100 + 50)]; g.voice = PChan(g, cid=gid * 100 + 60)
    g.channels = g.categories + g.text_channels + [g.voice] + g.forums
    g.get_channel = lambda cid, g=g: next((c for c in g.channels if c.id == cid), None)
    return g
async def mass_tests():
    reports = []
    async def report(t): reports.append(t)
    mb = mns["_mass_busy"]
    g = mguild(5000); staff = g.role(11); inv = g.inv; orig = {c.id: snap(c) for c in g.channels}
    await mns["run_mass_lock"](g, "lockall", [staff], [], inv, report)
    check(all(c.overwrites[g.default_role].send_messages is False for c in g.text_channels + g.forums), "lockall locks every text channel and forum")
    check(g.voice.edits == 0 and all(c.edits == 0 for c in g.categories), "lockall must not touch voice channels or categories")
    check(reports[-1] == "🔒 Locked **4** channels. Failed: **0**." and not mb and len(mlogs) == 1, f"lockall summary: {reports[-1]!r} busy={mb}")
    await mns["run_mass_unlock"](g, "lockall", report, inv)
    check({c.id: snap(c) for c in g.channels} == orig and reports[-1] == "🔓 Unlocked **4** channels. Failed: **0**.", f"unlockall restores everything: {reports[-1]!r}")
    await mns["run_mass_unlock"](g, "lockall", report, inv); check(reports[-1] == "ℹ️ No locked channels found.", f"nothing to unlock: {reports[-1]!r}")
    async def boom(target=None, overwrite=None, reason=None): raise Forbidden()
    g.text_channels[1].set_permissions = boom
    await mns["run_mass_lock"](g, "lockall", [], [], inv, report)
    check(reports[-1] == "🔒 Locked **3** channels. Failed: **1**." and not mb, f"one failing channel must not stop the rest: {reports[-1]!r} busy={mb}")
    del g.text_channels[1].set_permissions
    await mns["run_mass_unlock"](g, "lockall", report, inv); check({c.id: snap(c) for c in g.channels} == orig, "unlock after a partial failure still restores everything")
    g = mguild(5100, n_text=20); before_n = len(reports)
    await mns["run_mass_lock"](g, "lockall", [], [], g.inv, report)
    prog = [r for r in reports[before_n:] if r.startswith("⏳ Working...")]
    check(prog == ["⏳ Working... 8/21 channels", "⏳ Working... 16/21 channels"], f"progress reports: {prog}")
    # lockdown hides channels AND categories; layers must be undone newest-first
    g = mguild(5200); staff, members = g.role(11), g.role(12); inv = g.inv; orig = {c.id: snap(c) for c in g.channels}
    await mns["run_mass_lock"](g, "lockdown", [staff], [members], inv, report)
    check(all(c.overwrites[g.default_role].view_channel is False for c in g.channels), "lockdown hides every channel and category")
    check(reports[-1].startswith("🌑 Lockdown is on: hidden **7** channels/categories. Failed: **0**."), f"lockdown summary: {reports[-1]!r}")
    await mns["run_mass_lock"](g, "lockall", [staff], [], inv, report)
    await mns["run_mass_unlock"](g, "lockdown", report, inv)
    check(reports[-1] == "⚠️ Lift **lockall** first - it was started after this one." and all(c.overwrites[g.default_role].view_channel is False for c in g.channels), f"wrong undo order must be refused: {reports[-1]!r}")
    await mns["run_mass_unlock"](g, "lockall", report, inv); await mns["run_mass_unlock"](g, "lockdown", report, inv)
    check({c.id: snap(c) for c in g.channels} == orig, "undoing newest-first restores every channel exactly")
    await mns["run_mass_unlock"](g, "lockdown", report, inv); check(reports[-1] == "ℹ️ There is no active lockdown.", f"no lockdown: {reports[-1]!r}")
    g = mguild(5300); await mns["run_mass_lock"](g, "lockdown", [], [], g.inv, report)
    g.channels.remove(g.text_channels[0])
    await mns["run_mass_unlock"](g, "lockdown", report, g.inv)
    check(reports[-1].startswith("🌤️ Lockdown lifted: restored **6**") and not MSET[g.id].get("hide_snapshots"), f"deleted channels are skipped and their snapshots dropped: {reports[-1]!r}")
    # who may start it
    said = []
    async def say(t): said.append(t)
    plain = Member(88); plain.guild_permissions = types.SimpleNamespace(administrator=False, manage_guild=False)
    admin = Member(89); admin.guild_permissions = types.SimpleNamespace(administrator=True, manage_guild=False)
    check(mns["can_mass_lock"](g.inv) and mns["can_mass_lock"](admin) and not mns["can_mass_lock"](plain), "only Manage Server / Administrator may use the mass commands")
    check(await mns["_mass_guard"](g, plain, say) is False and said[-1] == "❌ This needs the **Manage Server** permission!", f"guard without permission: {said}")
    check(await mns["_mass_guard"](g, g.inv, say) is True, "a Manage Server holder passes")
    g.me.guild_permissions = types.SimpleNamespace(administrator=False, manage_channels=True, manage_roles=False)
    check(await mns["_mass_guard"](g, g.inv, say) is False and "Manage Roles" in said[-1], "the bot needs its own permissions first")
    g.me.guild_permissions = types.SimpleNamespace(administrator=True, manage_channels=False, manage_roles=False)
    check(await mns["_mass_guard"](g, g.inv, say) is True, "an Administrator bot passes")
    mb.add(g.id); check(await mns["_mass_guard"](g, g.inv, say) is False and "already running" in said[-1], "two mass operations may not run at once"); mb.discard(g.id)
asyncio.run(mass_tests())

_L = lambda t, *a: t.format(*a) if a else t
# ---------------- 3) honeypot ----------------
logs, cases = [], []
async def fake_case(*a, **k): cases.append(a)
async def fake_log(*a, **k): logs.append(a)
hdel = []
async def fake_silent2(m): hdel.append(m); return True
g2 = Guild(2000)
hns = dict(L=_L, discord=discord, get_settings=lambda gid: {"honeypot": "60"}, BOT_CREATOR_ID=999, silent_delete=fake_silent2, post_case_log=fake_case,
           next_case_s=lambda s: 1, send_log=fake_log)
async def _hp_send_dm(user, **kw):
    return False                       # DM policy: the honeypot DM is only sent when the server switched 'Moderation DMs' on
hns["send_dm"] = _hp_send_dm
exec(seg("handle_honeypot"), hns)
class HMsg:
    def __init__(self, author, ch=60): 
        self.guild, self.author, self.content = g2, author, "buy cheap nitro"
        async def send(*a, **k): pass
        self.channel = types.SimpleNamespace(id=ch, send=send)
async def honeypot_tests():
    victim = Member(42, guild=g2); admin = Member(43, admin=True, guild=g2); creator = Member(999, guild=g2)
    check(await hns["handle_honeypot"](HMsg(victim, ch=61)) is False, "honeypot ignores other channels")
    check(await hns["handle_honeypot"](HMsg(victim)) is True, "honeypot handles its channel")
    check(len(g2.banned) == 1 and g2.banned[0][0] is victim and g2.banned[0][1].get("delete_message_seconds") == 604800, "victim banned + 7 days of messages deleted")
    check(len(victim.sent) == 0 and len(cases) == 1 and len(hdel) == 1, "victim NOT DM'd by default, case logged, trigger message deleted")
    n = len(g2.banned)
    await hns["handle_honeypot"](HMsg(admin)); await hns["handle_honeypot"](HMsg(creator))
    check(len(g2.banned) == n, "admins and the bot owner are exempt")
    async def forbid(member, **kw): raise Forbidden()
    g2.ban = forbid; other = Member(44, guild=g2)
    check(await hns["handle_honeypot"](HMsg(other)) is True and len(logs) == 1, "ban failure is reported to the log channel instead of crashing")
asyncio.run(honeypot_tests())

# ---------------- 4) language layer ----------------
SETTINGS_DB = {"1": {"language": "tr"}, "2": {"language": "ru"}, "3": {"language": "xx"}}
lns = dict(contextvars=contextvars, settings_db=SETTINGS_DB)
exec(seg("_LANG", "set_lang", "PHRASES", "_load_phrases", "L", "_PHRASE_TABLE"), lns); lns["_load_phrases"](lns["_PHRASE_TABLE"])
L, set_lang, P = lns["L"], lns["set_lang"], lns["PHRASES"]
def fields(s): return [f[2] or "" for f in string.Formatter().parse(s) if f[1] is not None]
def sample(spec): return 7 if "d" in spec else 12345 if "," in spec else 2.5 if "g" in spec else "X"
same = []
for lang, gid in (("tr", 1), ("ru", 2)):
    set_lang(gid)
    for en in P[lang]:
        args = [sample(sp) for sp in fields(en)]
        try: out = L(en, *args)
        except Exception as e: fails.append(f"L crashed for {lang}: {en[:40]!r}: {e}"); continue
        if "{" in out or "}" in out: fails.append(f"{lang}: unformatted braces in {out[:50]!r}")
        if out == L.__globals__["_LANG"].get() and False: pass
        if len(re.findall(r"[A-Za-z]", en)) >= 3 and out == en.format(*args): same.append((lang, en[:30]))
set_lang(3); check(L("❌ Usage: `{}`", ".ban") == "❌ Usage: `.ban`", "unknown language falls back to English")
set_lang(None); check(L("Reason") == "Reason", "DMs use English")
set_lang(1); check(L("Reason") == "Sebep" and L("Never translated phrase") == "Never translated phrase", "translation + fallback")
check(len(P["tr"]) == len(P["ru"]) and len(P["tr"]) > 280, "TR and RU tables must have the same size")
print(f"language layer: {len(P['tr'])} phrases x 2 languages formatted without errors; identical-to-English: {len(same)} {same[:6]}")

# ---------------- 5) helpers ----------------
dns = dict(re=re, L=L, discord=discord)
exec(seg("parse_duration"), dns)
set_lang(1); s, lab = dns["parse_duration"]("5m"); check((s, lab) == (300, "5 dakika"), f"parse_duration tr: {(s, lab)}")
set_lang(2); check(dns["parse_duration"]("2h") == (7200, "2 ч."), "parse_duration ru")
check(dns["parse_duration"]("abc")[0] is None and not dns["parse_duration"]("0m")[0] and dns["parse_duration"]("1w")[0] == 604800, "parse_duration edge cases")
ens = {}
exec(seg("emoji_key", "emoji_from_key"), ens)
class UEmoji:
    name, id = "👍", None
    def __str__(self): return "👍"
custom = types.SimpleNamespace(name="pepe", id=123)
check(ens["emoji_key"](custom) == "pepe:123" and ens["emoji_key"](UEmoji()) == "👍" and ens["emoji_from_key"]("pepe:123") == "<:pepe:123>" and ens["emoji_from_key"]("👍") == "👍", "emoji key round-trip")
rns = dict(_DANGEROUS_PERMS=None)
exec(seg("_DANGEROUS_PERMS", "role_is_dangerous"), rns)
mk = lambda **k: types.SimpleNamespace(permissions=types.SimpleNamespace(**k))
check(rns["role_is_dangerous"](mk(ban_members=True)) and rns["role_is_dangerous"](mk(administrator=True)) and not rns["role_is_dangerous"](mk(send_messages=True)), "dangerous-role detection")

print("\nSELF-TEST:", "ALL PASSED" if not fails else f"{len(fails)} FAILED")
for f in fails: print("  FAIL:", f)
sys.exit(1 if fails else 0)
