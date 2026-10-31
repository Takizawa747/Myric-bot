import ast, asyncio, math, sys, types
from datetime import datetime, timezone
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
class VoiceChannel: pass
class StageChannel: pass
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw); self.fields = []
    def add_field(self, name=None, value=None, inline=True): self.fields.append((name, value)); return self
discord = types.SimpleNamespace(VoiceChannel=VoiceChannel, StageChannel=StageChannel, Embed=Embed)
class Clock:
    t = 1000.0
    def monotonic(self): return self.t
clock = Clock(); sent_msgs, role_log = [], []
class Chan(VoiceChannel):
    def __init__(self, guild, cid): self.guild, self.id, self.members, self.name = guild, cid, [], f"vc{cid}"
    async def send(self, **kw): sent_msgs.append(kw)
class StageCh(Chan, StageChannel): pass
class Member:
    def __init__(self, uid, bot=False):
        self.id, self.bot, self.timed_out, self.mention = uid, bot, False, f"<@{uid}>"
        self.voice = types.SimpleNamespace(channel=None, self_mute=False, self_deaf=False, mute=False, deaf=False, suppress=False, afk=False)
    def is_timed_out(self): return self.timed_out
    async def add_roles(self, role, reason=None): role_log.append((self.id, role.id))
class Guild:
    def __init__(self, gid=1): self.id, self.afk_channel, self.chans, self.mem = gid, None, {}, {}
    def get_channel(self, cid): return self.chans.get(cid)
    def get_member(self, uid): return self.mem.get(uid)
    def get_role(self, rid): return types.SimpleNamespace(id=rid) if rid == 500 else None
    voice_channels = property(lambda s: [c for c in s.chans.values() if isinstance(c, Chan) and not isinstance(c, StageCh)])
    stage_channels = property(lambda s: [c for c in s.chans.values() if isinstance(c, StageCh)])
g = Guild(1); ch10 = Chan(g, 10); g.chans[10] = ch10; g.chans[99] = Chan(g, 99)
def mk(uid, ch=None, bot=False, **flags):
    m = Member(uid, bot); g.mem[uid] = m
    for k, v in flags.items(): setattr(m.voice, k, v)
    if ch is not None: m.voice.channel = ch; ch.members.append(m)
    return m
settings_db = {"1": {"features": {"vcxp": "enabled"}, "vc_channels": ["10"]}}
RESTR, levels_db, afk_db = {}, {}, {}
def get_user_xp(gid, uid): return levels_db.setdefault(str(gid), {}).setdefault(str(uid), {"xp": 0, "level": 0})
ns = dict(discord=discord, _time=clock, settings_db=settings_db, DEFAULT_FEATURES={"vcxp": "disabled", "leveling": "enabled"}, bot_bans_db={"servers": []}, afk_db=afk_db,
          user_restricted=lambda uid, f: uid in RESTR.get(f, set()), get_user_xp=get_user_xp, get_level=lambda xp, gid=None: int(math.sqrt(max(0, xp) / 100)), levels_db=levels_db,
          t=lambda gid, key, *a: f"{key}:{a[0]}:{a[1]}", role_assignable=lambda gg, r: True, datetime=datetime, timezone=timezone, asyncio=asyncio,
          L=lambda s, *a: s.format(*a) if a else s, get_settings=lambda gid: settings_db.setdefault(str(gid), {}), save_settings=lambda: None,
          bot=types.SimpleNamespace(guilds=[g], get_guild=lambda gid: g if gid == 1 else None, get_channel=lambda cid: g.chans.get(cid)))
exec(seg("VC_MIN_PEOPLE", "VC_TICK", "VC_MAX_GAP", "VC_DAILY_MINUTES", "VC_MAX_CHANNELS", "VC_DIFFICULTIES", "_vc_state", "_vc_credit", "vc_config", "vc_channel_ids", "_feature_on",
         "vc_enabled_for", "vc_eligible", "vc_settle", "vc_on_voice_state", "vc_today", "vc_grant", "vc_level_up", "vc_award_all", "vc_xp_tick", "vc_valid_channel",
         "vc_all_voice_ids", "vc_add_channels", "vc_remove_channels", "vc_panel_embed", "vc_info_embed"), ns)
settle, credit = ns["vc_settle"], lambda uid: ns["_vc_credit"].get((1, uid), [0.0])[0]
def fresh():
    ns["_vc_state"].clear(); ns["_vc_credit"].clear(); ch10.members.clear(); levels_db.clear(); g.mem.clear(); g.afk_channel = None
    settings_db["1"] = {"features": {"vcxp": "enabled"}, "vc_channels": ["10"]}; RESTR.clear(); afk_db.clear(); ns["bot_bans_db"]["servers"].clear()

# ---- difficulty presets
rates = [v["rate"] for v in ns["VC_DIFFICULTIES"].values()]
check(rates == sorted(rates, reverse=True) and len(set(rates)) == len(rates), f"harder presets must pay strictly less: {rates}")
check(all(ns["vc_config"](1)["cap"] == 0 or True for _ in [0]) and ns["vc_config"](1) == {"label": "⚪ Normal", "rate": 7, "cap": 1680}, f"normal preset: {ns['vc_config'](1)}")
settings_db["1"]["vcxpdiff"] = "hardest"; check(ns["vc_config"](1)["rate"] == 2 and ns["vc_config"](1)["cap"] == 480, "hardest preset and its 4h cap")
settings_db["1"]["vcxpdiff"] = "bogus"; check(ns["vc_config"](1)["rate"] == 7, "an unknown preset falls back to normal"); check(ns["vc_config"](999)["rate"] == 7, "unknown server")

# ---- who is eligible: every way of being muted / deafened / away must block XP
fresh(); el = ns["vc_eligible"]
check(el(mk(1, ch10)), "baseline: mic and headphones on")
for flag in ("self_mute", "self_deaf", "mute", "deaf", "suppress", "afk"): check(not el(mk(2, ch10, **{flag: True})), f"{flag} must block XP")
m = mk(3, ch10); m.timed_out = True; check(not el(m), "timed-out members earn nothing")
check(not el(mk(4, ch10, bot=True)), "bots earn nothing")
afk_db[5] = {"reason": "x"}; check(not el(mk(5, ch10)), "the bot's own .afk status blocks XP")
RESTR["leveling"] = {6}; check(not el(mk(6, ch10)), "restricted from leveling"); RESTR["vcxp"] = {7}; check(not el(mk(7, ch10)), "restricted from voice XP")
check(not el(mk(8, None)), "not in a voice channel"); m = mk(9, ch10); m.voice = None; check(not el(m), "no voice state at all")

# ---- time accounting: seconds are integrated between events, so mute-dodging does not work
fresh(); A, B = mk(1, ch10), mk(2, ch10)
settle(ch10, 0); settle(ch10, 30); check(credit(1) == 30 and credit(2) == 30, f"two eligible people together: {credit(1)}, {credit(2)}")
B.voice.self_mute = True; settle(ch10, 60)                                   # B muted at t=60: the interval 30..60 still counted (B was on)
check(credit(1) == 60 and credit(2) == 60, "the time before a mute is credited")
settle(ch10, 90); check(credit(1) == 60 and credit(2) == 60, "alone (the other one is muted): nothing")
B.voice.self_mute = False; settle(ch10, 100); settle(ch10, 130)
check(credit(1) == 90 and credit(2) == 60 + 30, f"after un-muting both earn again: {credit(1)}, {credit(2)}")
settle(ch10, 130 + 91); check(credit(1) == 90, "a gap longer than 90 s is never credited")
settle(ch10, 130 + 91 + 90); check(credit(1) == 180, "exactly 90 s is credited")
fresh(); a = mk(1, ch10); settle(ch10, 0); settle(ch10, 50); check(credit(1) == 0, "one person alone earns nothing")
fresh(); a, b, c3 = mk(1, ch10), mk(2, ch10, self_deaf=True), mk(3, ch10, mute=True); settle(ch10, 0); settle(ch10, 40); check(credit(1) == 0 and credit(2) == 0, "one eligible + two muted/deafened = nothing")
fresh(); st = StageCh(g, 11); g.chans[11] = st; settings_db["1"]["vc_channels"] = ["10", "11"]
a, b = mk(1, st, suppress=True), mk(2, st, suppress=True); settle(st, 0); settle(st, 40); check(credit(1) == 0, "stage listeners earn nothing")
b.voice.suppress = False; settle(st, 50); a.voice.suppress = False; settle(st, 60); settle(st, 90); check(credit(1) == 30 and credit(2) == 30, "stage speakers earn")
# ---- switched-off situations drop the state and give nothing
for label, mutate in (("feature off", lambda: settings_db["1"]["features"].update(vcxp="disabled")), ("leveling off", lambda: settings_db["1"]["features"].update(leveling="disabled")),
                      ("channel not chosen", lambda: settings_db["1"].update(vc_channels=["11"])), ("AFK channel", lambda: setattr(g, "afk_channel", ch10)),
                      ("banned server", lambda: ns["bot_bans_db"]["servers"].append("1"))):
    fresh(); mk(1, ch10); mk(2, ch10); settle(ch10, 0); mutate(); settle(ch10, 30)
    check(credit(1) == 0 and 10 not in ns["_vc_state"], f"{label}: no credit and the state is dropped")

# ---- the instant reaction to state changes
fresh(); calls = []; real = ns["vc_settle"]; ns["vc_settle"] = lambda ch, now=None: calls.append(ch.id)
ch11 = Chan(g, 11); h = ns["vc_on_voice_state"]; mem = mk(1)
h(mem, types.SimpleNamespace(channel=ch10), types.SimpleNamespace(channel=ch11)); check(calls == [10, 11], f"moving settles both channels: {calls}")
calls.clear(); h(mem, types.SimpleNamespace(channel=ch10), types.SimpleNamespace(channel=ch10)); check(calls == [10], "a mute toggle settles the channel once")
calls.clear(); h(mem, types.SimpleNamespace(channel=None), types.SimpleNamespace(channel=ch10)); check(calls == [10], "joining")
calls.clear(); h(mk(2, bot=True), types.SimpleNamespace(channel=ch10), types.SimpleNamespace(channel=ch10)); check(calls == [], "bots are ignored"); ns["vc_settle"] = real

# ---- XP, daily limit, level-up
fresh(); gr = ns["vc_grant"]
check(gr(1, 1, 2) == (14, 0, 0) and levels_db["1"]["1"]["xp"] == 14 and levels_db["1"]["1"]["vc_xp"] == 14, f"2 minutes at 7 XP: {levels_db}")
levels_db["1"]["1"]["vc_xp"] = 1670; r = gr(1, 1, 10); check(r[0] == 10 and levels_db["1"]["1"]["vc_xp"] == 1680, f"only the room left under the cap is paid: {r}")
check(gr(1, 1, 5)[0] == 0 and levels_db["1"]["1"]["xp"] == 14 + 10, "nothing more after the daily limit")
levels_db["1"]["1"]["vc_day"] = "1999-01-01"; r = gr(1, 1, 1); check(r[0] == 7 and levels_db["1"]["1"]["vc_xp"] == 7, "a new day starts a fresh limit")
levels_db["1"]["2"] = {"xp": 95, "level": 0}; r = gr(1, 2, 1); check(r == (7, 0, 1) and levels_db["1"]["2"]["level"] == 1, f"level-up is detected: {r}")
settings_db["1"].update(levelup="99", levelroles={"1": "500"}); sent_msgs.clear(); role_log.clear()
asyncio.run(ns["vc_level_up"](g, mk(2), 1)); check(len(sent_msgs) == 1 and role_log == [(2, 500)], f"announcement + level role: {sent_msgs} {role_log}")

# ---- the whole loop: ticks -> credits -> XP, stale data cleaned
fresh(); mk(1, ch10); mk(2, ch10); ns["_vc_state"][777] = (0, frozenset()); tick = lambda t: (setattr(clock, "t", t), asyncio.run(ns["vc_xp_tick"]()))
tick(1000); tick(1030); check(levels_db == {} and credit(1) == 30, f"30 s is not a minute yet: {levels_db} {credit(1)}")
tick(1090); check(levels_db["1"]["1"]["xp"] == 7 and levels_db["1"]["2"]["xp"] == 7 and abs(credit(1) - 30) < 1e-6, f"one minute paid, 30 s carried over: {levels_db}")
check(777 not in ns["_vc_state"], "state of an unknown channel is dropped")
ns["_vc_credit"][(1, 55)] = [10.0, clock.t - 4000]; ns["_vc_credit"][(1, 56)] = [120.0, clock.t]; asyncio.run(ns["vc_award_all"]())
check((1, 55) not in ns["_vc_credit"], "old leftovers are pruned"); check(ns["_vc_credit"][(1, 56)][0] == 0 and "56" not in levels_db["1"], "credit of someone who left the server is dropped, no XP")
mk(1, ch10).voice.self_mute = True; asyncio.run(ns["vc_xp_tick"]())
# ---- channel list helpers
fresh(); g.chans[12] = types.SimpleNamespace(id=12); g.chans[13] = Chan(g, 13); st = StageCh(g, 14); g.chans[14] = st; g.afk_channel = g.chans[13]
check(sorted(ns["vc_all_voice_ids"](g)) == [10, 11, 14, 99], f"'all voice channels' = voice + stage, without the AFK channel (13): {ns['vc_all_voice_ids'](g)}")
settings_db["1"].pop("vc_channels")
check(ns["vc_add_channels"](g, [10, 14, 12, 4242, 10]) == 2 and settings_db["1"]["vc_channels"] == ["10", "14"], f"only real voice/stage channels, no duplicates: {settings_db['1']['vc_channels']}")
check(ns["vc_channel_ids"](1) == [10, 14], "ids come back as integers"); check(ns["vc_remove_channels"](g, [10, 777]) == 1 and settings_db["1"]["vc_channels"] == ["14"], "remove")
ns["VC_MAX_CHANNELS"] = 2; settings_db["1"]["vc_channels"] = []; check(ns["vc_add_channels"](g, [10, 14, 99]) == 2, "the list is capped"); ns["VC_MAX_CHANNELS"] = 100
check(ns["vc_remove_channels"](g, ns["vc_channel_ids"](1)) == 2 and ns["vc_channel_ids"](1) == [], "clear")
# ---- what members see
fresh(); ns["vc_info_embed"].__globals__  # noqa
levels_db["1"] = {"1": {"xp": 5, "level": 0, "vc_day": ns["vc_today"](), "vc_xp": 300}}; e = ns["vc_info_embed"](g, types.SimpleNamespace(id=1)); f = dict(e.fields)
check("never joins" in f["🔒 Privacy"] and "never hears or records" in f["🔒 Privacy"], "the privacy promise is shown")
check(f["📅 Your voice XP today"] == "**300** / 1,680" and f["📌 Status"] == "✅ On" and "<#10>" in f["🎙️ Voice XP Channels"], f"info fields: {f}")
check("microphone and headphones on" in e.description and "4" in e.description, "rules are shown")
levels_db["1"]["1"]["vc_day"] = "1999-01-01"; settings_db["1"]["vc_channels"] = []; settings_db["1"]["features"]["vcxp"] = "disabled"
f = dict(ns["vc_info_embed"](g, types.SimpleNamespace(id=1)).fields); check(f["📅 Your voice XP today"].startswith("**0**") and f["📌 Status"] == "❌ Off" and "/setup vc" in f["🎙️ Voice XP Channels"], f"off / empty state: {f}")
pe = ns["vc_panel_embed"](g); check("nobody earns" in pe.description and any("not active" in v for _, v in pe.fields), "the panel warns when the feature is off")
print("Voice XP:", "ALL PASSED (presets, eligibility, integrated time, 2-person rule, gaps, stage, switches, events, caps, level-up, loop, channel list, info)" if not fails else f"{len(fails)} FAILED")
for x in fails: print("  FAIL:", x)
sys.exit(1 if fails else 0)
