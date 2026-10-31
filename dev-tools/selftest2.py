import ast, asyncio, collections, random, re, sys, types, unicodedata
from datetime import datetime, timezone
SRC = open(__import__("os").environ.get("BOT_SRC", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "bot.py")), encoding="utf-8").read(); TREE = ast.parse(SRC)
def seg(*names):
    out = []
    for n in TREE.body:
        nm = getattr(n, "name", None)
        if nm is None and isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name): nm = n.targets[0].id
        if nm in names: out.append(ast.get_source_segment(SRC, n))
    assert len(out) == len(names), f"missing: {set(names)}"
    return "\n\n".join(out)
fails = []
def check(c, m):
    if not c: fails.append(m)
_L = lambda t, *a: t.format(*a) if a else t
class Embed:
    def __init__(self, **kw): self.__dict__.update(kw); self.fields = []; self.footer = None
    def add_field(self, name, value, inline=True): self.fields.append((name, value))
    def set_footer(self, text=None, icon_url=None): self.footer = text
    def set_image(self, url): self.image = url
    def set_thumbnail(self, url): self.thumb = url
disc = types.SimpleNamespace(Embed=Embed, Member=object)

# ---------- 1) slots: paytable maths ----------
sns = dict(random=random, collections=collections)
exec(seg("_RNG", "SLOT_SYMBOLS", "SLOT_JACKPOT", "slot_spin", "slots_paytable"), sns)
T = sns["SLOT_SYMBOLS"]; W = sum(s[1] for s in T)
check(W == 1000, f"slot weights must add up to 1000, are {W}")
rtp = sum((s[1] / W) ** 3 * s[3] + 3 * (s[1] / W) ** 2 * (1 - s[1] / W) * s[2] for s in T)
check(0.93 < rtp < 0.96, f"exact slots RTP out of range: {rtp:.4f}")
paying = sorted((s for s in T if s[3]), key=lambda s: s[3])
check(all(paying[i][1] > paying[i + 1][1] for i in range(len(paying) - 1)), "the more an emoji pays, the rarer it must be")
check(all(s[2] <= s[3] / 2 for s in T), "a pair must never pay more than half of the triple")
check(len({s[3] for s in paying}) == len(paying) and [s[3] for s in paying][-1] > 100, "every emoji has its own triple value, with a jackpot on top")
N, ret, any_pay, kinds = 300_000, 0.0, 0, collections.Counter()
for _ in range(N):
    reels, mult, kind = sns["slot_spin"](); ret += mult; any_pay += mult > 0; kinds[kind] += 1
    if kind == "jackpot" and reels[0] != "🎰": fails.append("only 🎰 can be the jackpot")
check(0.91 < ret / N < 0.98, f"simulated slots RTP {ret / N:.4f}")
check(0.20 < any_pay / N < 0.33, f"payout frequency {any_pay / N:.3f}")
check(0.008 < (kinds["triple"] + kinds["jackpot"]) / N < 0.025, "triples should show up about once in 70 spins")
# ---------- 2) coin flip ----------
rng = random.SystemRandom(); heads = sum(rng.getrandbits(1) == 0 for _ in range(400_000)) / 400_000
check(0.495 < heads < 0.505, f"coin flip not 50/50: {heads:.4f}")
check('_RNG.getrandbits(1) == 0' in seg("cf_p"), "cf_p must use the OS-entropy generator")
# ---------- 3) flags ----------
fns = dict(re=re, unicodedata=unicodedata)
exec(seg("_FLAG_DATA", "FLAGS", "FLAG_ANSWERS", "_norm_answer", "_load_flags"), fns); fns["_load_flags"]()
F, A, norm = fns["FLAGS"], fns["FLAG_ANSWERS"], fns["_norm_answer"]
check(len(F) >= 190 and len({c for c, _ in F}) == len(F) and all(re.fullmatch(r"[a-z]{2}", c) for c, _ in F), f"flag list problem ({len(F)} entries)")
check(all(norm(n) in A[c] for c, n in F), "every country's own name must be accepted")
check(norm("U.S.A") in A["us"] and norm("Côte d'Ivoire") in A["ci"] and norm("Türkiye") in A["tr"] and norm("  united  KINGDOM ") in A["gb"], "aliases / accents / case")
check(norm("germany") not in A["fr"] and norm("") not in A["fr"], "wrong answers must not match")
# ---------- 4) counting v2 ----------
deleted, reacts, said = [], [], []
async def fake_silent(m): deleted.append(m.content); return True
db = {}
cns = dict(L=_L, get_settings=lambda g: {"counting_channel": "50"}, is_feature_enabled=lambda g, f: True, counting_db=db, touch=lambda *a, **k: None, silent_delete=fake_silent)
cns["user_restricted"] = lambda *a: False
exec(seg("handle_counting", "handle_counting_edit"), cns)
class Msg:
    _id = 0
    def __init__(self, text, uid, ch=50):
        Msg._id += 1; self.id, self.content, self.guild = Msg._id, text, types.SimpleNamespace(id=7)
        self.author = types.SimpleNamespace(id=uid, mention=f"<@{uid}>")
        async def send(txt, **kw): said.append(txt)
        self.channel = types.SimpleNamespace(id=ch, send=send)
    async def add_reaction(self, e): reacts.append(e)
async def counting_tests():
    h = cns["handle_counting"]
    for text, uid in [("1", 1), ("2", 1), ("2", 2), ("3", 2), ("3", 1), ("5", 1), ("4", 3), ("hello", 2), ("5", 1)]:
        await h(Msg(text, uid))
    check(deleted == ["2", "3", "5", "hello"], f"deleted wrong messages: {deleted}")
    check(db["7"]["count"] == 5 and db["7"]["last_user"] == "1", f"state: {db['7']}")
    check(not reacts, f"no check-mark reaction must be added, got {reacts}")
    check(sum("Wait for someone else" in s for s in said) == 2 and sum("next number" in s for s in said) == 2, f"notices: {said}")
    check(await h(Msg("1", 9, ch=99)) is False, "other channels are ignored")
    db["7"] = {"count": 49, "last_user": "2"}; reacts.clear(); m50 = Msg("50", 1); await h(m50); await h(Msg("51", 2))
    check(reacts == ["⭐"], f"only milestones get a reaction: {reacts}")
    # editing the latest number must roll it back; editing an old one is ignored
    edit = cns["handle_counting_edit"]; old = Msg("51", 2); old.id = m50.id
    check(await edit(old, old) is False or db["7"]["count"] == 51, "edit of an old message")
    last_id = db["7"]["last_msg"]; cur = Msg("hax", 2); cur.id = last_id; deleted.clear()
    check(await edit(cur, cur) is True and db["7"]["count"] == 50 and db["7"]["last_user"] is None and deleted == ["hax"], f"edit rollback: {db['7']}")
asyncio.run(counting_tests())
# ---------- 5) poll rendering ----------
pns = dict(L=_L, discord=types.SimpleNamespace(Embed=Embed), POLL_EMOJIS=["1️⃣", "2️⃣", "3️⃣"])
exec(seg("poll_embed"), pns)
poll = {"q": "Best?", "opts": ["A", "B", "C"], "votes": {"1": 0, "2": 0, "3": 1}, "closed": False, "by": "9", "ends": 2_000_000_000}
e = pns["poll_embed"](poll)
check(e.title == "📊 Best?" and "67%" in e.description and "33%" in e.description and "███████░░░" in e.description and "🏆" not in e.description, f"open poll: {e.description!r}")
check(e.footer == "3 votes" and any(n == "Ends" for n, _ in e.fields), "footer / ends field")
poll["closed"] = True; e = pns["poll_embed"](poll)
check(e.title.startswith("🔒") and e.description.count("🏆") == 1 and "Closed" in e.footer and not any(n == "Ends" for n, _ in e.fields), "closed poll")
check(pns["poll_embed"]({"q": "x", "opts": ["A", "B"], "votes": {}, "closed": False, "by": "1"}).description.count("0%") == 2, "empty poll must not divide by zero")
# ---------- 6) rob ----------
clock, rnd = [1_000_000.0], {"p": 0.9, "n": 60}
fake_random = types.SimpleNamespace(random=lambda: rnd["p"], randint=lambda a, b: rnd["n"])
fake_time = types.SimpleNamespace(time=lambda: clock[0])
ECON, sent = {}, []
def get_econ(g, u): return ECON.setdefault(u, {"wallet": 0, "bank": 0, "inventory": []})
rns = dict(L=_L, t=lambda g, key, *a: (key, a), get_econ=get_econ, save_econ=lambda: None, discord=disc, random=fake_random, _time=fake_time)
exec(seg("ROB_COOLDOWN", "ROB_FINE_RATE", "_fmt_wait", "rob_p"), rns)
async def send(*a, **kw): sent.append(kw.get("embed").description if kw.get("embed") else a[0])
ctx = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), author=types.SimpleNamespace(id=10), send=send)
vic = types.SimpleNamespace(id=20, bot=False, display_name="Vic")
async def rob_tests():
    rob = rns["rob_p"]; ECON[10] = {"wallet": 1000, "bank": 0, "inventory": []}; ECON[20] = {"wallet": 500, "bank": 0, "inventory": []}
    rnd["p"] = 0.1; await rob(ctx, vic)                                    # caught -> 70% of the wallet
    check(ECON[10]["wallet"] == 300 and sent[-1] == ("rob_caught", ("700", "300")), f"caught: {ECON[10]} {sent[-1]}")
    await rob(ctx, vic); check("30m 0s" in str(sent[-1]), f"cooldown message: {sent[-1]}")
    clock[0] += 1799; await rob(ctx, vic); check("0m 1s" in str(sent[-1]) or "1s" in str(sent[-1]), f"still cooling down: {sent[-1]}")
    clock[0] += 2; rnd["p"] = 0.9; await rob(ctx, vic)                       # success
    check(ECON[10]["wallet"] == 360 and ECON[20]["wallet"] == 440, f"success: {ECON[10]} {ECON[20]}")
    clock[0] += 1801; ECON[20]["wallet"] = 50; before = ECON[10]["last_rob"]; await rob(ctx, vic)
    check(ECON[10]["last_rob"] == before, "a refused robbery (poor victim) must not use up the cooldown")
    await rob(ctx, types.SimpleNamespace(id=10, bot=False, display_name="me")); check("yourself" in str(sent[-1]), "self rob")
    await rob(ctx, types.SimpleNamespace(id=99, bot=True, display_name="bot")); check("bot" in str(sent[-1]), "bot rob")
asyncio.run(rob_tests())
# ---------- 7) joining a server: nobody is messaged and no invite is made; banned servers are left ----------
dms, invites_made = [], []
class Owner:
    async def send(self, **kw): dms.append(kw)
async def fetch_user(i): return Owner()
class Ch:
    async def send(self, *a, **k): dms.append(("channel", a, k))
    async def create_invite(self, **kw): invites_made.append(kw); return types.SimpleNamespace(url="https://discord.gg/testinvite")
class G:
    def __init__(self, feats, gid=1):
        self.features, self.name, self.id, self.member_count, self.owner_id = feats, "SecretClub", gid, 321, 77
        self.system_channel, self.left = Ch(), False
    async def leave(self): self.left = True
gns = dict(bot=types.SimpleNamespace(fetch_user=fetch_user, guilds=[1, 2, 3]), bot_bans_db={"servers": ["5"]}, BOT_CREATOR_ID=1, discord=disc, datetime=datetime, timezone=timezone)
exec(seg("on_guild_join"), gns)
async def join_tests():
    j = gns["on_guild_join"]
    for feats in ([], ["COMMUNITY"], ["DISCOVERABLE"]): await j(G(feats))
    check(dms == [] and invites_made == [], f"joining a server must message NOBODY and never make an invite: {dms}")
    banned = G([], gid=5); await j(banned); check(banned.left, "a banned server is left")
asyncio.run(join_tests())


# ---------- 8) amounts: all / half / quarter / 48% / 100,000,000 / 1.5k / 2m ----------
import decimal
ans = dict(re=re, decimal=decimal); exec(seg("_AMOUNT_WORDS", "_AMOUNT_SUFFIX", "parse_amount"), ans); pa = ans["parse_amount"]
for text, bal, want in [("all", 1000, 1000), ("ALL", 1000, 1000), ("half", 1000, 500), ("quarter", 1000, 250), ("48%", 1000, 480), ("100%", 1000, 1000), ("12.5%", 1000, 125),
        ("0%", 1000, None), ("101%", 1000, None), ("-5", 1000, None), ("abc", 1000, None), ("", 1000, None), (None, 1000, None), ("1e6", 0, None), ("1.5.2k", 0, None),
        ("1k", 0, 1000), ("1.5k", 0, 1500), ("2m", 0, 2_000_000), ("1b", 0, 10**9), ("100,000,000", 0, 100_000_000), ("100_000", 0, 100_000), ("  50 ", 0, 50),
        ("hepsi", 1000, 1000), ("половина", 1000, 500), ("yarı", 1000, 500), ("half", 7, 3), ("quarter", 7, 1), ("10%", 7, 0),
        ("half", 10**15, 5 * 10**14), ("33%", 10**15, 330_000_000_000_000)]:
    got = pa(text, bal); check(got == want, f"parse_amount({text!r}, {bal}) = {got!r}, expected {want!r}")
ECON2, sent2 = {}, []
def get_econ2(g, u): return ECON2.setdefault(u, {"wallet": 0, "bank": 0, "inventory": []})
async def send2(*a, **kw): sent2.append(kw["embed"].description if kw.get("embed") is not None else a[0])
async def check_casino(ctx, is_slash=False): return True
base = dict(L=_L, t=lambda g, key, *a: (key, a), get_econ=get_econ2, save_econ=lambda: None, discord=disc, re=re, decimal=decimal, parse_amount=pa, check_casino=check_casino)
ctx2 = types.SimpleNamespace(guild=types.SimpleNamespace(id=1), author=types.SimpleNamespace(id=10, display_name="Me"), send=send2)
vic2 = types.SimpleNamespace(id=20, display_name="Vic")
pns2 = dict(base); exec(seg("pay_p", "deposit_p", "withdraw_p"), pns2)
async def amount_tests():
    ECON2[10] = {"wallet": 1000, "bank": 400}; ECON2[20] = {"wallet": 0, "bank": 0}
    await pns2["pay_p"](ctx2, vic2, "half");  check(ECON2[10]["wallet"] == 500 and ECON2[20]["wallet"] == 450, f"pay half: {ECON2}")
    await pns2["pay_p"](ctx2, vic2, "all");   check(ECON2[10]["wallet"] == 0 and ECON2[20]["wallet"] == 900, f"pay all: {ECON2}")
    await pns2["pay_p"](ctx2, vic2, "5%");    check("positive" in str(sent2[-1]), f"zero amount: {sent2[-1]}")
    await pns2["pay_p"](ctx2, vic2, "abc");   check("Usage" in str(sent2[-1]), f"usage: {sent2[-1]}")
    await pns2["pay_p"](ctx2, vic2, "5k");    check(sent2[-1][0] == "not_enough_wallet", f"not enough: {sent2[-1]}")
    ECON2[10]["wallet"] = 1000
    await pns2["deposit_p"](ctx2, "half");    check(ECON2[10] == {"wallet": 500, "bank": 900}, f"deposit half: {ECON2[10]}")
    await pns2["withdraw_p"](ctx2, "25%");    check(ECON2[10] == {"wallet": 725, "bank": 675}, f"withdraw 25%: {ECON2[10]}")
    await pns2["withdraw_p"](ctx2, "all");    check(ECON2[10] == {"wallet": 1400, "bank": 0}, f"withdraw all: {ECON2[10]}")
    # coin flip with a fixed generator (heads) - amounts, swapped order, errors
    class RNGF:
        bit = 0
        def getrandbits(self, n): return self.bit
    cf_ns = dict(base, _RNG=RNGF()); exec(seg("cf_p"), cf_ns); cf = cf_ns["cf_p"]
    ECON2[10] = {"wallet": 1000, "bank": 0}
    await cf(ctx2, "30%", "heads");   check(ECON2[10]["wallet"] == 1300, f"cf 30% heads wins: {ECON2[10]}")
    await cf(ctx2, "tails", "half");  check(ECON2[10]["wallet"] == 650, f"cf swapped order loses half: {ECON2[10]}")
    cf_ns["_RNG"].bit = 1; await cf(ctx2, "all", "tails"); check(ECON2[10]["wallet"] == 1300, f"cf all tails wins: {ECON2[10]}")
    await cf(ctx2, "abc", "heads");   check(sent2[-1][0] == "invalid_bet", f"cf invalid amount: {sent2[-1]}")
    await cf(ctx2, "10", "x");        check("Usage" in str(sent2[-1]), f"cf usage: {sent2[-1]}")
    await cf(ctx2, "0", "heads");     check(sent2[-1][0] == "invalid_bet" and ECON2[10]["wallet"] == 1300, "cf zero bet")
    # slots: "all" bets the whole wallet; no argument shows the paytable
    sl_ns = dict(base, slot_spin=lambda: (["🍒", "🍒", "🍒"], 2, "triple"), slots_paytable=lambda: "TABLE"); exec(seg("slots_p"), sl_ns); sl = sl_ns["slots_p"]
    ECON2[10] = {"wallet": 1000, "bank": 0}
    await sl(ctx2, "all");  check(ECON2[10]["wallet"] == 2000, f"slots all x2: {ECON2[10]}")
    await sl(ctx2, None);   check("TABLE" in str(sent2[-1]) or "Paytable" in str(sent2[-2:]), "slots without bet shows the paytable")
    await sl(ctx2, "abc");  check(sent2[-1][0] == "invalid_bet", f"slots invalid: {sent2[-1]}")
    await sl(ctx2, "1m");   check(sent2[-1][0] == "not_enough_wallet" and ECON2[10]["wallet"] == 2000, f"slots too much: {sent2[-1]}")
    check("parse_amount" in seg("bj_p") and "bet: str" in seg("bj_p"), "bj_p must use the amount parser")
asyncio.run(amount_tests())

print("SELF-TEST 2:", "ALL PASSED" if not fails else f"{len(fails)} FAILED")
print(f"  slots: exact RTP {rtp:.4f} | simulated {ret / N:.4f} | any payout {any_pay / N * 100:.1f}% | triples 1 in {round(N / max(1, kinds['triple'] + kinds['jackpot']))} | jackpots in {N}: {kinds['jackpot']}")
print(f"  coin flip heads share {heads:.4f} | flags {len(F)}")
for f in fails: print("  FAIL:", f)
sys.exit(1 if fails else 0)
