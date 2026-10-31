# ---------------- moderation banners (animated, rendered once per action + language, then cached) ----------------
_BN_ACC = {"ban": (237, 66, 69), "kick": (230, 126, 34), "timeout": (254, 231, 92), "mute": (149, 165, 166), "warn": (241, 196, 15), "pardon": (87, 242, 135)}
def _bn_icon(style):
    U, im = 4, PI.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = PD.Draw(im); acc, white, dark = _BN_ACC[style] + (255,), (245, 247, 250, 255), (22, 24, 34, 255)
    if style == "ban":                                  # gavel + block
        lay = PI.new("RGBA", im.size, (0, 0, 0, 0)); ld = PD.Draw(lay)
        ld.rounded_rectangle((44 * U, 38 * U, 56 * U, 94 * U), 5 * U, fill=(214, 172, 120, 255)); ld.rounded_rectangle((20 * U, 10 * U, 80 * U, 40 * U), 6 * U, fill=acc)
        ld.rounded_rectangle((15 * U, 7 * U, 28 * U, 43 * U), 5 * U, fill=white); ld.rounded_rectangle((72 * U, 7 * U, 85 * U, 43 * U), 5 * U, fill=white)
        im.alpha_composite(lay.rotate(35, resample=PI.Resampling.BICUBIC, center=(50 * U, 50 * U)))
        d.rounded_rectangle((6 * U, 82 * U, 64 * U, 96 * U), 4 * U, fill=(96, 102, 122, 255)); d.rounded_rectangle((6 * U, 82 * U, 64 * U, 87 * U), 3 * U, fill=(140, 147, 168, 255))
    elif style == "kick":                               # door + arrow
        d.rounded_rectangle((16 * U, 12 * U, 58 * U, 92 * U), 4 * U, outline=white, width=int(5 * U)); d.polygon([(58 * U, 12 * U), (78 * U, 24 * U), (78 * U, 80 * U), (58 * U, 92 * U)], fill=acc)
        d.rectangle((34 * U, 46 * U, 70 * U, 58 * U), fill=white); d.polygon([(66 * U, 34 * U), (94 * U, 52 * U), (66 * U, 70 * U)], fill=white)
    elif style == "timeout":                            # clock
        d.ellipse((12 * U, 14 * U, 88 * U, 90 * U), fill=dark, outline=acc, width=int(8 * U)); d.rounded_rectangle((43 * U, 4 * U, 57 * U, 13 * U), 2 * U, fill=acc)
        d.line([(50 * U, 52 * U), (50 * U, 30 * U)], fill=white, width=int(6 * U)); d.line([(50 * U, 52 * U), (68 * U, 62 * U)], fill=white, width=int(6 * U)); d.ellipse((44 * U, 46 * U, 56 * U, 58 * U), fill=acc)
    elif style == "mute":                               # speaker with a slash
        d.polygon([(12 * U, 40 * U), (32 * U, 40 * U), (54 * U, 20 * U), (54 * U, 84 * U), (32 * U, 64 * U), (12 * U, 64 * U)], fill=white)
        d.arc((50 * U, 34 * U, 82 * U, 70 * U), -60, 60, fill=white, width=int(5 * U)); d.line([(14 * U, 90 * U), (90 * U, 14 * U)], fill=dark, width=int(15 * U)); d.line([(14 * U, 90 * U), (90 * U, 14 * U)], fill=acc, width=int(8 * U))
    elif style == "warn":                               # warning triangle
        d.polygon([(50 * U, 8 * U), (96 * U, 88 * U), (4 * U, 88 * U)], fill=acc, outline=acc, width=int(6 * U), ); d.polygon([(50 * U, 18 * U), (86 * U, 82 * U), (14 * U, 82 * U)], fill=acc)
        d.rounded_rectangle((45 * U, 36 * U, 55 * U, 62 * U), 4 * U, fill=dark); d.ellipse((44 * U, 68 * U, 56 * U, 80 * U), fill=dark)
    else:                                               # pardon: check mark
        d.ellipse((10 * U, 10 * U, 90 * U, 90 * U), fill=acc); d.line([(28 * U, 52 * U), (44 * U, 68 * U), (74 * U, 34 * U)], fill=dark, width=int(10 * U), joint="curve")
    return im

def render_banner(style, word):
    """Short animated banner: icon pops in, impact ring, the word slides in. Returns GIF bytes (holds the last frame)."""
    W, H, DT = 480, 110, 0.05
    acc = _BN_ACC[style]
    icon = _bn_icon(style).resize((168, 168), PI.Resampling.LANCZOS)
    bg = PI.new("RGB", (W, H)); bd = PD.Draw(bg)
    for y in range(H):
        bd.line([(0, y), (W, y)], fill=_fx_lerp((30, 32, 44), (16, 17, 25), y / (H - 1)))
    bg = bg.convert("RGBA"); glow = PI.new("RGBA", (W, H), (0, 0, 0, 0)); PD.Draw(glow).ellipse((-50, -30, 190, 140), fill=acc + (120,))
    bg.alpha_composite(glow.filter(PFl.GaussianBlur(26))); PD.Draw(bg).rectangle((0, 0, 5, H), fill=acc + (255,))
    size = 46
    while size > 18 and _fx_font(size).getlength(word) > 290:
        size -= 2
    font = _fx_font(size); eo3 = lambda x: 1 - (1 - x) ** 3
    eob = lambda x: 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2
    clamp = lambda x: max(0.0, min(1.0, x))
    frames = []
    for k in range(30):
        t = k * DT
        img = bg.copy(); sc = 0.35 + 0.65 * eob(clamp(t / 0.4))
        ang = -40 * (1 - eo3(clamp(t / 0.35))) if style == "ban" else (10 * math.sin(t * 45) * math.exp(-t * 3) if style == "warn" else 0)
        side = max(8, int(84 * sc)); ic = icon.rotate(ang, resample=PI.Resampling.BICUBIC).resize((side, side), PI.Resampling.LANCZOS)
        ov = PI.new("RGBA", (W, H), (0, 0, 0, 0)); od = PD.Draw(ov)
        if t >= 0.30:
            rr = 20 + (t - 0.30) * 170; od.ellipse((74 - rr, 55 - rr, 74 + rr, 55 + rr), outline=acc + (int(200 * max(0.0, 1 - (t - 0.30) / 0.5)),), width=3)
        img.alpha_composite(ov); img.paste(ic, (74 - side // 2, 55 - side // 2), ic)
        ov = PI.new("RGBA", (W, H), (0, 0, 0, 0)); od = PD.Draw(ov); p = clamp((t - 0.25) / 0.45); a = int(255 * clamp((t - 0.25) / 0.3)); x = 140 + 90 * (1 - eo3(p))
        od.text((x + 2, 52), word, font=font, fill=(0, 0, 0, int(a * 0.6)), anchor="lm"); od.text((x, 50), word, font=font, fill=(255, 255, 255, a), anchor="lm")
        od.rectangle((140, 78, 140 + 230 * eo3(clamp((t - 0.5) / 0.5)), 81), fill=acc + (255,))
        if 0.30 <= t < 0.50:
            od.rectangle((0, 0, W, H), fill=(255, 255, 255, int(90 * (1 - (t - 0.30) / 0.2))))
        img.alpha_composite(ov); frames.append(img.convert("RGB"))
    return _fx_gif(frames, int(DT * 1000), last_ms=60000, colors=120)

# ---------------- cards ----------------
def _fx_tier(level):
    for lim, a, b in ((5, (88, 101, 242), (140, 160, 255)), (10, (26, 188, 156), (100, 235, 210)), (20, (155, 89, 182), (210, 150, 240)), (30, (255, 107, 53), (255, 180, 110))):
        if level < lim:
            return a, b
    return (241, 196, 15), (255, 232, 130)

def render_rank(avatar, name, level, xp, progress, needed, pos, chips, T):
    cv = _Cv(900, 260, 2); acc, acc2 = _fx_tier(level); pct = max(0.0, min(1.0, progress / needed)) if needed else 1.0
    cv.grad((0, 0, 900, 260), (30, 32, 46), (14, 15, 22), vertical=True)
    for i in range(9):
        cv.ell((-140 + i * 9, -160 + i * 9, 340 - i * 9, 320 - i * 9), fill=acc + (7,))
    cv.rr((3, 3, 897, 257), 24, outline=acc + (170,), width=3)
    cv.ell((130 - 98, 130 - 98, 130 + 98, 130 + 98), outline=(255, 255, 255, 34), width=10)
    if pct > 0:
        cv.d.arc(cv.box((130 - 98, 130 - 98, 130 + 98, 130 + 98)), -90, -90 + 360 * pct, fill=acc, width=int(10 * cv.k))
    cv.avatar(avatar, 130, 130, 84, name, acc)
    cv.text((250, 52), cv.safe(name, 38, 380), 38, (255, 255, 255), "lm")
    cv.text((872, 26), T["rank"], 14, (150, 156, 175), "ra"); cv.text((872, 36), f"#{pos}", 44, (255, 255, 255), "ra")
    cv.text((742, 26), T["level"], 14, (150, 156, 175), "ra"); cv.text((742, 36), str(level), 44, acc2, "ra")
    cv.text((872, 106), f"{progress:,} / {needed:,} XP", 18, (205, 210, 225), "rm", bold=False)
    cv.rr((250, 122, 872, 152), 15, fill=(255, 255, 255, 28))
    w = max(34, 622 * pct)
    cv.grad((250, 122, 250 + w, 152), acc, acc2, radius=15)
    if w > 80:
        cv.text((250 + w - 12, 137), f"{int(pct * 100)}%", 15, (255, 255, 255), "rm")
    n = max(1, len(chips)); gap = 10; cw = (622 - gap * (n - 1)) / n
    for i, (lab, val) in enumerate(chips):
        x = 250 + i * (cw + gap)
        cv.rr((x, 172, x + cw, 236), 14, fill=(255, 255, 255, 22)); cv.text((x + cw / 2, 189), lab, 12, (150, 156, 175), "mm"); cv.text((x + cw / 2, 214), val, 23, (255, 255, 255), "mm")
    return _fx_png(cv.out())

def render_levelup(avatar, name, level, T):
    cv = _Cv(640, 200, 2); gold, gold2 = (241, 196, 15), (255, 232, 130); rng = random.Random(level)
    cv.grad((0, 0, 640, 200), (40, 32, 16), (16, 13, 8), vertical=True)
    for _ in range(46):
        x, y, s = rng.uniform(0, 640), rng.uniform(0, 200), rng.uniform(3, 6); col = rng.choice([(255, 90, 90), (255, 210, 60), (90, 200, 255), (130, 255, 140), (255, 120, 230)])
        cv.rr((x, y, x + s * 1.6, y + s), 1, fill=col + (150,))
    cv.rr((3, 3, 637, 197), 22, outline=gold + (190,), width=3)
    cv.ell((100 - 72, 100 - 72, 100 + 72, 100 + 72), outline=gold + (255,), width=6); cv.avatar(avatar, 100, 100, 64, name, gold)
    cv.text((190, 50), T["title"], 38, gold2, "lm"); cv.text((190, 88), T["level"], 14, (170, 160, 130), "lm")
    cv.text((190, 128), str(level), 66, (255, 255, 255), "lm"); w = cv.width(str(level), 66) + 190
    cv.d.polygon([(int((w + 18) * cv.k), int(140 * cv.k)), (int((w + 38) * cv.k), int(140 * cv.k)), (int((w + 28) * cv.k), int(118 * cv.k))], fill=gold + (255,))
    cv.text((190, 176), cv.safe(name, 18, 400), 18, (190, 192, 205), "lm", bold=False)
    return _fx_png(cv.out())

def render_leaderboard(rows, title, guild_name):
    n = len(rows); H = 100 + 62 * n + 14; cv = _Cv(760, H, 2); acc, acc2 = (255, 107, 53), (255, 180, 110)
    cv.grad((0, 0, 760, H), (30, 32, 46), (14, 15, 22), vertical=True); cv.rr((3, 3, 757, H - 3), 22, outline=acc + (150,), width=3)
    cv.text((30, 48), title, 32, (255, 255, 255), "lm"); cv.text((730, 48), cv.safe(guild_name, 16, 260), 16, (150, 156, 175), "rm", bold=False)
    cv.rr((30, 76, 730, 79), 1, fill=acc + (255,))
    medal = {1: (255, 206, 60), 2: (200, 206, 218), 3: (205, 127, 50)}
    for i, r in enumerate(rows):
        y = 94 + i * 62
        cv.rr((20, y, 740, y + 54), 14, fill=(255, 255, 255, 16 if i % 2 == 0 else 9))
        col = medal.get(r["rank"], (70, 74, 92)); cv.ell((34, y + 11, 66, y + 43), fill=col + (255,))
        cv.text((50, y + 27), str(r["rank"]), 16, (30, 30, 40) if r["rank"] in medal else (255, 255, 255), "mm")
        cv.avatar(r.get("avatar"), 98, y + 27, 20, r["name"], col)
        cv.text((130, y + 19), cv.safe(r["name"], 20, 300), 20, (255, 255, 255), "lm")
        cv.rr((130, y + 36, 430, y + 42), 3, fill=(255, 255, 255, 30)); cv.grad((130, y + 36, 130 + max(8, 300 * r["frac"]), y + 42), acc, acc2, radius=3)
        cv.text((600, y + 27), f"{r['label']} {r['level']}", 17, acc2, "rm"); cv.text((726, y + 27), f"{r['xp']:,} XP", 19, (255, 255, 255), "rm")
    return _fx_png(cv.out())
