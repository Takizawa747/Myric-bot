"""Builds the static site (site/) from bot.py's HELP_TEXT and the two policy markdown files. Run: python3 dev-tools/make_site.py"""
import ast, base64, html, os, re
from html.parser import HTMLParser
OUT = "/mnt/user-data/outputs"; SUPPORT = "https://discord.gg/hxYWsFVWp8"
bot = open(f"{OUT}/bot.py", encoding="utf-8").read(); tree = ast.parse(bot)
m = re.search(r'([A-Za-z0-9_\-]{20,})\.[A-Za-z0-9_\-]{5,8}\.[A-Za-z0-9_\-]{20,}', bot)       # client id = first token segment (token is never printed)
cid = base64.urlsafe_b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)).decode() if m else None
perms = sum(1 << b for b in (0, 1, 2, 4, 6, 7, 10, 11, 13, 14, 15, 16, 17, 18, 27, 28, 30, 40))
INVITE = f"https://discord.com/oauth2/authorize?client_id={cid or 'YOUR_CLIENT_ID'}&permissions={perms}&scope=bot%20applications.commands"
def assigned(name): return next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
HT = eval(compile(ast.Expression(assigned("HELP_TEXT")), "help", "eval"), {"_SETUP_LIST": assigned("_SETUP_LIST").value})["en"]
CSS = """:root{--bg:#0f1117;--card:#181b24;--line:#262a36;--text:#e6e8ee;--muted:#9aa1b2;--brand:#5865f2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:#8ea1ff}main,.nav,footer{max-width:1040px;margin:0 auto;padding:0 20px}
.nav{display:flex;justify-content:space-between;align-items:center;height:64px;flex-wrap:wrap}.brand{font-weight:800;font-size:1.3rem;color:var(--text);text-decoration:none}
.nav nav a{margin-left:18px;color:var(--muted);text-decoration:none}.nav nav a:hover{color:var(--text)}
.hero{text-align:center;padding:72px 0 40px}.hero h1{font-size:clamp(2rem,6vw,3.2rem);line-height:1.15;margin:0 0 16px}
.hero p{color:var(--muted);max-width:640px;margin:0 auto 24px;font-size:1.1rem}
.btn{display:inline-block;padding:12px 22px;border-radius:10px;border:1px solid var(--line);color:var(--text);text-decoration:none;font-weight:600;margin:4px}.btn.primary{background:var(--brand);border-color:var(--brand)}
h2{margin:56px 0 18px;font-size:1.6rem}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}.card h3{margin:0 0 8px;font-size:1.1rem}.card p,.card div{margin:0;color:var(--muted);font-size:.95rem}
code{background:#10131b;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:.88em;color:#cfd6ff}.cmds .card div{line-height:2}
footer{padding:40px 20px;color:var(--muted);text-align:center;font-size:.9rem;border-top:1px solid var(--line);margin-top:64px}
.doc{max-width:760px;margin:0 auto;padding:24px 20px 0}.doc h1{font-size:2rem}.doc h2{font-size:1.3rem;margin-top:32px}.doc h3{font-size:1.05rem;margin:22px 0 6px}.doc li{margin:4px 0}.doc hr{border:0;border-top:1px solid var(--line);margin:32px 0}
"""
def page(title, body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="Versa is a free multi-purpose Discord bot: moderation, economy and casino, tickets, polls, giveaways and honeypot protection in English, Turkish and Russian."><meta name="theme-color" content="#0f1117"><link rel="stylesheet" href="style.css"></head>
<body><header class="nav"><a class="brand" href="index.html">Versa</a><nav><a href="index.html#features">Features</a><a href="index.html#commands">Commands</a><a href="privacy.html">Privacy</a><a href="terms.html">Terms</a></nav></header>
{body}
<footer>Versa is not affiliated with Discord Inc. · <a href="privacy.html">Privacy Policy</a> · <a href="terms.html">Terms of Service</a> · <a href="{SUPPORT}">Support</a></footer></body></html>"""
FEATS = [("🛡️ Moderation", "Ban, kick, mute, timeout and warn with automatic punishments, case history, channel lock, and timed bans that survive restarts."),
 ("💰 Economy &amp; Store", "Daily, work, rob and pay with a bank, plus a server store whose items can give a role. Amounts accept all, half, 25% or 1.5k."),
 ("🎰 Casino", "Blackjack with buttons, slots where every emoji has its own value, and a coin flip that is exactly 50/50."),
 ("📊 Leveling", "XP for chatting, level roles, leaderboards and a difficulty setting for each server."),
 ("🎫 Tickets", "Private ticket channels with a panel whose buttons you choose, a staff role and a close button."),
 ("🗳️ Polls &amp; Giveaways", "Button polls with live result bars that admins can close, and giveaways with winners and timers."),
 ("🍯 Protection", "A honeypot channel that bans spam bots on the spot, a strict counting channel and role persist."),
 ("🌍 3 languages", "Every server picks English, Türkçe or Русский and the bot answers in it.")]
def inline_cmd(t): return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(t.replace("{p}", "."), quote=False)).replace("\n", "<br>")
cmd_cards = "".join(f'<div class="card"><h3>{html.escape(t)}</h3><div>{inline_cmd(b)}</div></div>' for t, b in HT.values())
feat_cards = "".join(f'<div class="card"><h3>{t}</h3><p>{d}</p></div>' for t, d in FEATS)
index = page("Versa — Discord bot for moderation, economy, tickets and games", f"""<main>
<section class="hero"><h1>One bot for your whole Discord server</h1>
<p>Moderation, economy &amp; casino, tickets, polls, giveaways and spam-bot protection — free, in English, Türkçe and Русский.</p>
<a class="btn primary" href="{INVITE}">Add to Discord</a><a class="btn" href="{SUPPORT}">Join the support server</a></section>
<section id="features"><h2>Features</h2><div class="grid">{feat_cards}</div></section>
<section id="commands"><h2>Commands</h2><p class="muted">The default prefix is <code>.</code> (change it with <code>/setup prefix</code>). Slash commands start with <code>/</code>. Type <code>/help</code> in Discord for the same list.</p><div class="grid cmds">{cmd_cards}</div></section>
<section id="start"><h2>Get started</h2><div class="grid"><div class="card"><h3>1. Add the bot</h3><p>Press “Add to Discord” and pick your server. Keep the Versa role above the roles it should manage.</p></div>
<div class="card"><h3>2. Set it up</h3><p>Use <code>/setup log</code>, <code>/setup ticket</code>, <code>/language</code> and <code>/setup view</code> to see everything you can change.</p></div>
<div class="card"><h3>3. Need help?</h3><p>Join the <a href="{SUPPORT}">support server</a> or use <code>/modmail</code> to write to the developer.</p></div></div></section></main>""")
def link(u): return {"./privacy_policy.md": "privacy.html", "./terms_of_service.md": "terms.html"}.get(u, u)
def md_to_html(md):
    out, lst = [], False
    def inline(t):
        t = html.escape(t, quote=False); t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t); t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<em>\1</em>", t)
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{link(m.group(2))}">{m.group(1)}</a>', t)
    for line in md.split("\n"):
        if line.startswith("- "):
            if not lst: out.append("<ul>"); lst = True
            out.append(f"<li>{inline(line[2:])}</li>"); continue
        if lst: out.append("</ul>"); lst = False
        if not line.strip(): continue
        out.append("<hr>" if line.startswith("---") else f"<h3>{inline(line[4:])}</h3>" if line.startswith("### ") else f"<h2>{inline(line[3:])}</h2>" if line.startswith("## ")
                   else f"<h1>{inline(line[2:])}</h1>" if line.startswith("# ") else f"<p>{inline(line)}</p>")
    if lst: out.append("</ul>")
    return "\n".join(out)
os.makedirs(f"{OUT}/site", exist_ok=True)
open(f"{OUT}/site/style.css", "w", encoding="utf-8").write(CSS); open(f"{OUT}/site/index.html", "w", encoding="utf-8").write(index)
for md, name, title in (("privacy_policy.md", "privacy.html", "Privacy Policy — Versa"), ("terms_of_service.md", "terms.html", "Terms of Service — Versa")):
    open(f"{OUT}/site/{name}", "w", encoding="utf-8").write(page(title, f'<main class="doc">{md_to_html(open(f"{OUT}/{md}", encoding="utf-8").read())}</main>'))
class P(HTMLParser):
    def __init__(self): super().__init__(); self.stack, self.bad = [], []
    def handle_starttag(self, t, a):
        if t not in ("meta", "link", "br", "hr"): self.stack.append(t)
    def handle_endtag(self, t):
        if not self.stack or self.stack.pop() != t: self.bad.append(t)
for f in ("index.html", "privacy.html", "terms.html"):
    h = open(f"{OUT}/site/{f}", encoding="utf-8").read(); c = P(); c.feed(h)
    print(f"{f:13} {len(h):6} bytes | unbalanced tags: {c.bad or 'none'} | placeholder left: {'YOUR_CLIENT_ID' in h or '{{' in h}")
print("client id found:", bool(cid), "| permissions:", perms, "| 'all/half' in commands:", "half" in index)
