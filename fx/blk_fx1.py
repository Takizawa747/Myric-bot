# ==== FX BEGIN ====
# ============================================================
# VISUAL SUITE - animated slots / coin, moderation banners, rank / level-up / leaderboard cards.
# Pillow is OPTIONAL: when it is missing (or anything fails) every command falls back to its plain embed.
# ============================================================
import io, math
FX_OK = False
try:
    from PIL import Image as PI, ImageDraw as PD, ImageFilter as PFl, ImageFont as PFt
    FX_OK = True
except Exception:
    pass

_FX_SEM = None
async def fx_run(fn, *args, timeout=8.0):
    """Run a CPU-heavy renderer in a worker thread (two at a time at most) with a time limit."""
    global _FX_SEM
    if not FX_OK:
        raise RuntimeError("Pillow is not installed")
    if _FX_SEM is None:
        _FX_SEM = asyncio.Semaphore(2)
    async with _FX_SEM:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)

def _fx_lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))
_FX_FONTS = {}
def _fx_font(size, bold=True):
    key = (size, bold)
    if key not in _FX_FONTS:
        f, names = None, (("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if bold else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"))
        for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/", ""):
            for n in names:
                try:
                    f = PFt.truetype(d + n, size)
                    break
                except Exception:
                    pass
            if f:
                break
        if f is None:
            try:
                f = PFt.load_default(size)
            except TypeError:
                f = PFt.load_default()
        _FX_FONTS[key] = f
    return _FX_FONTS[key]

_FX_TOFU = {}
def _fx_mask(font, ch):
    m = font.getmask(ch)
    return m.tobytes() if hasattr(m, "tobytes") else bytes(m)
def _fx_safe(font, text, max_w=None):
    """Names may contain emoji or scripts the font lacks: drop those characters (no empty boxes) and shorten to fit."""
    ref = _FX_TOFU.setdefault(id(font), _fx_mask(font, "\uFFFE"))
    out = []
    for ch in str(text):
        if ch.isspace():
            out.append(" ")
            continue
        try:
            ok = _fx_mask(font, ch) != ref
        except Exception:
            ok = ch.isascii()
        if ok and ch.isprintable():
            out.append(ch)
    s = " ".join("".join(out).split()) or "?"
    if max_w and font.getlength(s) > max_w:
        while len(s) > 1 and font.getlength(s + "…") > max_w:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s

def _fx_gif(frames, dur_ms, last_ms=30000, colors=200):
    n = len(frames)
    idx = sorted({round(i * (n - 1) / 7) for i in range(8)})
    w, h = frames[0].size
    mosaic = PI.new("RGB", (w // 2 * len(idx), h // 2))
    for q, i in enumerate(idx):
        mosaic.paste(frames[i].resize((w // 2, h // 2)), (q * (w // 2), 0))
    pal = mosaic.quantize(colors=colors, method=PI.Quantize.MEDIANCUT)
    pf = [f.quantize(palette=pal, dither=PI.Dither.NONE) for f in frames]
    buf = io.BytesIO()
    pf[0].save(buf, format="GIF", save_all=True, append_images=pf[1:], duration=[dur_ms] * (n - 1) + [last_ms], loop=0, disposal=1)
    return buf.getvalue()
def _fx_png(img):
    b = io.BytesIO()
    img.save(b, format="PNG", optimize=True)
    return b.getvalue()

_FX_AVATARS = {}
async def fx_avatar(user, size=128):
    """Avatar bytes (cached); None when it cannot be fetched."""
    try:
        key = (user.id, getattr(user.display_avatar, "key", ""), size)
        if key in _FX_AVATARS:
            return _FX_AVATARS[key]
        data = await user.display_avatar.replace(size=size, format="png").read()
        if len(_FX_AVATARS) > 300:
            _FX_AVATARS.pop(next(iter(_FX_AVATARS)))
        _FX_AVATARS[key] = data
        return data
    except Exception:
        return None

class _Cv:
    """Tiny supersampled drawing canvas: everything is drawn k times larger and shrunk at the end (smooth edges)."""
    def __init__(self, w, h, k=2, bg=(0, 0, 0)):
        self.w, self.h, self.k = w, h, k
        self.im = PI.new("RGB", (w * k, h * k), bg)
        self.d = PD.Draw(self.im, "RGBA")
    def box(self, b): return tuple(int(v * self.k) for v in b)
    def rr(self, b, r, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.box(b), int(r * self.k), fill=fill, outline=outline, width=max(1, int(width * self.k)))
    def ell(self, b, fill=None, outline=None, width=1):
        self.d.ellipse(self.box(b), fill=fill, outline=outline, width=max(1, int(width * self.k)))
    def text(self, xy, s, size, fill, anchor="la", bold=True):
        self.d.text((xy[0] * self.k, xy[1] * self.k), s, font=_fx_font(int(size * self.k), bold), fill=fill, anchor=anchor)
    def safe(self, s, size, max_w, bold=True): return _fx_safe(_fx_font(int(size * self.k), bold), s, max_w * self.k)
    def grad(self, box, c1, c2, vertical=False, radius=0):
        x0, y0, x1, y1 = self.box(box)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        g = PI.new("RGB", (w, h))
        gd = PD.Draw(g)
        for i in range(h if vertical else w):
            c = _fx_lerp(c1, c2, i / max(1, (h if vertical else w) - 1))
            gd.line([(0, i), (w, i)] if vertical else [(i, 0), (i, h)], fill=c)
        mask = PI.new("L", (w, h), 0)
        PD.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), int(radius * self.k), fill=255)
        self.im.paste(g, (x0, y0), mask)
    def avatar(self, data, cx, cy, r, name, accent):
        size = int(2 * r * self.k)
        av = None
        if data:
            try:
                av = PI.open(io.BytesIO(data)).convert("RGB").resize((size, size), PI.Resampling.LANCZOS)
            except Exception:
                av = None
        if av is None:
            av = PI.new("RGB", (size, size), accent)
            ch = self.safe(name, 10, 40)[:1].upper() or "?"
            PD.Draw(av).text((size / 2, size / 2), ch, font=_fx_font(int(size * 0.5)), fill=(255, 255, 255), anchor="mm")
        mask = PI.new("L", (size, size), 0)
        PD.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        self.im.paste(av, (int(cx * self.k - size / 2), int(cy * self.k - size / 2)), mask)
    def width(self, s, size, bold=True): return _fx_font(int(size * self.k), bold).getlength(s) / self.k
    def out(self): return self.im.resize((self.w, self.h), PI.Resampling.LANCZOS)

# ---------------- slot machine ----------------
_SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "🍉", "⭐", "🔔", "💎", "🎰", "🍀"]
_SLOT_WEIGHTS = [194, 153, 123, 92, 71, 56, 46, 39, 31, 195]
_SLOT_ASSETS = {}
def _slot_assets():
    if _SLOT_ASSETS:
        return _SLOT_ASSETS
    S, SPR = 4, 84
    def new(): return PI.new("RGBA", (SPR * S, SPR * S), (0, 0, 0, 0)), SPR * S / 100
    def fin(im): return im.resize((SPR, SPR), PI.Resampling.LANCZOS)
    def ball(im, cx, cy, r, light, dark, outline=None, steps=18):
        d = PD.Draw(im)
        if outline:
            d.ellipse((cx - r - 2.2 * S, cy - r - 2.2 * S, cx + r + 2.2 * S, cy + r + 2.2 * S), fill=outline + (255,))
        for i in range(steps):
            t = i / (steps - 1)
            rr, off = r * (1 - 0.8 * t), r * 0.22 * t
            d.ellipse((cx - rr - off, cy - rr - off, cx + rr - off, cy + rr - off), fill=_fx_lerp(dark, light, t) + (255,))
    def shine(im, box, a=170):
        layer = PI.new("RGBA", im.size, (0, 0, 0, 0))
        PD.Draw(layer).ellipse(box, fill=(255, 255, 255, a))
        im.alpha_composite(layer)
    def leaf(d, U, pts): d.polygon([(x * U, y * U) for x, y in pts], fill=(96, 176, 64, 255), outline=(40, 100, 36, 255))
    def star(cx, cy, ro, ri): return [(cx + (ro if i % 2 == 0 else ri) * math.cos(math.radians(-90 + i * 36)), cy + (ro if i % 2 == 0 else ri) * math.sin(math.radians(-90 + i * 36))) for i in range(10)]
    def cherry():
        im, U = new(); d = PD.Draw(im); stem = (84, 130, 52, 255)
        d.line([(30 * U, 66 * U), (46 * U, 34 * U), (64 * U, 16 * U)], fill=stem, width=int(3.4 * U), joint="curve")
        d.line([(68 * U, 70 * U), (62 * U, 38 * U), (64 * U, 16 * U)], fill=stem, width=int(3.4 * U), joint="curve")
        leaf(d, U, [(64, 16), (88, 8), (90, 24), (74, 28)])
        for x, y, r in ((30, 70, 20), (68, 73, 18)):
            ball(im, x * U, y * U, r * U, (255, 125, 125), (172, 12, 36), outline=(110, 0, 20)); shine(im, ((x - 10) * U, (y - 12) * U, (x - 2) * U, (y - 4) * U))
        return fin(im)
    def lemon():
        im, U = new(); L = PI.new("RGBA", im.size, (0, 0, 0, 0)); d = PD.Draw(L)
        for pts in ([(5, 50), (22, 38), (22, 62)], [(95, 50), (78, 38), (78, 62)]):
            d.polygon([(x * U, y * U) for x, y in pts], fill=(214, 170, 20, 255))
        d.ellipse((10 * U, 24 * U, 90 * U, 76 * U), fill=(214, 170, 20, 255)); d.ellipse((13 * U, 27 * U, 87 * U, 72 * U), fill=(255, 225, 70, 255)); d.ellipse((22 * U, 31 * U, 62 * U, 46 * U), fill=(255, 247, 175, 210))
        im.alpha_composite(L.rotate(22, resample=PI.Resampling.BICUBIC, center=(50 * U, 50 * U))); leaf(PD.Draw(im), U, [(66, 20), (88, 8), (90, 26), (74, 28)])
        return fin(im)
    def orange():
        im, U = new(); ball(im, 50 * U, 58 * U, 34 * U, (255, 178, 72), (224, 100, 10), outline=(150, 60, 0)); shine(im, (28 * U, 36 * U, 46 * U, 50 * U))
        d = PD.Draw(im); leaf(d, U, [(52, 26), (78, 10), (82, 28), (62, 34)]); d.ellipse((45 * U, 20 * U, 56 * U, 31 * U), fill=(110, 70, 30, 255))
        return fin(im)
    def grapes():
        im, U = new(); d = PD.Draw(im)
        d.line([(50 * U, 34 * U), (53 * U, 12 * U)], fill=(100, 70, 40, 255), width=int(3.6 * U)); leaf(d, U, [(53, 18), (80, 6), (82, 24), (64, 28)])
        for x, y in [(50, 86), (42, 70), (58, 70), (34, 54), (50, 54), (66, 54), (26, 38), (42, 38), (58, 38), (74, 38)]:
            ball(im, x * U, y * U, 11 * U, (190, 120, 230), (84, 24, 140), outline=(50, 10, 90), steps=10); shine(im, ((x - 6) * U, (y - 7) * U, (x - 1) * U, (y - 2) * U), 150)
        return fin(im)
    def melon():
        im, U = new(); L = PI.new("RGBA", im.size, (0, 0, 0, 0)); d = PD.Draw(L); cx, cy = 50 * U, 28 * U
        for r, col in ((47, (24, 92, 38)), (43, (118, 202, 92)), (39, (250, 246, 228)), (35, (236, 52, 72))):
            d.pieslice((cx - r * U, cy - r * U, cx + r * U, cy + r * U), 0, 180, fill=col + (255,))
        for x, y in ((36, 46), (50, 54), (64, 46), (43, 62), (57, 62)):
            d.ellipse(((x - 2.5) * U, (y - 4) * U, (x + 2.5) * U, (y + 4) * U), fill=(30, 20, 20, 255))
        d.ellipse((24 * U, 34 * U, 42 * U, 42 * U), fill=(255, 255, 255, 90)); im.alpha_composite(L.rotate(12, resample=PI.Resampling.BICUBIC, center=(50 * U, 50 * U)))
        return fin(im)
    def starsym():
        im, U = new(); d = PD.Draw(im)
        d.polygon([(x * U, y * U) for x, y in star(50, 54, 47, 21)], fill=(176, 108, 8, 255)); d.polygon([(x * U, y * U) for x, y in star(50, 54, 41, 18)], fill=(255, 200, 36, 255))
        d.polygon([(x * U, y * U) for x, y in star(50, 51, 27, 12)], fill=(255, 236, 120, 255)); shine(im, (40 * U, 24 * U, 52 * U, 34 * U), 190)
        return fin(im)
    def bell():
        im, U = new(); d = PD.Draw(im)
        def shape(col, k):
            d.ellipse(((24 + k) * U, (14 + k) * U, (76 - k) * U, (66 - k) * U), fill=col); d.polygon([((24 + k) * U, 40 * U), ((76 - k) * U, 40 * U), ((90 - k) * U, (76 - k) * U), ((10 + k) * U, (76 - k) * U)], fill=col)
            d.rounded_rectangle(((8 + k) * U, (72 + k) * U, (92 - k) * U, (86 - k) * U), int(6 * U), fill=col)
        shape((160, 98, 10, 255), 0); shape((255, 200, 40, 255), 3); d.ellipse((44 * U, 4 * U, 56 * U, 16 * U), fill=(176, 108, 8, 255))
        d.ellipse((42 * U, 84 * U, 58 * U, 100 * U), fill=(176, 108, 8, 255)); d.ellipse((44 * U, 86 * U, 56 * U, 98 * U), fill=(255, 210, 60, 255)); shine(im, (32 * U, 24 * U, 46 * U, 52 * U), 140)
        return fin(im)
    def gem():
        im, U = new(); d = PD.Draw(im)
        for pts, col in (([(28, 26), (72, 26), (92, 46), (50, 92), (8, 46)], (10, 70, 150)), ([(28, 26), (72, 26), (62, 46), (38, 46)], (130, 214, 255)), ([(8, 46), (28, 26), (38, 46)], (76, 172, 242)),
                         ([(92, 46), (72, 26), (62, 46)], (60, 150, 232)), ([(8, 46), (38, 46), (50, 92)], (36, 128, 214)), ([(92, 46), (62, 46), (50, 92)], (18, 92, 172)), ([(38, 46), (62, 46), (50, 92)], (70, 172, 246))):
            d.polygon([(x * U, y * U) for x, y in pts], fill=col + (255,))
        d.line([(x * U, y * U) for x, y in [(28, 26), (72, 26), (92, 46), (50, 92), (8, 46), (28, 26)]], fill=(8, 50, 120, 255), width=int(2.2 * U), joint="curve"); shine(im, (34 * U, 28 * U, 46 * U, 36 * U), 200)
        return fin(im)
    def machine():
        im, U = new(); d = PD.Draw(im)
        d.line([(82 * U, 38 * U), (92 * U, 22 * U)], fill=(170, 172, 184, 255), width=int(4 * U)); d.ellipse((86 * U, 12 * U, 99 * U, 25 * U), fill=(255, 60, 60, 255), outline=(120, 0, 0, 255), width=int(1.5 * U))
        d.rounded_rectangle((14 * U, 12 * U, 82 * U, 92 * U), int(9 * U), fill=(196, 22, 42, 255), outline=(242, 192, 60, 255), width=int(3.2 * U))
        d.rounded_rectangle((22 * U, 24 * U, 74 * U, 56 * U), int(4 * U), fill=(255, 250, 235, 255), outline=(120, 70, 10, 255), width=int(2 * U))
        for x in (32, 48, 64):
            d.text((x * U, 41 * U), "7", font=_fx_font(int(24 * U)), fill=(214, 22, 30, 255), anchor="mm")
        d.rounded_rectangle((26 * U, 66 * U, 70 * U, 82 * U), int(3 * U), fill=(70, 10, 18, 255)); shine(im, (20 * U, 16 * U, 36 * U, 22 * U), 120)
        return fin(im)
    def clover():
        im, U = new(); d = PD.Draw(im); d.line([(50 * U, 52 * U), (60 * U, 80 * U), (72 * U, 92 * U)], fill=(36, 110, 46, 255), width=int(3.6 * U), joint="curve")
        for a in (45, 135, 225, 315):
            ball(im, (50 + 18 * math.cos(math.radians(a))) * U, (46 + 18 * math.sin(math.radians(a))) * U, 18 * U, (130, 230, 110), (24, 130, 50), outline=(16, 80, 36), steps=12)
        d.ellipse((44 * U, 40 * U, 56 * U, 52 * U), fill=(30, 120, 50, 255))
        return fin(im)
    W, H, RW, RH, GAP, RY = 480, 240, 120, 140, 12, 54
    sprites = dict(zip(_SLOT_SYMBOLS, [f() for f in (cherry, lemon, orange, grapes, melon, starsym, bell, gem, machine, clover)]))
    base = PI.new("RGB", (W, H)); d = PD.Draw(base); rx = [(W - (3 * RW + 2 * GAP)) // 2 + i * (RW + GAP) for i in range(3)]
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_fx_lerp((46, 22, 90), (12, 6, 30), y / (H - 1)))
    rng = random.Random(7)
    for _ in range(80):
        d.point((rng.randrange(W), rng.randrange(H)), fill=rng.choice([(96, 74, 156), (126, 104, 196), (74, 52, 124)]))
    d.rounded_rectangle((5, 5, W - 6, H - 6), 24, outline=(236, 186, 64), width=4); d.rounded_rectangle((11, 11, W - 12, H - 12), 19, outline=(130, 78, 24), width=2)
    for x in rx:
        d.rounded_rectangle((x - 7, RY - 7, x + RW + 7, RY + RH + 7), 14, fill=(34, 18, 12), outline=(240, 194, 80), width=3)
    mask = PI.new("L", (RW, RH), 0); md = PD.Draw(mask)
    for y in range(RH):
        md.line([(0, y), (RW, y)], fill=int(150 * max(0.0, 1 - min(y, RH - 1 - y) / (RH * 0.30)) ** 1.6))
    shade = PI.new("RGBA", (RW, RH), (0, 0, 0, 0)); shade.putalpha(mask)
    pay = PI.new("RGBA", (W, H), (0, 0, 0, 0)); pd = PD.Draw(pay); cy = RY + RH // 2
    pd.line([(rx[0] - 3, cy), (rx[2] + RW + 3, cy)], fill=(255, 70, 70, 150), width=2)
    pd.polygon([(rx[0] - 15, cy - 8), (rx[0] - 15, cy + 8), (rx[0] - 4, cy)], fill=(255, 210, 80, 255)); pd.polygon([(rx[2] + RW + 15, cy - 8), (rx[2] + RW + 15, cy + 8), (rx[2] + RW + 4, cy)], fill=(255, 210, 80, 255))
    _SLOT_ASSETS.update(sprites=sprites, base=base, shade=shade, pay=pay, rx=rx, W=W, H=H, RW=RW, RH=RH, RY=RY, SPR=SPR)
    return _SLOT_ASSETS

def render_slots(reels, mult, kind, seed=0):
    """reels: 3 symbols, mult: payout multiplier, kind: 'jackpot' | 'triple' | 'pair' | 'none'. Returns (gif bytes, final png bytes, seconds)."""
    A = _slot_assets(); W, H, RW, RH, RY, rx, PITCH, DT = A["W"], A["H"], A["RW"], A["RH"], A["RY"], A["rx"], 100, 0.05
    SPR, GOLD, WHITE = A["SPR"], (255, 226, 90), (255, 255, 255)
    rng = random.Random(seed or sum(ord(c) for c in "".join(reels)) + int(mult * 7))
    stops = [1.3, 2.0, 2.7 + (0.9 if reels[0] == reels[1] else 0.0)]
    Ks = [int(s * 14) + 3 for s in stops]
    def strip(target, K):
        N = K + 5
        st = PI.new("RGB", (RW, N * PITCH), (252, 236, 196))
        for c in range(N):
            sym = target if c - 2 == K else rng.choices(_SLOT_SYMBOLS, weights=_SLOT_WEIGHTS)[0]
            st.paste(A["sprites"][sym], ((RW - SPR) // 2, (N - 1 - c) * PITCH + (PITCH - SPR) // 2), A["sprites"][sym])
        return st
    def sample(st, o, K):
        return st.transform((RW, RH), PI.Transform.AFFINE, (1, 0, 0, 0, 1, (K + 4 - (o + 2)) * PITCH - (RH - PITCH) / 2), resample=PI.Resampling.BILINEAR)
    def reel(st, o0, o1, K):
        px = abs(o1 - o0) * PITCH
        if px < 8:
            return sample(st, o1, K)
        n = min(10, int(px / 8) + 1)
        acc = sample(st, o0, K)
        for s in range(1, n):
            acc = PI.blend(acc, sample(st, o0 + (o1 - o0) * s / (n - 1), K), 1.0 / (s + 1))
        return acc
    def offset(t, ts, K):
        if t >= ts:
            tau = t - ts
            return K + 0.10 * math.sin(tau * 26) * math.exp(-tau * 9)
        return K * (1 - (1 - t / ts) ** 3)
    def sparkle(d, x, y, s, a):
        d.polygon([(x, y - s), (x + s * .22, y - s * .22), (x + s, y), (x + s * .22, y + s * .22), (x, y + s), (x - s * .22, y + s * .22), (x - s, y), (x - s * .22, y - s * .22)], fill=(255, 250, 200, a))
    strips = [strip(reels[i], Ks[i]) for i in range(3)]
    big = kind in ("jackpot", "triple")
    win = [0, 1, 2] if big else ([i for i in range(3) if reels.count(reels[i]) >= 2] if (mult > 0 and kind == "pair") else [])
    n_spin = int((stops[2] + 0.35) / DT) + 1
    n_fx = 34 if kind == "jackpot" else 22 if win else 7
    glow = PI.new("RGBA", (W, H), (0, 0, 0, 0)); gd = PD.Draw(glow)
    for i in win:
        gd.rounded_rectangle((rx[i] - 4, RY - 4, rx[i] + RW + 4, RY + RH + 4), 12, outline=(255, 226, 90, 255) if (mult >= 2 or big) else (160, 220, 255, 255), width=7)
    glow = glow.filter(PFl.GaussianBlur(5)); ga = glow.split()[3]
    sparks = [(rx[i] + RW / 2 + rng.uniform(-50, 50), RY + RH / 2 + rng.uniform(-58, 58), rng.randint(0, n_fx // 2), rng.randint(7, 11), rng.uniform(7, 15)) for i in win for _ in range(7)]
    confetti = [(rng.uniform(0, W), rng.uniform(-H, 0), rng.uniform(-40, 40), rng.uniform(150, 260), rng.uniform(0, 6.28), rng.uniform(-6, 6),
                 rng.choice([(255, 80, 80), (255, 210, 60), (90, 200, 255), (130, 255, 140), (255, 120, 230)]), rng.uniform(5, 9)) for _ in range(70)] if kind == "jackpot" else []
    frames, prev = [], [0.0] * 3
    for k in range(n_spin + n_fx):
        t = k * DT
        os_ = [offset(t, stops[i], Ks[i]) for i in range(3)]
        img = A["base"].copy()
        for i in range(3):
            r = reel(strips[i], prev[i], os_[i], Ks[i]).convert("RGBA")
            r.alpha_composite(A["shade"])
            img.paste(r.convert("RGB"), (rx[i], RY))
        prev = os_
        fx = k - n_spin + 1
        d = PD.Draw(img)
        for j in range(11):
            c = (255, 214, 90) if (j + k // 2) % 2 == 0 else (112, 82, 44)
            for x in (30 + j * 8, W - 30 - j * 8):
                d.ellipse((x - 3, 19, x + 3, 25), fill=c)
        flash = GOLD if (k // 2) % 2 == 0 else WHITE
        title, tc = ("JACKPOT!", flash) if (kind == "jackpot" and fx > 0) else ("WIN!", flash) if (big and fx > 0) else ("SLOTS", GOLD)
        d.text((W // 2, 24), title, font=_fx_font(26), fill=tc, anchor="mm", stroke_width=2, stroke_fill=(70, 30, 0))
        img = img.convert("RGBA")
        img.alpha_composite(A["pay"])
        if fx > 0 and win:
            pulse = 1.0 if fx >= n_fx else 0.55 + 0.45 * math.sin(fx * 0.9)
            g = glow.copy(); g.putalpha(ga.point(lambda v, p=pulse: int(v * p))); img.alpha_composite(g)
            if fx < n_fx:
                ov = PI.new("RGBA", (W, H), (0, 0, 0, 0)); od = PD.Draw(ov)
                for x, y, born, life, size in sparks:
                    age = fx - born
                    if 0 <= age < life:
                        sparkle(od, x, y, size * math.sin(math.pi * age / life), int(255 * (1 - age / life) ** 0.5))
                for x0, y0, vx, vy, rot, rs, col, sz in confetti:
                    tt = fx * DT; cx, cy, a = x0 + vx * tt, y0 + vy * tt, rot + rs * tt
                    if -10 < cy < H + 10:
                        od.polygon([(cx + sz * math.cos(a + q), cy + sz * .6 * math.sin(a + q)) for q in (0.8, 2.4, 3.9, 5.5)], fill=col + (235,))
                img.alpha_composite(ov)
        elif fx > 0:
            img.alpha_composite(PI.new("RGBA", (W, H), (0, 0, 0, int(55 * min(1, fx / 6)))))
        frames.append(img.convert("RGB"))
    return _fx_gif(frames, int(DT * 1000)), _fx_png(frames[-1]), (len(frames) - 1) * DT

# ---------------- coin flip ----------------
def render_coin(result, won, word):
    """A coin is tossed, spins and lands on `result` ('heads'|'tails'). word: the localised label shown at the end."""
    W, H, R, S, DT = 400, 240, 54, 4, 0.05
    def face(kind):
        sz = 2 * R * S; im = PI.new("RGBA", (sz, sz), (0, 0, 0, 0)); d = PD.Draw(im); c = sz / 2
        for r, col in ((R, (150, 96, 10)), (R - 2, (255, 214, 80)), (R - 8, (214, 150, 20)), (R - 11, (255, 228, 120))):
            d.ellipse((c - r * S, c - r * S, c + r * S, c + r * S), fill=col + (255,))
        if kind == "heads":
            pts = [(-24, 12), (-24, -14), (-12, -2), (0, -20), (12, -2), (24, -14), (24, 12)]
            d.polygon([(c + x * S, c + y * S) for x, y in pts], fill=(150, 90, 0, 255)); d.rectangle((c - 24 * S, c + 12 * S, c + 24 * S, c + 20 * S), fill=(150, 90, 0, 255))
            for x, y in ((-24, -14), (0, -20), (24, -14)):
                d.ellipse((c + (x - 4) * S, c + (y - 4) * S, c + (x + 4) * S, c + (y + 4) * S), fill=(150, 90, 0, 255))
            d.polygon([(c + (x * 0.8) * S, c + (y * 0.8 - 1) * S) for x, y in pts[:-1] + [(24, 8)]], fill=(255, 236, 140, 200))
        else:
            d.text((c, c - 2 * S), "V", font=_fx_font(int(46 * S)), fill=(150, 90, 0, 255), anchor="mm")
            for i in range(12):
                a = math.radians(i * 30)
                d.ellipse((c + (R - 6) * math.cos(a) * S - 2 * S, c + (R - 6) * math.sin(a) * S - 2 * S, c + (R - 6) * math.cos(a) * S + 2 * S, c + (R - 6) * math.sin(a) * S + 2 * S), fill=(150, 90, 0, 255))
        return im.resize((2 * R, 2 * R), PI.Resampling.LANCZOS)
    heads, tails = face("heads"), face("tails")
    bg = PI.new("RGB", (W, H)); bd = PD.Draw(bg)
    for y in range(H):
        bd.line([(0, y), (W, y)], fill=_fx_lerp((40, 28, 84), (12, 8, 30), y / (H - 1)))
    rng = random.Random(5)
    for _ in range(60):
        bd.point((rng.randrange(W), rng.randrange(H)), fill=rng.choice([(96, 74, 156), (126, 104, 196)]))
    bd.rounded_rectangle((5, 5, W - 6, H - 6), 22, outline=(236, 186, 64), width=3)
    floor_y, cx, N, T_fly = 188, W // 2, (8 if result == "heads" else 9), 1.6
    n_fly, frames = int(T_fly / DT), []
    for k in range(n_fly + 14 + 14):
        t = k * DT
        if t <= T_fly:
            p = t / T_fly; lift = 4 * p * (1 - p); th = math.pi * N * (1 - (1 - p) ** 2)
        else:
            tau = t - T_fly; lift = 0.11 * abs(math.sin(tau * 9)) * math.exp(-tau * 4); th = math.pi * N
        cosv = math.cos(th); sc = max(0.05, abs(cosv)); cy = floor_y - R - 120 * lift
        img = bg.copy().convert("RGBA"); ov = PI.new("RGBA", (W, H), (0, 0, 0, 0)); od = PD.Draw(ov)
        sw = R * (1.0 - 0.45 * lift * 2.0); od.ellipse((cx - sw, floor_y - 6, cx + sw, floor_y + 8 + 4 * (1 - lift)), fill=(0, 0, 0, int(110 * (1 - lift))))
        img.alpha_composite(ov)
        spr = (heads if cosv > 0 else tails).resize((2 * R, max(2, int(2 * R * sc))), PI.Resampling.BILINEAR)
        thick = int(9 * math.sqrt(max(0.0, 1 - sc * sc))); d = PD.Draw(img); hh = spr.size[1] / 2
        for i in range(thick, 0, -1):
            d.ellipse((cx - R, cy - hh + i, cx + R, cy + hh + i), fill=(150, 96, 10, 255))
        img.alpha_composite(spr, (int(cx - R), int(cy - hh)))
        fx = k - (n_fly + 14)
        if fx >= 0:
            a = int(255 * min(1, (fx + 1) / 5)); od2 = PD.Draw(img)
            od2.text((cx, 226 - 22), word.upper(), font=_fx_font(30), fill=(255, 226, 90, a), anchor="mm", stroke_width=2, stroke_fill=(70, 30, 0, a))
            if won:
                for q in range(6):
                    ang = q * 1.05 + fx * 0.3; rr = 70 + fx * 5; sx, sy = cx + rr * math.cos(ang), floor_y - R + rr * 0.55 * math.sin(ang)
                    s = 9 * math.sin(math.pi * min(1, (fx + 1) / 14)); od2.polygon([(sx, sy - s), (sx + s * .25, sy - s * .25), (sx + s, sy), (sx + s * .25, sy + s * .25), (sx, sy + s), (sx - s * .25, sy + s * .25), (sx - s, sy), (sx - s * .25, sy - s * .25)], fill=(255, 250, 200, 230))
            else:
                img.alpha_composite(PI.new("RGBA", (W, H), (60, 0, 10, int(60 * min(1, (fx + 1) / 6)))))
        frames.append(img.convert("RGB"))
    return _fx_gif(frames, int(DT * 1000)), _fx_png(frames[-1]), (len(frames) - 1) * DT
