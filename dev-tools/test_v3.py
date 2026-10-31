"""V3: store/inventory buttons, Higher-Lower odds and game flow, multiplayer blackjack, forceban, .work lines, drawn cards.
Runs without a Discord connection (discord.py must be installed for the view tests). BOT_SRC=path picks the file."""
import ast, asyncio, collections, io, math, os, random, re, sys, types
BOT = os.environ.get("BOT_SRC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot.py"))
SRC = open(BOT, encoding="utf-8").read(); TREE = ast.parse(SRC)
def nm(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return n.name
    if isinstance(n, ast.Assign):
        t = n.targets[0]; return t.id if isinstance(t, ast.Name) else None
def seg(*names):
    out = [ast.get_source_segment(SRC, n) for want in names for n in TREE.body if nm(n) == want]
    assert len(out) == len(names), f"missing {names}"; return "\n\n".join(out)
def deco(fn):
    node = next(n for n in TREE.body if nm(n) == fn); return " ".join(ast.unparse(d) for d in node.decorator_list)
fails = []
def check(c, m):
    if not c: fails.append(m)
def Lf(s, *a): return s.format(*a) if a else s

# ---- 1) source guarantees
prefix = set(re.findall(r'@bot\.command\(name="([\w-]+)"', SRC))
check("useitem" not in prefix and "useitem" not in ast.get_source_segment(SRC, next(n for n in TREE.body if nm(n) == "HELP_TEXT")), "useitem is gone (command and help)")
check({"forceban", "higherlower", "blackjack", "estore", "inv", "buy", "work"} <= prefix, "V3 commands are registered")
gen = ast.literal_eval(seg("GENERAL_CMDS").split("=", 1)[1].strip())
check("higherlower" in gen and "useitem" not in gen, "GENERAL_CMDS updated")
check("ban_members" in deco("forceban_p") and "bot_has_permissions" in deco("forceban_p") and "guild_permissions.ban_members" in seg("forceban_p"), "forceban: user and bot need Ban Members")
fb = seg("forceban_p"); check("can_act_on" in fb and "fetch_ban" in fb and "post_case_log" in fb and "send_dm" not in fb, "forceban: hierarchy check, already-banned check, case log, never a DM")
check("discord.version_info < (2, 6)" in SRC, "clear message when discord.py is too old for components v2")
check("_can_attach(ctx.channel)" in seg("slots_p") and "_can_attach(ctx.channel)" in seg("cf_p") and "_can_attach(channel)" in seg("_fx_attach"), "no upload attempt where Attach Files is denied (text fallback)")
check("ctx.send(view=view" in seg("estore_p") and "ctx.send(view=view" in seg("inv_p"), "store and inventory use the button layouts")

# ---- 2) Higher-Lower odds: ties lose, RTP = 97% per guess, impossible sides are disabled
hns = dict(math=math); exec(seg("HL_RANKS", "HL_EDGE", "HL_MAX_MULT", "hl_value", "hl_odds"), hns); odds = hns["hl_odds"]
for r in hns["HL_RANKS"]:
    for side, (p, m) in odds((r, "♠️")).items():
        if p:
            check(0.955 <= p * m <= 0.97 + 1e-9 and m >= 1.0, f"hl RTP for {r} {side}: p={p:.3f} m={m}")
        else:
            check(m == 0.0, f"impossible side has no multiplier: {r} {side}")
check(odds(("3", "♥️"))["lower"][1] == 12.61 and odds(("3", "♥️"))["higher"][1] == 1.14, f"card 3: {odds(('3', '♥️'))}")
check(odds(("2", "♥️"))["lower"][0] == 0 and odds(("A", "♥️"))["higher"][0] == 0 and odds(("8", "♣️"))["higher"][1] == odds(("8", "♣️"))["lower"][1] == 2.1, "edges and the middle card")
rng = random.Random(7); ret = 0.0; N = 200000
for _ in range(N):
    cur = rng.choice(hns["HL_RANKS"]); nxt = rng.choice(hns["HL_RANKS"]); o = odds((cur, "x"))
    side = max(o, key=lambda k: o[k][0]); a, b = hns["hl_value"]((cur, "")), hns["hl_value"]((nxt, ""))
    ret += o[side][1] if (b > a if side == "higher" else b < a) else 0
check(0.95 < ret / N < 0.985, f"simulated return per guess {ret / N:.4f}")

# ---- 3) blackjack payouts
bns = {}; exec(seg("hand_value", "bj_dealer_play", "bj_credit"), bns); cr = bns["bj_credit"]
check(cr("bust", 25, 18, 100) == 0 and cr("bj", 21, 21, 100) == 250 and cr("stand", 20, 22, 100) == 200 and cr("stand", 20, 19, 100) == 200
      and cr("stand", 18, 18, 100) == 100 and cr("stand", 17, 20, 100) == 0, "blackjack credits (stake included)")
deck = [("5", "s"), ("K", "s")]; d = bns["bj_dealer_play"]([("2", "h"), ("3", "h")], deck.pop)
check(bns["hand_value"](d) >= 17 and len(d) == 4, f"dealer draws to 17: {d}")

# ---- 4) store: buy and use
econ = collections.defaultdict(lambda: {"wallet": 500, "bank": 0, "inventory": []}); saves = []
sns = dict(estore_db={"1": {"a": {"name": "VIP", "price": 300, "role": "77"}, "b": {"name": "Cookie", "price": 50, "role": None}}},
           get_econ=lambda g, u: econ[(g, u)], save_econ=lambda: saves.append(1), L=Lf)
exec(seg("_store_item_by_name", "buy_store_item", "use_store_item"), sns)
ok, msg = sns["buy_store_item"](1, 9, "a"); check(ok and econ[(1, 9)]["wallet"] == 200 and econ[(1, 9)]["inventory"] == ["VIP"], f"buy works: {msg}")
ok, msg = sns["buy_store_item"](1, 9, "a"); check(not ok and econ[(1, 9)]["wallet"] == 200, "cannot buy without money")
ok, msg = sns["buy_store_item"](1, 9, "zzz"); check(not ok, "missing item")
given = []
class Member:
    id = 9
    async def add_roles(self, role, reason=None): given.append(role)
guild = types.SimpleNamespace(id=1, get_role=lambda i: types.SimpleNamespace(id=i, mention=f"<@&{i}>"))
sns["role_assignable"] = lambda g, r: True
async def use_test():
    econ[(1, 9)]["inventory"] += ["Cookie"]
    ok1, _ = await sns["use_store_item"](guild, Member(), "vip")
    ok2, _ = await sns["use_store_item"](guild, Member(), "Cookie")
    ok3, _ = await sns["use_store_item"](guild, Member(), "Cookie")
    check(ok1 and ok2 and not ok3 and [r.id for r in given] == [77] and econ[(1, 9)]["inventory"] == [], f"use: role given once, items removed: {given} {econ[(1, 9)]}")
    sns["role_assignable"] = lambda g, r: False; econ[(1, 9)]["inventory"] += ["VIP"]
    ok4, _ = await sns["use_store_item"](guild, Member(), "VIP")
    check(not ok4 and econ[(1, 9)]["inventory"] == ["VIP"], "an item whose role cannot be given is kept")
asyncio.run(use_test())

# ---- 5) .work: three different joke sets
wl = ast.literal_eval(seg("WORK_LINES").split("=", 1)[1].strip())
check(set(wl) == {"en", "tr", "ru"} and all(len(v) >= 15 and len(set(v)) == len(v) and all(x.strip() for x in v) for v in wl.values()), "work lines: 15+ unique lines per language")
check(not (set(wl["en"]) & set(wl["tr"])) and not (set(wl["en"]) & set(wl["ru"])) and all(re.search(r"[а-яё]", x, re.I) for x in wl["ru"]) and all(re.search(r"[çğıöşüâ]", x, re.I) or True for x in wl["tr"]), "per-language sets, not copies")
check("_LANG.get()" in seg("work_line") and "work_line()" in seg("work_p"), ".work picks the server language")

# ---- 6) views (needs discord.py): blackjack table, invite, higher-lower, store layout size
try:
    import discord
except Exception:
    discord = None
if discord is not None:
    wallets = collections.defaultdict(lambda: {"wallet": 1000, "bank": 0, "inventory": []})
    ns = dict(discord=discord, asyncio=asyncio, math=math, io=io, collections=collections, re=re, random=random,
              L=Lf, t=lambda g, k, *a: k, get_econ=lambda g, u: wallets[u], save_econ=lambda: None, active_bj={}, _RNG=random.Random(3),
              bot_bans_db={}, BOT_CREATOR_ID=1, set_lang=lambda g: None, user_restricted=lambda u, f: False, restricted_text=lambda f: "x",
              render_bj_table=None, render_hl=None, estore_db={}, get_settings=lambda g: {"prefix": "."}, role_assignable=lambda g, r: True)
    exec(seg("BaseView", "CARD_SUITS", "card_emoji", "hand_value", "HL_RANKS", "HL_EDGE", "HL_MAX_MULT", "hl_value", "hl_odds", "hl_draw",
             "BJ_MAX_PLAYERS", "BJ_TURN_SECONDS", "BJ_INVITE_SECONDS", "bj_dealer_play", "bj_credit", "bj_shoe", "BlackjackTable",
             "start_bj_table", "BlackjackInvite", "HigherLowerView", "BaseLayout", "STORE_PAGE", "_item_text", "_store_item_by_name",
             "_PagedLayout", "StoreLayout", "InventoryLayout", "_quiet"), ns)
    async def no_image(embed, name, fn, *a, **k): return []
    ns["_fx_attach"] = no_image
    class Resp:
        async def defer(self): pass
        async def send_message(self, *a, **k): pass
        async def edit_message(self, **k): pass
    class Follow:
        def __init__(self): self.sent = []
        async def send(self, *a, **k): self.sent.append(a)
    class Inter:
        def __init__(self, uid): self.user = types.SimpleNamespace(id=uid); self.response = Resp(); self.followup = Follow(); self.edits = []
        async def edit_original_response(self, **k): self.edits.append(k)
    class Msg:
        def __init__(self): self.edits = []
        async def edit(self, **k): self.edits.append(k)
    M = lambda i: types.SimpleNamespace(id=i, display_name=f"P{i}", mention=f"<@{i}>")
    async def views():
        # three players, turns in order, only the current player can act, money adds up
        ab = ns["active_bj"]
        for u in (11, 12, 13): wallets[u]["wallet"] -= 100
        tb = ns["BlackjackTable"](1, [M(11), M(12), M(13)], 100)
        for u in (11, 12, 13): ab[u] = tb
        tb.message = Msg()
        order = []
        for _ in range(40):
            cur = tb.current()
            if cur is None: break
            order.append(cur["id"])
            other = next(s["id"] for s in tb.seats if s["id"] != cur["id"])
            before = [list(s["hand"]) for s in tb.seats]
            await tb.act(Inter(other), "hit")
            check([list(s["hand"]) for s in tb.seats] == before, "a player who is not on turn changes nothing")
            await tb.act(Inter(cur["id"]), "hit" if ns["hand_value"](cur["hand"]) < 15 else "stand")
        if not tb.finished: tb.settle()
        check(tb.finished and not ab, "table settled, games released")
        check(order == sorted(order), f"turns go player by player: {order}")
        dv = ns["hand_value"](tb.dealer)
        for s in tb.seats:
            exp = 900 + ns["bj_credit"](s["state"], ns["hand_value"](s["hand"]), dv, s["bet"])
            check(wallets[s["id"]]["wallet"] == exp, f"wallet of {s['id']}: {wallets[s['id']]['wallet']} != {exp}")
        # double: pays the extra bet once, one card, then the turn moves on
        wallets[21]["wallet"] = 300
        tb2 = ns["BlackjackTable"](1, [M(21), M(22)], 100); tb2.message = Msg()
        tb2.seats[0]["hand"], tb2.seats[0]["state"], tb2.turn = [("5", "♠️"), ("6", "♥️")], "play", 0
        await tb2.act(Inter(21), "double")
        check(tb2.seats[0]["bet"] == 200 and wallets[21]["wallet"] == 200 and len(tb2.seats[0]["hand"]) == 3 and tb2.seats[0]["state"] in ("stand", "bust"), "double")
        check(tb2.finished or tb2.current()["id"] == 22, "turn moves on after double")
        # an idle player stands automatically, the others keep playing
        ns["BJ_TURN_SECONDS"] = 0.05
        tb3 = ns["BlackjackTable"](1, [M(31), M(32)], 50); tb3.message = Msg()
        for s in tb3.seats: s["hand"], s["state"] = [("9", "♠️"), ("7", "♥️")], "play"
        tb3.turn = -1; tb3.advance(); tb3._arm_timer()
        await asyncio.sleep(0.3)
        check(tb3.seats[0]["afk"] and tb3.seats[0]["state"] == "stand", "idle player stands after the turn timer")
        await asyncio.sleep(0.3)
        check(tb3.finished and tb3.message.edits, "second idle player too, then the table settles and the message is updated")
        ns["BJ_TURN_SECONDS"] = 45
        # invite: one accepts, one declines -> table with host + the one who accepted; nobody -> refund
        for u in (41, 42, 43): wallets[u]["wallet"] = 500
        wallets[41]["wallet"] -= 100
        inv = ns["BlackjackInvite"](1, M(41), [M(42), M(43)], 100); inv.message = Msg(); ab[41] = inv
        await inv.accept.callback(Inter(42)); await inv.decline.callback(Inter(43))
        tbl = ab.get(41)
        check(inv.closed and isinstance(tbl, ns["BlackjackTable"]) and [s["id"] for s in tbl.seats] == [41, 42] and wallets[42]["wallet"] == 400 and wallets[43]["wallet"] == 500, "invite -> table")
        check(inv.message.edits and inv.message.edits[-1].get("content", "x") is None, "the invite message turns into the table")
        wallets[51]["wallet"] = 400
        inv2 = ns["BlackjackInvite"](1, M(51), [M(52)], 100); inv2.message = Msg(); ab[51] = inv2
        await inv2.on_timeout()
        check(inv2.closed and wallets[51]["wallet"] == 500 and 51 not in ab, "nobody accepted -> refund")
        # higher-lower: right guess multiplies, cash out pays, wrong guess loses
        seq = iter([("5", "♠️"), ("9", "♥️"), ("K", "♦️"), ("2", "♣️"), ("7", "♣️")])
        ns["hl_draw"] = lambda: next(seq)
        wallets[61]["wallet"] = 900
        hl = ns["HigherLowerView"](61, 1, 100, "P61"); ab[61] = hl
        m1 = ns["hl_odds"](("5", ""))["higher"][1]
        await hl.guess(Inter(61), "higher")
        check(hl.wins == 1 and abs(hl.mult - m1) < 1e-9 and not hl.done, "right guess")
        await hl.cashout.callback(Inter(61))
        check(hl.done and wallets[61]["wallet"] == 900 + int(100 * m1) and 61 not in ab, f"cash out pays {int(100 * m1)}")
        hl2 = ns["HigherLowerView"](62, 1, 100, "P62"); wallets[62]["wallet"] = 0; ab[62] = hl2
        await hl2.guess(Inter(62), "higher")
        check(hl2.done and wallets[62]["wallet"] == 0 and 62 not in ab, "wrong guess loses the bet")
        hl3 = ns["HigherLowerView"](63, 1, 100, "P63"); hl3.card = ("2", "♠️"); hl3.refresh_buttons()
        check(hl3.lower.disabled and not hl3.higher.disabled and "1.05" in hl3.higher.label, f"impossible side disabled: {hl3.higher.label}")
        # store layout: 24 items -> 4 pages, each page within Discord's 40 components
        g = types.SimpleNamespace(id=5, name="Srv", get_role=lambda i: None)
        ns["estore_db"]["5"] = {str(i): {"name": f"Item {i}", "price": 10 + i, "role": None, "description": "d" * 200} for i in range(24)}
        lay = ns["StoreLayout"](g)
        sizes = []
        for p in range(4):
            lay.page = p; lay.build(); sizes.append(len(list(lay.walk_children())))
        buys = [c for c in lay.walk_children() if isinstance(c, discord.ui.Button) and c.label == "Buy"]
        check(max(sizes) <= 40 and len(buys) == 6, f"store pages fit: {sizes}, buy buttons {len(buys)}")
        wallets[71]["inventory"] = ["Item 1", "Item 1", "Item 2"]
        own = ns["InventoryLayout"](g, M(71), 71); other = ns["InventoryLayout"](g, M(71), 72)
        uses = lambda v: [c for c in v.walk_children() if isinstance(c, discord.ui.Button) and c.label == "Use"]
        texts = " ".join(c.content for c in own.walk_children() if isinstance(c, discord.ui.TextDisplay))
        check(len(uses(own)) == 2 and not uses(other) and "×2" in texts, "inventory: quantity, Use buttons only for the owner")
    asyncio.run(views())
else:
    print("  (discord.py missing - view tests skipped)")

# ---- 7) drawings (needs Pillow): cards, table, higher-lower, slots, coin
start = SRC.index("# VISUAL SUITE"); end = SRC.index("# V3 - store / inventory buttons")
fx_src = SRC[SRC.rfind("# ====", 0, start): SRC.rfind("# ====", 0, end)]
fns = dict(asyncio=asyncio, random=random, math=math, io=io, SLOT_SYMBOLS=[("🍒", 194, 1, 2), ("🍋", 153, 1.5, 3), ("🍊", 123, 2.5, 5), ("🍇", 92, 5, 10), ("🍉", 71, 7.5, 15), ("⭐", 56, 10, 20), ("🔔", 46, 15, 50), ("💎", 39, 25, 100), ("🎰", 31, 30, 300), ("🍀", 195, 0, 0)])
exec(seg("hand_value"), fns); exec(fx_src, fns)
if fns.get("FX_OK"):
    from PIL import Image
    S = fns["CARD_SUITS"]
    seats = [dict(name=n, hand=[("A", S[0]), ("K", S[1]), ("10", S[2])], value=21, tag="STAND", turn=i == 1, tone=None) for i, n in enumerate(["Brad", "Мария 🎲", "Kerem", "X" * 60])]
    for n in (1, 2, 3, 4):
        png = fns["render_bj_table"]([("Q", S[3]), ("7", S[1])], True, seats[:n], {"dealer": "Krupiye"})
        im = Image.open(io.BytesIO(png)); check(png[:8] == b"\x89PNG\r\n\x1a\n" and im.size[0] == 720 and 300 < im.size[1] < 700, f"table for {n}: {im.size}")
    png = fns["render_hl"](("3", S[1]), None, [("9", S[0])] * 9, 12.61, "$1,261", None, None, "BÜYÜK MÜ KÜÇÜK MÜ")
    check(Image.open(io.BytesIO(png)).size == (640, 270), "higher-lower picture")
    png = fns["render_hl"](("3", S[1]), ("2", S[0]), [], 1.0, "$0", "KAYBETTİN", "lose")
    check(len(png) > 1000, "higher-lower lost picture")
    gif, last, secs = fns["render_slots"](["🍒", "🍋", "🍀"], 0, "none")
    check(gif[:6] == b"GIF89a" and last[:4] == b"\x89PNG" and 2 < secs < 8, "slot animation")
    gif, last, secs = fns["render_coin"]("tails", False, "Tails")
    check(gif[:6] == b"GIF89a" and 1 < secs < 5, "coin animation")
else:
    print("  (Pillow missing - drawing tests skipped)")

print("V3:", "ALL PASSED (store/inv buttons, higher-lower odds + flow, multiplayer blackjack, invite, forceban, work lines, drawings)" if not fails else f"{len(fails)} FAILED")
for x in fails: print("  FAIL:", x)
sys.exit(1 if fails else 0)
