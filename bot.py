# ============================================================
# VERSA BOT — Complete Rebuild
# ============================================================
import os, re, sys, json, math, random, asyncio
import contextvars, io, zipfile, collections, sqlite3, threading, signal, unicodedata, decimal
import time as _time
from collections import deque
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

if discord.version_info < (2, 6):
    sys.exit("discord.py 2.6 or newer is needed. Update it: pip install -U discord.py --break-system-packages")

# ============================================================
# CONSTANTS
# ============================================================
def _read_token():
    """Token comes from the VERSA_TOKEN env var or token.txt; never write the token into this file."""
    tok = os.environ.get("VERSA_TOKEN", "").strip()
    if not tok and os.path.exists("token.txt"):
        try:
            tok = open("token.txt", encoding="utf-8").read().strip()
        except Exception:
            tok = ""
    return tok

BOT_TOKEN = _read_token()
if not BOT_TOKEN and "--check" not in sys.argv:
    sys.exit("No bot token found. Put it in token.txt next to bot.py (one line, nothing else) or set the VERSA_TOKEN environment variable.")
BOT_CREATOR_ID = 1365571735222747280
SUPPORT_LINK   = "https://discord.gg/hxYWsFVWp8"


LEVEL_DIFFICULTIES = {
    "easiest":   {"label":"🟢 Easiest",   "xp_min":50,"xp_max":80, "divisor":30},
    "very_easy": {"label":"🟢 Very Easy", "xp_min":35,"xp_max":55, "divisor":50},
    "easy":      {"label":"🔵 Easy",      "xp_min":20,"xp_max":35, "divisor":70},
    "normal":    {"label":"⚪ Normal",    "xp_min":10,"xp_max":25, "divisor":100},
    "hard":      {"label":"🟠 Hard",      "xp_min":5, "xp_max":15, "divisor":150},
    "very_hard": {"label":"🔴 Very Hard", "xp_min":3, "xp_max":8,  "divisor":220},
    "hardest":   {"label":"💀 Hardest",   "xp_min":1, "xp_max":3,  "divisor":350},
}

DEFAULT_TICKET_BUTTONS = [
    {"label":"🆘 General Support","category":"General Support","emoji":"🆘","style":"blurple"},
    {"label":"🐛 Bug Report",     "category":"Bug Report",     "emoji":"🐛","style":"red"},
    {"label":"💡 Suggestion",      "category":"Suggestion",     "emoji":"💡","style":"green"},
    {"label":"❓ Other",            "category":"Other",          "emoji":"❓","style":"grey"},
]



DEFAULT_FEATURES = {
    "economy":"enabled","casino":"enabled","estore":"disabled",
    "leveling":"enabled","tickets":"enabled","giveaway":"enabled",
    "flag":"enabled","poll":"enabled",
    "reaction_roles":"enabled","counting":"disabled","vcxp":"disabled","dmnotices":"disabled",
}

FEATURE_LABELS = {
    "economy":"💰 Economy","casino":"🎰 Casino","estore":"🛒 Economy Store",
    "leveling":"📊 Leveling","tickets":"🎫 Tickets","giveaway":"🎉 Giveaway",
    "flag":"🏳️ Flag Game","poll":"📋 Poll",
    "reaction_roles":"🎭 Reaction Roles","counting":"🔢 Counting","vcxp":"🎙️ Voice XP","dmnotices":"📨 Moderation DMs",
}

# ============================================================
# DATABASE FILES
# ============================================================
SETTINGS_FILE      = "settings.json"
ECONOMY_FILE       = "economy.json"
LEVELS_FILE        = "levels.json"
MSGSTATS_FILE      = "msgstats.json"
WARNS_FILE         = "warns.json"
MODLOGS_FILE       = "modlogs.json"
BOT_BANS_FILE      = "bot_bans.json"
FLAG_SCORES_FILE   = "flag_scores.json"
GIVEAWAYS_FILE     = "giveaways.json"
REACTION_ROLES_FILE= "reaction_roles.json"
WHITELIST_FILE     = "whitelist.json"
ESTORE_FILE        = "estore.json"


# ============================================================
# STORAGE - SQLite (WAL) + in-memory cache, hidden behind the old load_json()/save_json()
#   * reads never touch the disk (the dicts below ARE the cache)
#   * only rows that changed are written, in a worker thread, in small batches
#   * the old *.json files are imported once and then left untouched as a backup
# ============================================================
DB_PATH = "versa.db"
_db_lock = threading.RLock()
_conn = None
# file name -> (store name, kind)   kind: global = one document | guild = one row per guild | nested = one row per guild+user
_STORE_BY_FILE = {
    "settings.json": ("settings", "guild"), "estore.json": ("estore", "guild"), "giveaways.json": ("giveaways", "guild"),
    "reaction_roles.json": ("reaction_roles", "guild"), "counting.json": ("counting", "guild"),
    "polls.json": ("polls", "guild"),
    "economy.json": ("economy", "nested"), "levels.json": ("levels", "nested"), "msgstats.json": ("msgstats", "nested"), "warns.json": ("warns", "nested"),
    "modlogs.json": ("modlogs", "nested"), "flag_scores.json": ("flag_scores", "nested"), "role_persist.json": ("role_persist", "nested"),
    "bot_bans.json": ("bot_bans", "global"), "whitelist.json": ("whitelist", "global"), "schedule.json": ("schedule", "global"),
}
_TOUCH_ALL_ON_SAVE = {"giveaways", "reaction_roles", "estore", "counting"}      # tiny stores: save_*() re-checks every row
_stores, _kinds, _last, _touched = {}, {}, {}, {}

def _atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def _load_plain_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        try:
            os.replace(path, f"{path}.corrupt-{int(_time.time())}")
        except Exception:
            pass
        print(f"[DB] {path} was unreadable ({e}); moved aside, starting empty")
        return {}

def _save_plain_json(path, data):
    try:
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[DB] could not save {path}: {e}")

def _connect():
    global _conn
    with _db_lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.execute("CREATE TABLE IF NOT EXISTS kv (store TEXT NOT NULL, k1 TEXT NOT NULL, k2 TEXT NOT NULL, v TEXT NOT NULL, PRIMARY KEY (store, k1, k2)) WITHOUT ROWID")
            _conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, v TEXT)")
            _conn.commit()
        return _conn

def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def _rows_of(kind, data):
    if kind == "global":
        yield "", "", data
    elif kind == "guild":
        for k1, obj in data.items():
            yield k1, "", obj
    else:
        for k1, users in data.items():
            if isinstance(users, dict):
                for k2, obj in users.items():
                    yield k1, k2, obj

_UPSERT = "INSERT INTO kv(store, k1, k2, v) VALUES(?, ?, ?, ?) ON CONFLICT(store, k1, k2) DO UPDATE SET v = excluded.v"

def load_json(path):
    info = _STORE_BY_FILE.get(os.path.basename(path))
    if info is None:
        return _load_plain_json(path)
    name, kind = info
    if name in _stores:            # already loaded: the live dict is the source of truth - never swap it for a stale copy
        return _stores[name]
    conn = _connect()
    with _db_lock:
        rows = conn.execute("SELECT k1, k2, v FROM kv WHERE store = ?", (name,)).fetchall()
        initialised = conn.execute("SELECT 1 FROM meta WHERE key = ?", (f"init:{name}",)).fetchone()
    data = {}
    for k1, k2, v in rows:
        try:
            obj = json.loads(v)
        except Exception:
            continue
        if kind == "global":
            data = obj
        elif kind == "guild":
            data[k1] = obj
        else:
            data.setdefault(k1, {})[k2] = obj
    if not rows and not initialised:                      # first start with SQLite: import the old JSON file once
        old = _load_plain_json(path)
        data = old if isinstance(old, dict) else {}
        batch = [(name, k1, k2, _dumps(obj)) for k1, k2, obj in _rows_of(kind, data)]
        with _db_lock:
            conn.executemany(_UPSERT, batch)
            conn.execute("INSERT OR REPLACE INTO meta(key, v) VALUES(?, '1')", (f"init:{name}",))
            conn.commit()
        if batch:
            print(f"[DB] imported {os.path.basename(path)} into SQLite ({len(batch)} rows)")
    elif rows and not initialised:
        with _db_lock:
            conn.execute("INSERT OR REPLACE INTO meta(key, v) VALUES(?, '1')", (f"init:{name}",))
            conn.commit()
    _stores[name], _kinds[name], _touched[name] = data, kind, set()
    _last[name] = {(k1, k2): _dumps(obj) for k1, k2, obj in _rows_of(kind, data)}
    return data

def touch(store, k1="", k2=""):
    """Mark one row as possibly changed; the background flush writes it if it really changed."""
    t = _touched.get(store)
    if t is not None:
        t.add((k1, k2))

def touch_all(store):
    """Re-check every row of a store, including rows that were deleted since the last write."""
    if store in _stores:
        _touched[store].update((k1, k2) for k1, k2, _obj in _rows_of(_kinds[store], _stores[store]))
        _touched[store].update(_last[store])

def save_json(path, data):
    info = _STORE_BY_FILE.get(os.path.basename(path))
    if info is None:
        _save_plain_json(path, data)
        return
    name, kind = info
    if name in _stores and (kind == "global" or name in _TOUCH_ALL_ON_SAVE):
        touch_all(name)

def _collect_store(name, batch):
    """Serialize the given rows; return only the ones that differ from what is already on disk."""
    kind, data, last = _kinds[name], _stores[name], _last[name]
    changes = []
    for k1, k2 in batch:
        if kind == "global":
            obj = data
        elif kind == "guild":
            obj = data.get(k1)
        else:
            users = data.get(k1)
            obj = users.get(k2) if isinstance(users, dict) else None
        s = None if obj is None else _dumps(obj)
        if last.get((k1, k2)) != s:
            changes.append((name, k1, k2, s))
            if s is None:
                last.pop((k1, k2), None)
            else:
                last[(k1, k2)] = s
    return changes

def _write(changes):
    if not changes:
        return
    conn = _connect()
    with _db_lock:
        ups = [c for c in changes if c[3] is not None]
        dels = [(c[0], c[1], c[2]) for c in changes if c[3] is None]
        if ups:
            conn.executemany(_UPSERT, ups)
        if dels:
            conn.executemany("DELETE FROM kv WHERE store = ? AND k1 = ? AND k2 = ?", dels)
        conn.commit()

def _restore_failed(changes):
    for name, k1, k2, _v in changes:
        _last[name].pop((k1, k2), None)
        _touched[name].add((k1, k2))

def flush_now():
    """Synchronous full flush - used at shutdown / SIGTERM (nothing else is running then)."""
    try:
        changes = []
        for name in list(_stores):
            touch_all(name)
            _touched[name].update(_last[name])
            batch = list(_touched[name])
            _touched[name] = set()
            changes += _collect_store(name, batch)
        _write(changes)
    except Exception as e:
        print(f"[DB] final flush failed: {e}")





settings_db      = load_json(SETTINGS_FILE)
economy_db       = load_json(ECONOMY_FILE)
levels_db        = load_json(LEVELS_FILE)
msgstats_db      = load_json(MSGSTATS_FILE)
warns_db         = load_json(WARNS_FILE)
modlogs_db       = load_json(MODLOGS_FILE)
bot_bans_db      = load_json(BOT_BANS_FILE)
flag_scores_db   = load_json(FLAG_SCORES_FILE)
giveaways_db     = load_json(GIVEAWAYS_FILE)
reaction_roles_db= load_json(REACTION_ROLES_FILE)
whitelist_db     = load_json(WHITELIST_FILE)
estore_db        = load_json(ESTORE_FILE)

if "banned"  not in bot_bans_db: bot_bans_db["banned"]  = []
if "servers" not in bot_bans_db: bot_bans_db["servers"] = []

def save_settings():      save_json(SETTINGS_FILE, settings_db)
def save_econ():          save_json(ECONOMY_FILE, economy_db)
def save_warns():         save_json(WARNS_FILE, warns_db)
def save_modlogs():       save_json(MODLOGS_FILE, modlogs_db)
def save_bot_bans():      save_json(BOT_BANS_FILE, bot_bans_db)
def save_flag_scores():   save_json(FLAG_SCORES_FILE, flag_scores_db)
def save_giveaways():     save_json(GIVEAWAYS_FILE, giveaways_db)
def save_reaction_roles():save_json(REACTION_ROLES_FILE, reaction_roles_db)
def save_whitelist():     save_json(WHITELIST_FILE, whitelist_db)
def save_estore():        save_json(ESTORE_FILE, estore_db)

# Runtime state
active_bj       = {}
afk_db          = {}
xp_cooldown     = {}
WL_SESSIONS     = {}



# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_settings(guild_id):
    if not guild_id:                                   # DMs: a throw-away default, never stored
        return {"prefix": ".", "language": "en", "features": {}, "ticket_buttons": list(DEFAULT_TICKET_BUTTONS)}
    gid = str(guild_id)
    s = settings_db.get(gid)
    if s is None:
        s = settings_db[gid] = {}
    touch("settings", gid)
    if "prefix" not in s: s["prefix"] = "."
    if "language" not in s: s["language"] = "en"
    if "features" not in s: s["features"] = {}
    if "ticket_buttons" not in s: s["ticket_buttons"] = list(DEFAULT_TICKET_BUTTONS)
    return s

def is_feature_enabled(guild_id, feature):
    s = get_settings(guild_id)
    val = s["features"].get(feature, DEFAULT_FEATURES.get(feature, "enabled"))
    return val == "enabled" if isinstance(val, str) else bool(val)

def get_econ(guild_id, user_id):
    gid, uid = str(guild_id), str(user_id)
    users = economy_db.setdefault(gid, {})
    e = users.get(uid)
    if e is None:
        e = users[uid] = {"wallet": 0, "bank": 0, "inventory": []}
    touch("economy", gid, uid)
    if "inventory" not in e: e["inventory"] = []
    return e

def get_warns(guild_id, user_id):
    gid, uid = str(guild_id), str(user_id)
    users = warns_db.setdefault(gid, {})
    touch("warns", gid, uid)
    return users.setdefault(uid, [])

def get_user_xp(guild_id, user_id):
    gid, uid = str(guild_id), str(user_id)
    users = levels_db.setdefault(gid, {})
    u = users.get(uid)
    if u is None:
        u = users[uid] = {"xp": 0, "level": 0}
    touch("levels", gid, uid)
    return u

def get_level_config(guild_id=None):
    if not guild_id: return LEVEL_DIFFICULTIES["normal"]
    s = get_settings(guild_id)
    return LEVEL_DIFFICULTIES.get(s.get("leveldiff","normal"), LEVEL_DIFFICULTIES["normal"])

def get_level(xp, guild_id=None):
    d = get_level_config(guild_id)["divisor"]
    return int(math.sqrt(max(0,xp)/d))

def xp_for_level(level, guild_id=None):
    d = get_level_config(guild_id)["divisor"]
    return level * level * d

def get_ticket_buttons(guild_id):
    heal_ticket_pool(guild_id)
    return get_settings(guild_id).get("ticket_buttons", DEFAULT_TICKET_BUTTONS)

def dts(dt, style="f"):
    if not dt: return "?"
    ts = int(dt.timestamp()) if hasattr(dt,"timestamp") else int(dt)
    return f"<t:{ts}:{style}>"

def fmt_duration(s):
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m"
    if s < 86400: return f"{s//3600}h"
    return f"{s//86400}d"

def parse_duration(dur):
    """'10s' '5m' '2h' '1d' '1w' -> (seconds, localized label). (None, text) if invalid."""
    if not dur:
        return None, "?"
    m = re.match(r"^(\d+)([smhdw])$", dur.lower().strip())
    if not m:
        return None, dur
    amt, unit = int(m.group(1)), m.group(2)
    secs = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    labels = {"s": "{} second(s)", "m": "{} minute(s)", "h": "{} hour(s)", "d": "{} day(s)", "w": "{} week(s)"}
    return amt * secs, L(labels[unit], amt)

def create_deck():
    suits=["♠️","♥️","♦️","♣️"]; vals=["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    d=[(v,s) for s in suits for v in vals]; random.shuffle(d); return d

def card_emoji(c): return f"{c[0]}{c[1]}"

def hand_value(hand):
    total=0; aces=0
    for v,_ in hand:
        if v in ["J","Q","K"]: total+=10
        elif v=="A": total+=11; aces+=1
        else: total+=int(v)
    while total>21 and aces: total-=10; aces-=1
    return total


def is_whitelisted(uid, perm=None):
    if uid == BOT_CREATOR_ID: return True
    wl = whitelist_db.get(str(uid))
    if not wl: return False
    if perm is None: return True
    return perm in wl.get("perms",[]) or "all" in wl.get("perms",[])

def is_owner(uid):   return uid == BOT_CREATOR_ID
def is_supreme(uid): return uid == BOT_CREATOR_ID
def is_creator(uid): return uid == BOT_CREATOR_ID

def is_bot_banned(uid):
    if uid == BOT_CREATOR_ID:
        return False
    return str(uid) in bot_bans_db.get("banned", [])

def reload_bans():
    """Kept for old callers. The in-memory dict is the single source of truth (SQLite is written from it), so there is
    nothing to reload - re-reading the database here would throw away a ban that has not been flushed yet."""
    return None

def can_act_on(actor, target, guild):
    if actor.id == BOT_CREATOR_ID: return target.id != actor.id
    if target.id == guild.owner_id: return False
    if actor.id == guild.owner_id: return True
    return target.top_role < actor.top_role

# Whitelist = BOT-owner commands only (never server moderation). Each command is its own permission.
_WL_SINGLE = ["banuser", "unbanuser", "bannedusers", "banserver", "unbanserver", "bannedservers", "leaveserver",
              "addmoney", "removemoney", "setmoney", "resetmoney",
              "addlevel", "removelevel", "setlevel", "resetlevel", "addxp", "removexp",
              "say_no_watermark", "saydm", "sayin", "supsearch", "supstats", "servers", "userdata", "stealemoji", "setstatus"]
WL_PERMS = {p: [p] for p in _WL_SINGLE}
WL_PERMS.update({
    "bans": ["banuser", "unbanuser", "bannedusers", "banserver", "unbanserver", "bannedservers", "leaveserver"],
    "money": ["addmoney", "removemoney", "setmoney", "resetmoney"],
    "levels": ["addlevel", "removelevel", "setlevel", "resetlevel", "addxp", "removexp"],
    "messaging": ["say_no_watermark", "saydm", "sayin"],
    "info": ["supsearch", "supstats", "servers", "userdata"],
    "all": list(_WL_SINGLE),
})
WL_DESC = {
    "banuser": "banuser <id> - ban a user from the whole bot or chosen features (menu)", "unbanuser": "unbanuser <id> - lift a bot ban / restrictions",
    "bannedusers": "bannedusers - list banned and restricted users", "banserver": "banserver <id> - ban a server (bot leaves)",
    "unbanserver": "unbanserver <id> - lift a server ban", "bannedservers": "bannedservers - list banned servers", "leaveserver": "leaveserver <id> - leave a server without banning it",
    "addmoney": "addmoney <id> <n>", "removemoney": "removemoney <id> <n>", "setmoney": "setmoney <id> <n>", "resetmoney": "resetmoney <id>",
    "addlevel": "addlevel <id> <n>", "removelevel": "removelevel <id> <n>", "setlevel": "setlevel <id> <n>", "resetlevel": "resetlevel <id>",
    "addxp": "addxp <id> <n>", "removexp": "removexp <id> <n>",
    "say_no_watermark": "say without the 'Sent by' watermark (in servers)", "saydm": "saydm <id> <text> - DM a user as the bot", "sayin": "sayin <channel id> <text>",
    "supsearch": "supsearch <id> - account lookup", "supstats": "supstats - bot statistics", "servers": "servers - list servers", "userdata": "userdata <id> - what is stored about a user",
    "stealemoji": "stealemoji <emoji id> <name> - copy an emoji into a server you manage", "setstatus": "setstatus <type> <text> - change the bot status",
    "bans": "GROUP: all ban commands", "money": "GROUP: money commands", "levels": "GROUP: level and XP commands", "messaging": "GROUP: say / saydm / sayin",
    "info": "GROUP: supsearch, supstats, servers, userdata", "all": "EVERYTHING (except creator-only backup)",
}



# ============================================================
# TRANSLATIONS — All 3 languages full coverage
# ============================================================
TRANSLATIONS = {
    "en": {
        # Permissions
        "no_perm":"❌ You do not have permission!",
        "bot_no_perm":"❌ I don't have the required permissions!",
        "cannot_act":"❌ You cannot act on this member!",
        "no_perm_role":"❌ My role is too low to do that!",
        # Mod DMs
        "ban_dm":"🔨 You were banned from **{}**!\nReason: {}",
        "kick_dm":"👢 You were kicked from **{}**!\nReason: {}",
        "mute_dm":"🔇 You were muted in **{}**!\nDuration: {}\nReason: {}",
        "timeout_dm":"⏱️ You received a timeout in **{}**!\nDuration: {}\nReason: {}",
        "warn_dm":"⚠️ You received a warning in **{}**!\nReason: {}\nTotal warnings: {}",
        "warn_given":"⚠️ {} has been warned! ({} warnings)\nReason: {}",
        # Economy
        "not_enough_wallet":"❌ You only have **${}** in your wallet!",
        "not_enough_bank":"❌ You only have **${}** in your bank!",
        "invalid_amount":"❌ Invalid amount!",
        "daily_claimed":"✅ Daily reward: **${}**!\n💰 Wallet: **${}**",
        "daily_wait":"⏰ Next daily available in: **{}**",
        "work_done":"💼 You worked as **{}** and earned **${}**!\n💰 Wallet: **${}**",
        "work_wait":"⏰ You can work again in: **{}**",
        "deposited":"🏦 Deposited **${}** to your bank!\n🏦 Bank: **${}**",
        "withdrawn":"💰 Withdrew **${}** from your bank!\n💰 Wallet: **${}**",
        "rob_poor":"❌ **{}** doesn't have enough money to rob!",
        "rob_caught":"🚔 You were caught robbing! You lost **70%** of your wallet: **${}**!\n💰 Wallet: **${}**",
        "rob_success":"💰 You robbed **{}** and stole **${}**!\n💰 Wallet: **${}**",
        "money_added":"✅ Added **${}** to {}!",
        "money_removed":"✅ Removed **${}** from {}!",
        # Leveling
        "levelup":"🎉 Congratulations {}! You reached **Level {}**!",
        # General
        "afk_set":"💤 {} is now AFK\n> *{}*",
        "afk_back":"👋 Welcome back, {}! Your AFK has been removed.",
        "afk_user":"💤 **{}** is currently AFK\n> *{}*",
        # Settings
        "language_set":"✅ Language set to: **English** 🇬🇧",
        "prefix_set":"✅ Prefix set to `{}`!",
        "setup_reset":"🔄 Settings have been reset!",
        # Tickets
        "ticket_created":"✅ Your ticket has been created: {}",
        # Casino
        "casino_only":"❌ Economy commands are only allowed in {}!",
        "invalid_bet":"❌ Invalid bet amount!\n💰 Your wallet: **${}**",
        # Features
        "feature_off":"❌ **{}** is not enabled on this server!\nAsk an admin to enable it: `/setup feature {} on`",
        # Welcome
        "welcome":"👋 Welcome to **{}**, {}!\nYou are member **#{}**!",
        # Misc
        "purge_done":"🗑️ Deleted **{}** messages!",
        "nothing_playing":"❌ Nothing is currently playing!",
    },
    "tr": {
        # Permissions
        "no_perm":"❌ Bu işlem için yetkiniz yok!",
        "bot_no_perm":"❌ Gerekli yetkiye sahip değilim!",
        "cannot_act":"❌ Bu üyeye işlem yapamazsınız!",
        "no_perm_role":"❌ Rolüm bunun için çok düşük!",
        # Mod DMs
        "ban_dm":"🔨 **{}** sunucusundan yasaklandınız!\nSebep: {}",
        "kick_dm":"👢 **{}** sunucusundan atıldınız!\nSebep: {}",
        "mute_dm":"🔇 **{}** sunucusunda susturuldunuz!\nSüre: {}\nSebep: {}",
        "timeout_dm":"⏱️ **{}** sunucusunda zaman aşımına uğradınız!\nSüre: {}\nSebep: {}",
        "warn_dm":"⚠️ **{}** sunucusunda uyarı aldınız!\nSebep: {}\nToplam uyarı: {}",
        "warn_given":"⚠️ {} uyarıldı! ({} uyarı)\nSebep: {}",
        # Economy
        "not_enough_wallet":"❌ Cüzdanınızda yalnızca **${}** var!",
        "not_enough_bank":"❌ Bankada yalnızca **${}** var!",
        "invalid_amount":"❌ Geçersiz miktar!",
        "daily_claimed":"✅ Günlük ödülünüz: **${}**!\n💰 Cüzdan: **${}**",
        "daily_wait":"⏰ Sonraki günlük ödülünüz: **{}** sonra",
        "work_done":"💼 **{}** olarak çalıştın ve **${}** kazandın!\n💰 Cüzdan: **${}**",
        "work_wait":"⏰ Tekrar çalışabilirsin: **{}** sonra",
        "deposited":"🏦 **${}** bankaya yatırıldı!\n🏦 Banka: **${}**",
        "withdrawn":"💰 Bankadan **${}** çekildi!\n💰 Cüzdan: **${}**",
        "rob_poor":"❌ **{}** soyulmak için yeterli parası yok!",
        "rob_caught":"🚔 Soyarken yakalandın! Cüzdanının **%70'ini** kaybettin: **${}**!\n💰 Cüzdan: **${}**",
        "rob_success":"💰 **{}** soyuldu, **${}** çalındı!\n💰 Cüzdan: **${}**",
        "money_added":"✅ {}'e **${}** eklendi!",
        "money_removed":"✅ {}'den **${}** çıkarıldı!",
        # Leveling
        "levelup":"🎉 Tebrikler {}! **{}. Seviye**ye ulaştın!",
        # General
        "afk_set":"💤 {} artık AFK\n> *{}*",
        "afk_back":"👋 Geri döndün, {}! AFK durumun kaldırıldı.",
        "afk_user":"💤 **{}** şu an AFK\n> *{}*",
        # Settings
        "language_set":"✅ Dil olarak ayarlandı: **Türkçe** 🇹🇷",
        "prefix_set":"✅ Önek `{}` olarak ayarlandı!",
        "setup_reset":"🔄 Tüm ayarlar sıfırlandı!",
        # Tickets
        "ticket_created":"✅ Ticketınız oluşturuldu: {}",
        # Casino
        "casino_only":"❌ Ekonomi komutları yalnızca {} kanalında kullanılabilir!",
        "invalid_bet":"❌ Geçersiz bahis miktarı!\n💰 Cüzdanın: **${}**",
        # Features
        "feature_off":"❌ **{}** bu sunucuda aktif değil!\nBir yönetici etkinleştirebilir: `/setup feature {} on`",
        # Welcome
        "welcome":"👋 **{}** sunucusuna hoş geldin, {}!\nSunucumuzun **{}. üyesi** oldun!",
        # Misc
        "purge_done":"🗑️ **{}** mesaj silindi!",
        "nothing_playing":"❌ Şu an çalan bir şey yok!",
    },
    "ru": {
        # Permissions
        "no_perm":"❌ У вас нет разрешения!",
        "bot_no_perm":"❌ У меня недостаточно прав!",
        "cannot_act":"❌ Нельзя применить это к данному участнику!",
        "no_perm_role":"❌ Моя роль слишком низкая для этого!",
        # Mod DMs
        "ban_dm":"🔨 Вы забанены на сервере **{}**!\nПричина: {}\nОбжаловать: https://discord.gg/hxYWsFVWp8",
        "kick_dm":"👢 Вас выгнали с сервера **{}**!\nПричина: {}",
        "mute_dm":"🔇 Вы заглушены на сервере **{}**!\nДлительность: {}\nПричина: {}",
        "timeout_dm":"⏱️ Вам выдан тайм-аут на сервере **{}**!\nДлительность: {}\nПричина: {}",
        "warn_dm":"⚠️ Вы получили предупреждение на **{}**!\nПричина: {}\nВсего предупреждений: {}",
        "warn_given":"⚠️ {} предупреждён! ({} предупреждений)\nПричина: {}",
        # Economy
        "not_enough_wallet":"❌ В вашем кошельке только **${}**!",
        "not_enough_bank":"❌ В вашем банке только **${}**!",
        "invalid_amount":"❌ Неверная сумма!",
        "daily_claimed":"✅ Ежедневная награда: **${}**!\n💰 Кошелёк: **${}**",
        "daily_wait":"⏰ Следующая награда через: **{}**",
        "work_done":"💼 Вы работали как **{}** и заработали **${}**!\n💰 Кошелёк: **${}**",
        "work_wait":"⏰ Снова работать можно через: **{}**",
        "deposited":"🏦 Положено **${}** в банк!\n🏦 Банк: **${}**",
        "withdrawn":"💰 Снято **${}** из банка!\n💰 Кошелёк: **${}**",
        "rob_poor":"❌ У **{}** недостаточно денег для ограбления!",
        "rob_caught":"🚔 Тебя поймали на ограблении! Потеряно **70%** кошелька: **${}**!\n💰 Кошелёк: **${}**",
        "rob_success":"💰 Вы ограбили **{}** на **${}**!\n💰 Кошелёк: **${}**",
        "money_added":"✅ Добавлено **${}** для {}!",
        "money_removed":"✅ Снято **${}** у {}!",
        # Leveling
        "levelup":"🎉 Поздравляем, {}! Вы достигли **{} уровня**!",
        # General
        "afk_set":"💤 {} теперь AFK\n> *{}*",
        "afk_back":"👋 С возвращением, {}! Ваш AFK-статус снят.",
        "afk_user":"💤 **{}** сейчас AFK\n> *{}*",
        # Settings
        "language_set":"✅ Язык установлен: **Русский** 🇷🇺",
        "prefix_set":"✅ Префикс установлен: `{}`!",
        "setup_reset":"🔄 Настройки сброшены!",
        # Tickets
        "ticket_created":"✅ Ваш тикет создан: {}",
        # Casino
        "casino_only":"❌ Команды экономики доступны только в {}!",
        "invalid_bet":"❌ Неверная сумма ставки!\n💰 Ваш кошелёк: **${}**",
        # Features
        "feature_off":"❌ **{}** отключена на этом сервере!\nАдмин может включить: `/setup feature {} on`",
        # Welcome
        "welcome":"👋 Добро пожаловать на **{}**, {}!\nТы стал **{}. участником** сервера!",
        # Misc
        "purge_done":"🗑️ Удалено **{}** сообщений!",
        "nothing_playing":"❌ Сейчас ничего не играет!",
    },
}

def t(guild_id, key, *args):
    gid = str(guild_id)
    lang = settings_db.get(gid,{}).get("language","en")
    msg = TRANSLATIONS.get(lang,{}).get(key) or TRANSLATIONS["en"].get(key,key)
    try: return msg.format(*args) if args else msg
    except: return str(msg)


# ============================================================
# BOT SETUP
# ============================================================
OWNER_ONLY_CMDS = set()                       # owner commands now live in DMs only

def _base_prefix(bot, message):
    if not message.guild: return ["."]
    if message.content:
        first_word = message.content.lstrip(" ").split()[0] if message.content.strip() else ""
        cmd = re.sub(r'^[^a-z0-9]+',"",first_word.lower())
        if cmd in OWNER_ONLY_CMDS: return ["."]
    s = settings_db.get(str(message.guild.id),{})
    pfx = s.get("prefix",".")
    return [pfx, "."] if pfx != "." else ["."]

def get_prefix(bot, message):
    return commands.when_mentioned(bot, message) + _base_prefix(bot, message)

intents = discord.Intents.default()
intents.members = True                # welcome messages, role persist, member lookups
intents.message_content = True        # prefix commands, XP and message counts (no presence intent: it is not needed)

class VersaTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild:
            if str(interaction.guild.id) in bot_bans_db.get("servers", []):
                return False
            set_lang(interaction.guild.id)
        uid = interaction.user.id
        if uid != BOT_CREATOR_ID and str(uid) in bot_bans_db.get("banned", []):
            try:
                await interaction.response.send_message(L('⛔ You are banned from using this bot.'), ephemeral=True)
            except Exception:
                pass
            return False
        if rate_limited(uid):
            try:
                await interaction.response.send_message(L('⏳ You are using commands too fast. Please slow down!'), ephemeral=True)
            except Exception:
                pass
            return False
        return True

bot = commands.AutoShardedBot(command_prefix=get_prefix, intents=intents, help_command=None, tree_cls=VersaTree, activity=discord.Game(name=".help | /help"))
setup_group = app_commands.Group(name="setup", description="Server configuration", guild_only=True,
                                 default_permissions=discord.Permissions(manage_guild=True))
rroles_group = app_commands.Group(name="rroles", description="Reaction roles", guild_only=True,
                                  default_permissions=discord.Permissions(manage_roles=True))

# Feature check decorator
def feature_required(feature):
    async def predicate(ctx):
        if user_restricted(ctx.author.id, feature):
            await notify_restricted(ctx, feature)
            return False
        if not is_feature_enabled(ctx.guild.id, feature):
            label = L(FEATURE_LABELS.get(feature, feature))
            await ctx.send(t(ctx.guild.id,"feature_off",label,feature), delete_after=8)
            return False
        return True
    from discord.ext.commands import check
    return check(predicate)

async def slash_check_feature(interaction, feature):
    if user_restricted(interaction.user.id, feature):
        try: await interaction.response.send_message(restricted_text(feature), ephemeral=True)
        except: pass
        return False
    if not is_feature_enabled(interaction.guild.id if interaction.guild else 0, feature):
        label = L(FEATURE_LABELS.get(feature, feature))
        try: await interaction.response.send_message(t(interaction.guild.id if interaction.guild else 0,"feature_off",label,feature), ephemeral=True)
        except: pass
        return False
    return True

async def check_casino(ctx, is_slash=False):
    gid = ctx.guild.id if hasattr(ctx,"guild") else ctx.guild_id
    s = get_settings(gid); ch = s.get("casino")
    channel_id = ctx.channel_id if is_slash else ctx.channel.id
    if ch and str(channel_id) != str(ch):
        c = ctx.guild.get_channel(int(ch)) if hasattr(ctx,"guild") else None
        mention = c.mention if c else f"<#{ch}>"
        msg = t(gid,"casino_only",mention)
        if is_slash:
            try: await ctx.response.send_message(msg, ephemeral=True)
            except: pass
        else: await ctx.send(msg, delete_after=8)
        return False
    return True

# ============================================================
# LOG HELPER
# ============================================================

async def post_case_log(guild, case_id, action, target, mod, reason):
    gid, uid = str(guild.id), str(target.id)
    if gid not in modlogs_db: modlogs_db[gid] = {}
    if uid not in modlogs_db[gid]: modlogs_db[gid][uid] = []
    modlogs_db[gid][uid].append({
        "case":case_id,"action":action,"reason":reason,
        "mod":str(mod.id),"time":datetime.now(timezone.utc).isoformat(),
        "target_name":str(target),"mod_name":str(mod)
    })
    touch("modlogs", gid, uid); save_modlogs()
    colors = {"ban":0xED4245,"kick":0xFEE75C,"warn":0xFEE75C,"mute":0x808080,"timeout":0xFEE75C}
    emojis = {"ban":"🔨","kick":"👢","warn":"⚠️","mute":"🔇","unmute":"🔊","timeout":"⏱️","softban":"🔄"}
    embed = discord.Embed(title=L('{} {} — Case #{}', emojis.get(action, '❓'), action.upper(), case_id),
        color=colors.get(action,0xff6b35), timestamp=datetime.now(timezone.utc))
    embed.add_field(name=L('👤 Target'), value=f"{target.mention} (`{target.id}`)", inline=True)
    embed.add_field(name=L('🛡️ Mod'), value=mod.mention, inline=True)
    embed.add_field(name=L('📝 Reason'), value=reason, inline=False)
    embed.set_footer(text=L('Case #{}', case_id))
    if log_on(guild.id, "mod_cases"):
        await send_log(guild, embed)

async def get_muted_role(guild):
    s = get_settings(guild.id)
    role_id = s.get("mutedrole")
    if role_id:
        role = guild.get_role(int(role_id))
        if role: return role
    role = discord.utils.get(guild.roles, name="Muted")
    if not role:
        role = await guild.create_role(name="Muted")
        for ch in guild.text_channels:
            try: await ch.set_permissions(role, send_messages=False, add_reactions=False)
            except: pass
    return role


# ============================================================
# VIEWS — UI COMPONENTS
# ============================================================
STYLE_MAP = {"blurple":discord.ButtonStyle.blurple,"red":discord.ButtonStyle.red,
             "green":discord.ButtonStyle.green,"grey":discord.ButtonStyle.grey}

class BaseView(discord.ui.View):
    """Base of every view: blocks bot-banned users/servers, sets the language, localizes button labels."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for child in self.children:
            label = getattr(child, "label", None)
            if label:
                try:
                    child.label = L(label)
                except Exception:
                    pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild:
            if str(interaction.guild.id) in bot_bans_db.get("servers", []):
                return False
            set_lang(interaction.guild.id)
        uid = interaction.user.id
        if uid != BOT_CREATOR_ID and str(uid) in bot_bans_db.get("banned", []):
            try:
                await interaction.response.send_message(L('⛔ You are banned from using this bot.'), ephemeral=True)
            except Exception:
                pass
            return False
        return True


class EchoView(BaseView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="sent with echo",style=discord.ButtonStyle.grey,disabled=True,emoji="📢",custom_id="echo_v2"))







class TicketButton(discord.ui.Button):
    def __init__(self, label, style, custom_id, category, emoji_label, row):
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self.category = category
        self.emoji_label = emoji_label
    async def callback(self, interaction: discord.Interaction):
        await create_ticket(interaction, self.category, self.emoji_label)




# ============================================================
# WHITELIST SYSTEM
# ============================================================
class WhitelistPanel(BaseView):
    def __init__(self): super().__init__(timeout=300)
    @discord.ui.button(label="➕ Add User", style=discord.ButtonStyle.green, custom_id="wl_add")
    async def add_user(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != BOT_CREATOR_ID: await interaction.response.send_message("❌",ephemeral=True); return
        WL_SESSIONS[interaction.user.id] = {"step":"get_uid","perms":[]}
        await interaction.response.send_message("📝 **Enter the USER ID** to whitelist:")
    @discord.ui.button(label="➖ Remove User", style=discord.ButtonStyle.red, custom_id="wl_remove")
    async def remove_user(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != BOT_CREATOR_ID: await interaction.response.send_message("❌",ephemeral=True); return
        WL_SESSIONS[interaction.user.id] = {"step":"remove_uid"}
        await interaction.response.send_message("📝 **Enter the USER ID** to remove:")
    @discord.ui.button(label="👥 WL Users", style=discord.ButtonStyle.blurple, custom_id="wl_list")
    async def list_users(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if interaction.user.id != BOT_CREATOR_ID: await interaction.response.send_message("❌",ephemeral=True); return
        if not whitelist_db: await interaction.response.send_message("📋 No whitelisted users!"); return
        embed = discord.Embed(title="👥 Whitelisted Users", color=0x57F287)
        for uid, data in whitelist_db.items():
            perms = ", ".join(data.get("perm_groups",[])) or "None"
            embed.add_field(name=f"<@{uid}>", value=f"**Perms:** {perms}\n**Added:** {str(data.get('added_at','?'))[:10]}", inline=False)
        await interaction.response.send_message(embed=embed)


# ============================================================
# GIVEAWAY VIEW
# ============================================================

async def end_giveaway(guild, gid, ga_id):
    if gid not in giveaways_db or ga_id not in giveaways_db[gid]: return
    ga = giveaways_db[gid][ga_id]
    if ga.get("ended"): return
    ga["ended"] = True; save_giveaways()
    ch = bot.get_channel(int(ga.get("channel_id",0)))
    if not ch: return
    parts = ga.get("participants",[])
    if not parts:
        try:
            msg = await ch.fetch_message(int(ga.get("message_id",0)))
            await msg.edit(embed=discord.Embed(description=L('🎉 **{}** — No participants!', ga['prize']), color=0x808080), view=None)
        except: await ch.send(embed=discord.Embed(description=L('🎉 **{}** — No participants!', ga['prize']), color=0x808080))
        return
    winners = random.sample(parts, min(ga.get("winners",1), len(parts)))
    mentions = " ".join(f"<@{w}>" for w in winners)
    embed = discord.Embed(title=L('🎉 ENDED: {}', ga['prize']), description=L('**Winners:** {}', mentions), color=0xffd700)
    try:
        msg = await ch.fetch_message(int(ga.get("message_id",0)))
        await msg.edit(embed=embed, view=None)
    except: pass
    await ch.send(L('🎉 Congrats {}! You won **{}**!', mentions, ga['prize']))




# ============================================================
# MODERATION COMMANDS
# ============================================================

@bot.command(name="kick")
@commands.bot_has_permissions(kick_members=True)
async def kick_p(ctx, member: discord.Member = None, *, reason: str = "No reason"):
    reason, notify = strip_dm_flag(reason)
    reason = reason or "No reason"
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send(t(ctx.guild.id,"no_perm"), delete_after=5); return
    if not member: await ctx.send(L('❌ Usage: `{}`', '.kick @user [reason]'), delete_after=5); return
    if not can_act_on(ctx.author, member, ctx.guild): await ctx.send(t(ctx.guild.id,"cannot_act"), delete_after=5); return
    try:
        gid = ctx.guild.id; s = get_settings(gid); case_id = next_case_s(s)
        try: await send_dm(member, guild=ctx.guild, notify=notify, embed=discord.Embed(description=t(gid,"kick_dm",ctx.guild.name,reason),color=0xFEE75C))
        except: pass
        await member.kick(reason=reason)
        await ctx.send(embed=discord.Embed(description=L('👢 **{}** kicked!\nReason: {}', member, reason),color=0xFEE75C),delete_after=15)
        await ctx.message.add_reaction("✅")
        await post_case_log(ctx.guild, case_id, "kick", member, ctx.author, reason)
    except Exception as e: await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="unban")
@commands.bot_has_permissions(ban_members=True)
async def unban_p(ctx, user_id: str = None, *, reason: str = "No reason"):
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send(t(ctx.guild.id,"no_perm"), delete_after=5); return
    if not user_id: await ctx.send(L('❌ Usage: `{}`', '.unban <user_id>'), delete_after=5); return
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user, reason=reason)
        await ctx.send(embed=discord.Embed(description=L('✅ **{}** unbanned!', user),color=0x57F287),delete_after=10)
        await ctx.message.add_reaction("✅")
    except Exception as e: await ctx.send(f"❌ {e}", delete_after=5)




@bot.command(name="untimeout")
@commands.bot_has_permissions(moderate_members=True)
async def untimeout_p(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.moderate_members: return
    if not member: await ctx.send(L('❌ Usage: `{}`', '.untimeout @user'), delete_after=5); return
    try:
        await member.timeout(None)
        await ctx.send(embed=discord.Embed(description=L('✅ **{}** timeout removed!', member),color=0x57F287),delete_after=10)
        await ctx.message.add_reaction("✅")
    except Exception as e: await ctx.send(f"❌ {e}", delete_after=5)


@bot.command(name="warn")
async def warn_p(ctx, member: discord.Member = None, *, reason: str = "No reason"):
    reason, notify = strip_dm_flag(reason)
    reason = reason or "No reason"
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.send(t(ctx.guild.id,"no_perm"), delete_after=5); return
    if not member: await ctx.send(L('❌ Usage: `{}`', '.warn @user [reason]'), delete_after=5); return
    gid = ctx.guild.id; warns = get_warns(gid, member.id)
    warns.append({"reason":reason,"by":str(ctx.author.id),"time":datetime.now(timezone.utc).isoformat()})
    save_warns(); wc = len(warns)
    try: await send_dm(member, guild=ctx.guild, notify=notify, embed=discord.Embed(description=t(gid,"warn_dm",ctx.guild.name,reason,wc),color=0xFEE75C))
    except: pass
    await ctx.send(embed=discord.Embed(description=t(gid,"warn_given",member.mention,wc,reason),color=0xFEE75C),delete_after=15)
    await ctx.message.add_reaction("✅")
    s = get_settings(gid); case_id = next_case_s(s)
    await post_case_log(ctx.guild, case_id, "warn", member, ctx.author, reason)
    puns = s.get("warnpunish",{3:"mute",5:"kick",10:"ban"})
    action = puns.get(wc) or puns.get(str(wc))
    if action == "mute":
        role = await get_muted_role(ctx.guild)
        try: await member.add_roles(role, reason=f"Auto-mute: {wc} warns")
        except: pass
    elif action == "kick":
        try: await member.kick(reason=f"Auto-kick: {wc} warns")
        except: pass
    elif action == "ban":
        try: await member.ban(reason=f"Auto-ban: {wc} warns")
        except: pass

@bot.command(name="warnings")
async def warnings_p(ctx, member: discord.Member = None):
    target = member or ctx.author
    warns = get_warns(ctx.guild.id, target.id)
    embed = discord.Embed(title=L("⚠️ {}'s Warnings ({})", target.display_name, len(warns)), color=0xFEE75C)
    if not warns: embed.description = L('✅ No warnings!')
    else:
        for i,w in enumerate(warns[-10:],1):
            embed.add_field(name=f"#{i}",value=L('**Reason:** {}\n**By:** <@{}>\n**Date:** {}', w['reason'], w.get('by', '?'), str(w.get('time', '?'))[:10]),inline=False)
    await ctx.send(embed=embed)

@bot.command(name="clearwarns", aliases=["clearwarnings"])
async def clearwarns_p(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.manage_messages: return
    if not member: await ctx.send(L('❌ Usage: `{}`', '.clearwarns @user'), delete_after=5); return
    gid, uid = str(ctx.guild.id), str(member.id)
    if gid in warns_db and uid in warns_db[gid]: warns_db[gid][uid] = []; touch("warns", gid, uid); save_warns()
    await ctx.send(embed=discord.Embed(description=L('✅ Cleared all warns for {}!', member.mention),color=0x57F287),delete_after=10)

@bot.command(name="purge")
@commands.bot_has_permissions(manage_messages=True, read_message_history=True)
async def purge_p(ctx, amount: int = 10):
    if not ctx.author.guild_permissions.manage_messages: return
    amount = max(1, min(100, abs(int(amount))))
    try:
        deleted = await ctx.channel.purge(limit=amount+1)
        await ctx.send(embed=discord.Embed(description=L('🗑️ Deleted **{}** messages!', len(deleted) - 1),color=0xff6b35),delete_after=5)
    except Exception as e: await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="history", aliases=["modlogs","modhistory"])
async def history_p(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.moderate_members: return
    if not member: await ctx.send(L('❌ Usage: `{}`', '.history @user'), delete_after=5); return
    gid, uid = str(ctx.guild.id), str(member.id)
    all_logs = list(modlogs_db.get(gid,{}).get(uid,[]))
    warns = warns_db.get(gid,{}).get(uid,[])
    for i,w in enumerate(warns):
        if not any(l.get("action")=="warn" and l.get("time","")[:10]==w.get("time","")[:10] for l in all_logs):
            all_logs.append({"case":f"W{i+1}","action":"warn","reason":w.get("reason","?"),"mod":w.get("by","?"),"time":w.get("time","?")})
    if not all_logs:
        await ctx.send(embed=discord.Embed(description=L('✅ **{}** has no moderation history.', member.display_name),color=0x57F287)); return
    all_logs.sort(key=lambda x: x.get("time",""), reverse=True)
    emojis = {"ban":"🔨","kick":"👢","warn":"⚠️","mute":"🔇","unmute":"🔊","timeout":"⏱️","softban":"🔄"}
    counts = {}
    for l in all_logs: a=l.get("action","?"); counts[a]=counts.get(a,0)+1
    summary = " | ".join(f"{emojis.get(k,'❓')} {k.title()}: {v}" for k,v in counts.items())
    embed = discord.Embed(title=L("📋 {}'s History", member.display_name),description=L('**Summary:** {}\n**Total:** {}', summary, len(all_logs)),color=0xff6b35)
    embed.set_thumbnail(url=member.display_avatar.url)
    for l in all_logs[:10]:
        action = l.get("action","?"); emoji = emojis.get(action,"❓")
        embed.add_field(name=L('{} Case #{} — {}', emoji, l.get('case', '?'), action.upper()),
            value=L('**Reason:** {}\n**By:** <@{}>\n**Date:** {}', l.get('reason', '?'), l.get('mod', '?'), str(l.get('time', '?'))[:10]),inline=False)
    if len(all_logs)>10: embed.set_footer(text=L('Showing 10 of {}', len(all_logs)))
    await ctx.send(embed=embed)

@bot.command(name="case")
async def case_p(ctx, case_id=None):
    if not ctx.author.guild_permissions.moderate_members: return
    if not case_id: await ctx.send(L('❌ Usage: `{}`', '.case <id>'), delete_after=5); return
    gid = str(ctx.guild.id)
    emojis = {"ban":"🔨","kick":"👢","warn":"⚠️","mute":"🔇","timeout":"⏱️"}
    for uid, logs in modlogs_db.get(gid,{}).items():
        for l in logs:
            if str(l.get("case","")) == str(case_id):
                action = l.get("action","?")
                member = ctx.guild.get_member(int(uid))
                embed = discord.Embed(title=L('{} Case #{} — {}', emojis.get(action, '❓'), case_id, action.upper()),color=0xff6b35,timestamp=datetime.now(timezone.utc))
                embed.add_field(name=L('👤 Member'),value=f"{member.mention if member else f'<@{uid}>'} (`{uid}`)",inline=True)
                embed.add_field(name=L('🛡️ Mod'),value=f"<@{l.get('mod','?')}>",inline=True)
                embed.add_field(name=L('📝 Reason'),value=l.get("reason","?"),inline=False)
                embed.add_field(name=L('📅 Date'),value=str(l.get("time","?"))[:19],inline=True)
                if member: embed.set_thumbnail(url=member.display_avatar.url)
                await ctx.send(embed=embed); return
    await ctx.send(L('❌ Case `{}` not found!', case_id), delete_after=5)





@bot.command(name="slowmode")
@commands.bot_has_permissions(manage_channels=True)
async def slowmode_p(ctx, seconds: int = 0, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.manage_channels: return
    ch = channel or ctx.channel
    try:
        await ch.edit(slowmode_delay=max(0,min(21600,seconds)))
        await ctx.send(embed=discord.Embed(description=L('⏱️ Slowmode set to **{}s** in {}!', seconds, ch.mention),color=0xff6b35),delete_after=10)
        try: await ctx.message.delete()
        except: pass
    except Exception as e: await ctx.send(f"❌ {e}", delete_after=5)





# ============================================================
# ECONOMY COMMANDS
# ============================================================
@bot.command(name="balance", aliases=["bal","wallet"])
@feature_required("economy")
async def balance_p(ctx, member: discord.Member = None):
    target = member or ctx.author
    econ = get_econ(ctx.guild.id, target.id)
    embed = discord.Embed(title=f"💰 {target.display_name}", color=0x57F287)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name=L('👝 Wallet'), value=f"${econ['wallet']:,}", inline=True)
    embed.add_field(name=L('🏦 Bank'), value=f"${econ['bank']:,}", inline=True)
    embed.add_field(name=L('💵 Total'), value=f"${econ['wallet']+econ['bank']:,}", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="daily")
@feature_required("economy")
async def daily_p(ctx):
    gid = ctx.guild.id; econ = get_econ(gid, ctx.author.id)
    now = datetime.now(timezone.utc); last = econ.get("last_daily")
    if last:
        diff = (now - datetime.fromisoformat(last)).total_seconds()
        if diff < 86400:
            h,m = int((86400-diff)//3600), int(((86400-diff)%3600)//60)
            await ctx.send(embed=discord.Embed(description=t(gid,"daily_wait",f"{h}h {m}m"),color=0xED4245),delete_after=10); return
    amount = random.randint(200,500); econ["wallet"]+=amount; econ["last_daily"]=now.isoformat(); save_econ()
    await ctx.send(embed=discord.Embed(description=t(gid,"daily_claimed",f"{amount:,}",f"{econ['wallet']:,}"),color=0x57F287))





# ---------- amounts: all / half / quarter / 48% / 100,000,000 / 1.5k / 2m (used by pay, dep, with, bj, slots, cf) ----------
_AMOUNT_WORDS = {"all": (1, 1), "max": (1, 1), "everything": (1, 1), "hamısı": (1, 1), "hepsi": (1, 1), "tümü": (1, 1), "все": (1, 1), "всё": (1, 1),
                 "half": (1, 2), "yarı": (1, 2), "yarısı": (1, 2), "половина": (1, 2),
                 "quarter": (1, 4), "çeyrek": (1, 4), "dörddəbir": (1, 4), "четверть": (1, 4)}
_AMOUNT_SUFFIX = {"": 1, "k": 10 ** 3, "m": 10 ** 6, "b": 10 ** 9, "t": 10 ** 12}

def parse_amount(text, balance):
    """Whole number of coins for 'all', 'half', 'quarter', '48%', '100,000,000', '1.5k', '2m' ... or None when it is not an amount."""
    if text is None:
        return None
    s = str(text).strip().lower().replace(" ", "").replace("_", "")
    if not s:
        return None
    if s in _AMOUNT_WORDS:
        num, den = _AMOUNT_WORDS[s]
        return balance * num // den
    try:
        if s.endswith("%"):
            pct = decimal.Decimal(s[:-1].replace(",", "."))
            return int(pct * balance / 100) if 0 < pct <= 100 else None
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmbt]?)", s.replace(",", ""))
        if not m:
            return None
        return int(decimal.Decimal(m.group(1)) * _AMOUNT_SUFFIX[m.group(2)])
    except decimal.InvalidOperation:
        return None

@bot.command(name="pay")
@feature_required("economy")
async def pay_p(ctx, member: discord.Member = None, amount: str = None):
    gid = ctx.guild.id
    if not member or amount is None:
        await ctx.send(L("❌ Usage: `{}`", ".pay @user <amount|all|half|25%>"), delete_after=5)
        return
    if member.id == ctx.author.id:
        await ctx.send(L("❌ Can't pay yourself!"), delete_after=5)
        return
    sender = get_econ(gid, ctx.author.id)
    amt = parse_amount(amount, sender["wallet"])
    if amt is None:
        await ctx.send(L("❌ Usage: `{}`", ".pay @user <amount|all|half|25%>"), delete_after=5)
        return
    if amt <= 0:
        await ctx.send(L("❌ Amount must be positive!"), delete_after=5)
        return
    if amt > sender["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{sender['wallet']:,}"), color=0xED4245))
        return
    tax = int(amt * 0.10)
    net = amt - tax
    sender["wallet"] -= amt
    recv = get_econ(gid, member.id)
    recv["wallet"] += net
    save_econ()
    await ctx.send(embed=discord.Embed(description=L("💸 **{}** → **{}**: **${:,}**\n*(10% tax: ${:,})*", ctx.author.display_name, member.display_name, net, tax), color=0x57F287))

@bot.command(name="deposit", aliases=["dep"])
@feature_required("economy")
async def deposit_p(ctx, amount: str = None):
    gid = ctx.guild.id
    econ = get_econ(gid, ctx.author.id)
    amt = parse_amount(amount, econ["wallet"])
    if amt is None:
        await ctx.send(L("❌ Usage: `{}`", ".dep <amount|all|half|25%>"), delete_after=5)
        return
    if amt <= 0 or amt > econ["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{econ['wallet']:,}"), color=0xED4245), delete_after=8)
        return
    econ["wallet"] -= amt
    econ["bank"] += amt
    save_econ()
    await ctx.send(embed=discord.Embed(description=t(gid, "deposited", f"{amt:,}", f"{econ['bank']:,}"), color=0x57F287))

@bot.command(name="withdraw", aliases=["with"])
@feature_required("economy")
async def withdraw_p(ctx, amount: str = None):
    gid = ctx.guild.id
    econ = get_econ(gid, ctx.author.id)
    amt = parse_amount(amount, econ["bank"])
    if amt is None:
        await ctx.send(L("❌ Usage: `{}`", ".with <amount|all|half|25%>"), delete_after=5)
        return
    if amt <= 0 or amt > econ["bank"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_bank", f"{econ['bank']:,}"), color=0xED4245), delete_after=8)
        return
    econ["bank"] -= amt
    econ["wallet"] += amt
    save_econ()
    await ctx.send(embed=discord.Embed(description=t(gid, "withdrawn", f"{amt:,}", f"{econ['wallet']:,}"), color=0x57F287))

@bot.command(name="elb")
@feature_required("economy")
async def elb_p(ctx):
    gid = str(ctx.guild.id)
    if gid not in economy_db: await ctx.send(L('❌ No data yet!')); return
    users = sorted(economy_db[gid].items(),key=lambda x:x[1].get("wallet",0)+x[1].get("bank",0),reverse=True)[:10]
    embed = discord.Embed(title=L('💰 Economy Leaderboard'),color=0xffd700)
    medals = ["🥇","🥈","🥉"]
    for i,(uid,data) in enumerate(users,1):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid[:6]}"
        total = data.get("wallet",0)+data.get("bank",0)
        embed.add_field(name=f"{medals[i-1] if i<=3 else f'`{i}.`'} {name}",value=f"${total:,}",inline=False)
    await ctx.send(embed=embed)

# Owner economy admin



# ============================================================
# ECONOMY STORE
# ============================================================





# ============================================================
# CASINO COMMANDS
# ============================================================




# ============================================================
# LEVELING COMMANDS
# ============================================================
@bot.command(name="rank")
@feature_required("leveling")
async def rank_p(ctx, member: discord.Member = None):
    target = member or ctx.author
    gid = ctx.guild.id; udata = get_user_xp(gid, target.id)
    xp = udata["xp"]; level = get_level(xp, gid)
    next_xp = xp_for_level(level+1, gid); prev_xp = xp_for_level(level, gid)
    progress = xp - prev_xp; needed = next_xp - prev_xp
    pct = int((progress/needed)*20) if needed else 20
    bar = "▰"*pct + "▱"*(20-pct)
    embed = discord.Embed(title=f"📊 {target.display_name}", color=0xff6b35)
    embed.add_field(name=L('Level'), value=f"**{level}**", inline=True)
    embed.add_field(name=L('XP'), value=f"**{xp:,}**", inline=True)
    embed.add_field(name=L('Progress'), value=f"`{bar}`\n{progress:,}/{needed:,}", inline=False)
    embed.add_field(name=L('💬 Messages'), value=msg_stats_text(gid, target.id), inline=False)
    _mf = msg_stats_footer(gid)
    if _mf:
        embed.set_footer(text=_mf)
    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name="leaderboard", aliases=["lb"])
@feature_required("leveling")
async def lb_p(ctx):
    gid = str(ctx.guild.id)
    if gid not in levels_db or not levels_db[gid]: await ctx.send(L('❌ No XP data yet!')); return
    users = sorted(levels_db[gid].items(),key=lambda x:x[1].get("xp",0),reverse=True)[:10]
    embed = discord.Embed(title=L('📊 XP Leaderboard'), color=0xff6b35)
    medals = ["🥇","🥈","🥉"]
    for i,(uid,data) in enumerate(users,1):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid}"
        xp = data.get("xp",0); lvl = get_level(xp, int(gid))
        embed.add_field(name=f"{medals[i-1] if i<=3 else f'`{i}.`'} {name}",value=L('Level **{}** | **{:,}** XP', lvl, xp),inline=False)
    await ctx.send(embed=embed)





# ============================================================
# FLAG GAME
# ============================================================
active_flags = {}


@bot.command(name="flag-leaderboard", aliases=["flb"])
@feature_required("flag")
async def flb_p(ctx):
    gid = str(ctx.guild.id); data = flag_scores_db.get(gid,{})
    if not data: await ctx.send(L('❌ No scores yet!')); return
    users = sorted(data.items(),key=lambda x:x[1].get("total",0),reverse=True)[:10]
    embed = discord.Embed(title=L('🏳️ Flag Leaderboard'),color=0xff6b35)
    medals = ["🥇","🥈","🥉"]
    for i,(uid,scores) in enumerate(users,1):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid}"
        embed.add_field(name=f"{medals[i-1] if i<=3 else f'`{i}.`'} {name}",value=L('**{}** correct', scores.get('total', 0)),inline=False)
    await ctx.send(embed=embed)

# ============================================================
# ============================================================

@bot.command(name="ping")
async def ping_p(ctx):
    await ctx.send(embed=discord.Embed(description=L('🏓 **Pong!** `{}ms`', round(bot.latency * 1000)),color=0xff6b35))


@bot.command(name="afk")
async def afk_p(ctx, *, reason: str = "AFK"):
    if user_restricted(ctx.author.id, "afk"):
        await notify_restricted(ctx, "afk")
        return
    afk_db[ctx.author.id] = {"reason":reason}
    await ctx.send(embed=discord.Embed(description=t(ctx.guild.id,"afk_set",ctx.author.mention,reason),color=0xff6b35),delete_after=10)




# ============================================================
# COUNTING SYSTEM
# ============================================================

# ============================================================
# OWNER COMMANDS
# ============================================================










# ============================================================
# SETUP COMMANDS
# ============================================================
@setup_group.command(name="log", description="Set the log channel")
@app_commands.describe(channel="Channel for admin logs")
async def setup_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["log"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Log channel: {}', channel.mention),color=0x57F287))

@setup_group.command(name="ticket", description="Set the ticket panel channel")
@app_commands.describe(channel="Channel for ticket panel")
async def setup_ticket(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["ticket"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Ticket channel: {}', channel.mention),color=0x57F287))

@setup_group.command(name="ticketstaff", description="Set the ticket staff role")
@app_commands.describe(role="Staff role for tickets")
async def setup_ticketstaff(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["ticketstaff"] = str(role.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Ticket staff role: {}', role.mention),color=0x57F287))

@setup_group.command(name="welcome", description="Set the welcome message channel")
@app_commands.describe(channel="Channel for welcome messages")
async def setup_welcome(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["welcome"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Welcome channel: {}', channel.mention),color=0x57F287))


@setup_group.command(name="levelup", description="Set the level-up notification channel")
@app_commands.describe(channel="Channel for level-up messages")
async def setup_levelup(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["levelup"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Level-up channel: {}', channel.mention),color=0x57F287))

@setup_group.command(name="casino", description="Set the casino-only channel")
@app_commands.describe(channel="Channel for economy commands")
async def setup_casino(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["casino"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Casino/Economy channel: {}', channel.mention),color=0x57F287))

@setup_group.command(name="botcom", description="Set the bot commands channel")
@app_commands.describe(channel="Channel where general bot commands work")
async def setup_botcom(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["botcom"] = str(channel.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Bot commands channel: {}', channel.mention),color=0x57F287))

@setup_group.command(name="prefix", description="Set the bot prefix")
@app_commands.describe(prefix="New prefix (1-3 chars)")
async def setup_prefix(interaction: discord.Interaction, prefix: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    if len(prefix) > 3: await interaction.response.send_message(L('❌ Max 3 characters!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["prefix"] = prefix; save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=t(interaction.guild.id,"prefix_set",prefix),color=0x57F287))

@setup_group.command(name="mutedrole", description="Set the muted role")
@app_commands.describe(role="Role to use for muting members")
async def setup_mutedrole(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["mutedrole"] = str(role.id); save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Muted role set to {}!\nThis role will be given when `.mute` is used.', role.mention),color=0x57F287))


@setup_group.command(name="leveldiff", description="Set XP difficulty")
@app_commands.describe(difficulty="XP gain difficulty")
@app_commands.choices(difficulty=[app_commands.Choice(name=v["label"],value=k) for k,v in LEVEL_DIFFICULTIES.items()])
async def setup_leveldiff(interaction: discord.Interaction, difficulty: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["leveldiff"] = difficulty; save_settings()
    cfg = LEVEL_DIFFICULTIES[difficulty]
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ XP difficulty: **{}**\nXP per message: {}-{}', L(cfg['label']), cfg['xp_min'], cfg['xp_max']),color=0x57F287))

@setup_group.command(name="warnpunish", description="Set automatic punishments for warns")
@app_commands.describe(warns="Number of warns", action="Punishment action")
@app_commands.choices(action=[app_commands.Choice(name="Mute",value="mute"),app_commands.Choice(name="Kick",value="kick"),app_commands.Choice(name="Ban",value="ban"),app_commands.Choice(name="None",value="none")])
async def setup_warnpunish(interaction: discord.Interaction, warns: int, action: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id)
    if "warnpunish" not in s: s["warnpunish"] = {}
    if action == "none": s["warnpunish"].pop(str(warns), None)
    else: s["warnpunish"][str(warns)] = action
    save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ {} warns → **{}**!', warns, action),color=0x57F287))


@setup_group.command(name="tickettitle", description="Set the ticket panel title and description")
@app_commands.describe(title="Panel title", description="Panel description")
async def setup_tickettitle(interaction: discord.Interaction, title: str, description: str = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["ticket_panel_title"] = title
    if description: s["ticket_panel_desc"] = description
    save_settings()
    embed = discord.Embed(title=L('✅ Panel Updated'), color=0x57F287)
    embed.add_field(name=L('Title'), value=title, inline=False)
    if description: embed.add_field(name=L('Description'), value=description, inline=False)
    await interaction.response.send_message(embed=embed)


@setup_group.command(name="feature", description="Enable or disable a server feature")
@app_commands.describe(feature="Feature to toggle", enabled="on or off")
@app_commands.choices(feature=[app_commands.Choice(name=v,value=k) for k,v in FEATURE_LABELS.items()],
    enabled=[app_commands.Choice(name="✅ Enable",value="enabled"),app_commands.Choice(name="❌ Disable",value="disabled")])
async def setup_feature(interaction: discord.Interaction, feature: str, enabled: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["features"][feature] = enabled; save_settings()
    status = L('✅ Enabled') if enabled == 'enabled' else L('❌ Disabled')
    hint = ("\n" + L('➡️ Next: choose the voice channels with `/setup vc` (Voice XP gives nothing until you do).')) if feature == "vcxp" and enabled == "enabled" and not s.get("vc_channels") else ""
    await interaction.response.send_message(embed=discord.Embed(description=f"{status} **{L(FEATURE_LABELS.get(feature,feature))}**!{hint}",color=0x57F287 if enabled=="enabled" else 0xED4245))







# ============================================================
# REACTION ROLES SLASH COMMANDS
# ============================================================




# ============================================================
# SLASH COMMANDS
# ============================================================
@bot.tree.command(name="ping", description="Check bot latency")
async def ping_s(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(description=L('🏓 **Pong!** `{}ms`', round(bot.latency * 1000)),color=0xff6b35))

@bot.tree.command(name="help", description="Show help menu")
async def help_s(interaction: discord.Interaction):
    gid = interaction.guild.id if interaction.guild else 0
    s = get_settings(gid); pfx = s.get("prefix",".")
    embed = discord.Embed(title=L('📖 Versa Bot'),description=L('**Prefix:** `{}` | Support: {}', pfx, SUPPORT_LINK),color=0xff6b35)
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, view=HelpView(pfx))

@bot.tree.command(name="language", description="Change server language")
@app_commands.guild_only()
@app_commands.describe(lang="Language to use")
@app_commands.choices(lang=[app_commands.Choice(name="🇬🇧 English",value="en"),app_commands.Choice(name="🇹🇷 Turkish",value="tr"),app_commands.Choice(name="🇷🇺 Russian",value="ru")])
async def language_s(interaction: discord.Interaction, lang: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L('❌ No permission!'), ephemeral=True); return
    s = get_settings(interaction.guild.id); s["language"] = lang; save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=t(interaction.guild.id,"language_set"),color=0x57F287))


@bot.tree.command(name="userinfo", description="Get user information")
@app_commands.guild_only()
@app_commands.describe(member="Member to check")
async def userinfo_s(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    embed = discord.Embed(title=str(target), color=target.color if target.color != discord.Color.default() else 0xff6b35)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name=L('🆔 ID'), value=f"`{target.id}`", inline=True)
    embed.add_field(name=L('📛 Nickname'), value=target.nick or "None", inline=True)
    embed.add_field(name=L('🤖 Bot'), value=L('Yes') if target.bot else L('No'), inline=True)
    embed.add_field(name=L('📅 Account Created'), value=dts(target.created_at,"R"), inline=True)
    embed.add_field(name=L('📅 Server Joined'), value=dts(target.joined_at,"R") if target.joined_at else "?", inline=True)
    roles = [r.mention for r in target.roles[1:]][:10]
    embed.add_field(name=L('🎭 Roles ({})', len(target.roles) - 1), value=" ".join(roles) or "None", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Get server information")
@app_commands.guild_only()
async def serverinfo_s(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=g.name, color=0xff6b35)
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name=L('🆔 ID'), value=f"`{g.id}`", inline=True)
    embed.add_field(name=L('👑 Owner'), value=f"<@{g.owner_id}>", inline=True)
    embed.add_field(name=L('📅 Created'), value=dts(g.created_at,"R"), inline=True)
    embed.add_field(name=L('👥 Members'), value=f"`{g.member_count}`", inline=True)
    embed.add_field(name=L('💬 Channels'), value=L('`{}` text | `{}` voice', len(g.text_channels), len(g.voice_channels)), inline=True)
    embed.add_field(name=L('🎭 Roles'), value=f"`{len(g.roles)}`", inline=True)
    embed.add_field(name=L('🌐 Language'), value=settings_db.get(str(g.id),{}).get("language","en").upper(), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="afk", description="Set your AFK status")
@app_commands.describe(reason="AFK reason")
async def afk_s(interaction: discord.Interaction, reason: str = "AFK"):
    if user_restricted(interaction.user.id, "afk"):
        await interaction.response.send_message(restricted_text("afk"), ephemeral=True)
        return
    afk_db[interaction.user.id] = {"reason": reason}
    await interaction.response.send_message(embed=discord.Embed(description=t(interaction.guild.id if interaction.guild else 0,"afk_set",interaction.user.mention,reason),color=0xff6b35))



@bot.tree.command(name="balance", description="Check your balance")
@app_commands.guild_only()
@app_commands.describe(member="Member to check")
async def balance_s(interaction: discord.Interaction, member: discord.Member = None):
    if not await slash_check_feature(interaction, "economy"): return
    target = member or interaction.user
    econ = get_econ(interaction.guild.id, target.id)
    embed = discord.Embed(title=f"💰 {target.display_name}", color=0x57F287)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name=L('👝 Wallet'), value=f"${econ['wallet']:,}", inline=True)
    embed.add_field(name=L('🏦 Bank'), value=f"${econ['bank']:,}", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="daily", description="Claim your daily reward")
@app_commands.guild_only()
async def daily_s(interaction: discord.Interaction):
    if not await slash_check_feature(interaction, "economy"): return
    gid = interaction.guild.id; econ = get_econ(gid, interaction.user.id)
    now = datetime.now(timezone.utc); last = econ.get("last_daily")
    if last:
        diff = (now - datetime.fromisoformat(last)).total_seconds()
        if diff < 86400:
            h,m = int((86400-diff)//3600), int(((86400-diff)%3600)//60)
            await interaction.response.send_message(embed=discord.Embed(description=t(gid,"daily_wait",f"{h}h {m}m"),color=0xED4245),ephemeral=True); return
    amount = random.randint(200,500); econ["wallet"]+=amount; econ["last_daily"]=now.isoformat(); save_econ()
    await interaction.response.send_message(embed=discord.Embed(description=t(gid,"daily_claimed",f"{amount:,}",f"{econ['wallet']:,}"),color=0x57F287))

@bot.tree.command(name="rank", description="Check your rank")
@app_commands.guild_only()
@app_commands.describe(member="Member to check")
async def rank_s(interaction: discord.Interaction, member: discord.Member = None):
    if not await slash_check_feature(interaction, "leveling"): return
    target = member or interaction.user; gid = interaction.guild.id
    udata = get_user_xp(gid, target.id); xp = udata["xp"]; level = get_level(xp, gid)
    next_xp = xp_for_level(level+1, gid); prev_xp = xp_for_level(level, gid)
    progress = xp-prev_xp; needed = next_xp-prev_xp
    pct = int((progress/needed)*20) if needed else 20
    bar = "▰"*pct + "▱"*(20-pct)
    embed = discord.Embed(title=f"📊 {target.display_name}", color=0xff6b35)
    embed.add_field(name=L('Level'),value=f"**{level}**",inline=True)
    embed.add_field(name=L('XP'),value=f"**{xp:,}**",inline=True)
    embed.add_field(name=L('Progress'),value=f"`{bar}`\n{progress:,}/{needed:,}",inline=False)
    embed.add_field(name=L('💬 Messages'), value=msg_stats_text(gid, target.id), inline=False)
    _mf = msg_stats_footer(gid)
    if _mf:
        embed.set_footer(text=_mf)
    embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="View XP leaderboard")
@app_commands.guild_only()
async def leaderboard_s(interaction: discord.Interaction):
    if not await slash_check_feature(interaction, "leveling"): return
    gid = str(interaction.guild.id)
    if gid not in levels_db or not levels_db[gid]: await interaction.response.send_message(L('❌ No data!'), ephemeral=True); return
    users = sorted(levels_db[gid].items(),key=lambda x:x[1].get("xp",0),reverse=True)[:10]
    embed = discord.Embed(title=L('📊 XP Leaderboard'), color=0xff6b35)
    medals = ["🥇","🥈","🥉"]
    for i,(uid,data) in enumerate(users,1):
        m = interaction.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid}"
        xp = data.get("xp",0); lvl = get_level(xp, int(gid))
        embed.add_field(name=f"{medals[i-1] if i<=3 else f'`{i}.`'} {name}",value=L('Level **{}** | **{:,}** XP', lvl, xp),inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="flag-leaderboard", description="View flag game leaderboard")
@app_commands.guild_only()
async def flb_s(interaction: discord.Interaction):
    if not await slash_check_feature(interaction, "flag"): return
    gid = str(interaction.guild.id); data = flag_scores_db.get(gid,{})
    if not data: await interaction.response.send_message(L('❌ No scores yet!'), ephemeral=True); return
    users = sorted(data.items(),key=lambda x:x[1].get("total",0),reverse=True)[:10]
    embed = discord.Embed(title=L('🏳️ Flag Leaderboard'), color=0xff6b35)
    medals = ["🥇","🥈","🥉"]
    for i,(uid,scores) in enumerate(users,1):
        m = interaction.guild.get_member(int(uid))
        name = m.display_name if m else f"User {uid}"
        embed.add_field(name=f"{medals[i-1] if i<=3 else f'`{i}.`'} {name}",value=L('**{}** correct', scores.get('total', 0)),inline=False)
    await interaction.response.send_message(embed=embed)




# ============================================================
# ROBUSTNESS - non-blocking flush, rate limits, housekeeping, DB backups, graceful shutdown
# ============================================================
_bg_tasks = []

def keep_task(coro):
    """asyncio only keeps weak references to tasks - hold on to ours so they are never garbage-collected."""
    task = asyncio.create_task(coro)
    _bg_tasks.append(task)
    return task

async def _touch_all_async(name):
    kind, data = _kinds[name], _stores[name]
    if kind == "nested":
        for k1 in list(data):
            users = data.get(k1)
            if isinstance(users, dict):
                _touched[name].update((k1, k2) for k2 in list(users))
            await asyncio.sleep(0)
        _touched[name].update(_last[name])
    else:
        touch_all(name)

async def flush_pending(full=False):
    """Serialize touched rows in small slices (never blocks the event loop), then write them in a worker thread."""
    changes = []
    for name in list(_stores):
        if full:
            await _touch_all_async(name)
        batch = list(_touched[name])
        _touched[name] = set()
        for i in range(0, len(batch), 400):
            changes += _collect_store(name, batch[i:i + 400])
            await asyncio.sleep(0)
    if changes:
        try:
            await asyncio.to_thread(_write, changes)
        except Exception as e:
            print(f"[DB] write failed, will retry: {e}")
            _restore_failed(changes)

async def flush_loop():
    await bot.wait_until_ready()
    ticks = 0
    while not bot.is_closed():
        await asyncio.sleep(3)
        ticks += 1
        try:
            await flush_pending(full=(ticks % 300 == 0))      # full safety-net scan every 15 minutes
            if ticks % 200 == 0:
                housekeeping()
        except Exception as e:
            print(f"[DB] flush loop error: {e}")

# ---------- per-user command rate limit (protects the bot from command spam) ----------
_cmd_hits = {}

def rate_limited(uid, limit=6, window=5.0):
    if uid == BOT_CREATOR_ID:
        return False
    now = _time.monotonic()
    q = _cmd_hits.setdefault(uid, collections.deque())
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False

# ---------- log channel limiter: a raid must not make the bot hit Discord's rate limits ----------
_log_buckets = {}

async def send_log(guild, embed):
    s = get_settings(guild.id)
    if not s.get("log"):
        return
    now = _time.monotonic()
    b = _log_buckets.setdefault(guild.id, [5.0, now, 0])          # [tokens, last refill, dropped]
    b[0] = min(5.0, b[0] + (now - b[1]))
    b[1] = now
    if b[0] < 1:
        b[2] += 1
        return
    b[0] -= 1
    try:
        ch = guild.get_channel(int(s["log"]))
        if ch is None:
            ch = await bot.fetch_channel(int(s["log"]))
        if b[2]:
            dropped, b[2] = b[2], 0
            await ch.send(L("⚠️ {} log entries were skipped to stay inside Discord's rate limits.", dropped))
        await ch.send(embed=embed)
    except Exception:
        pass

# ---------- housekeeping ----------
def prune_giveaways(days=7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    for gid in list(giveaways_db):
        for ga_id in list(giveaways_db[gid]):
            ga = giveaways_db[gid][ga_id]
            try:
                ends = datetime.fromisoformat(ga["ends_at"])
            except Exception:
                continue
            if ga.get("ended") and ends < cutoff:
                del giveaways_db[gid][ga_id]
                removed += 1
        if not giveaways_db[gid]:
            del giveaways_db[gid]
    if removed:
        touch_all("giveaways")
    return removed

def housekeeping():
    now, mono = _time.time(), _time.monotonic()
    for k in [k for k, v in xp_cooldown.items() if now - v > 120]:
        del xp_cooldown[k]
    for k in [k for k, v in _dm_rate.items() if not v or now - v[-1] > 120]:
        del _dm_rate[k]
    for k in [k for k, v in _modmail_cd.items() if now - v > 300]:
        del _modmail_cd[k]
    for k in [k for k, q in _cmd_hits.items() if not q or mono - q[-1] > 60]:
        del _cmd_hits[k]
    for k in [k for k, b in _log_buckets.items() if mono - b[1] > 600 and not b[2]]:
        del _log_buckets[k]
    prune_giveaways()
    prune_polls()
    for k in [k for k, v in _ban_notice.items() if now - v > 3600]:
        del _ban_notice[k]
    for k in [k for k, v in _restrict_notice.items() if now - v > 3600]:
        del _restrict_notice[k]

# ---------- backup: a consistent snapshot of the SQLite file, zipped ----------
def _snapshot_zip():
    tmp = f"versa_snapshot_{os.getpid()}.db"
    try:
        dst = sqlite3.connect(tmp)
        with _db_lock:
            _connect().backup(dst)
        dst.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "versa.db")
        return buf
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

async def send_backup():
    try:
        owner = await bot.fetch_user(BOT_CREATOR_ID)
        await flush_pending(full=True)
        buf = await asyncio.to_thread(_snapshot_zip)
        size = buf.tell()
        buf.seek(0)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
        if size > 24 * 1024 * 1024:
            await owner.send(f"⚠️ The backup is {size / 1048576:.1f} MB - too big for Discord. Copy versa.db from the VPS instead.")
            return
        await owner.send(f"💾 Backup {stamp} UTC - {len(bot.guilds)} servers", file=discord.File(buf, filename=f"versa_backup_{stamp}.zip"))
        await _prune_old_backups(owner)
    except Exception as e:
        print(f"[BACKUP] failed: {e}")

def _on_sigterm(signum, frame):
    """`pkill` / systemd stop: write everything that is still in memory, then exit."""
    try:
        flush_now()
    finally:
        os._exit(0)






































# ============================================================
# CORE HELPERS — language context (L), silent deletes, XP flush, scheduler, role safety
# ============================================================
_LANG = contextvars.ContextVar("versa_lang", default="en")

def set_lang(guild_id):
    """Remember the server language for the current task so L() answers in it."""
    try:
        lang = settings_db.get(str(guild_id), {}).get("language", "en") if guild_id else "en"
        _LANG.set(lang if lang in ("en", "tr", "ru") else "en")
    except Exception:
        pass

PHRASES = {"tr": {}, "ru": {}}

def _load_phrases(table):
    for raw in table.split("\n"):
        parts = raw.rstrip("\r").split(" ||| ")
        if len(parts) != 3 or not parts[0]:
            continue
        en = parts[0].replace("\\n", "\n")
        PHRASES["tr"][en] = parts[1].replace("\\n", "\n")
        PHRASES["ru"][en] = parts[2].replace("\\n", "\n")

def L(text, *args):
    """Translate an English phrase into the current server language (falls back to English)."""
    out = PHRASES.get(_LANG.get(), {}).get(text, text)
    if args:
        try:
            out = out.format(*args)
        except Exception:
            try:
                out = text.format(*args)
            except Exception:
                pass
    return out

_PHRASE_TABLE = r'''
{} players ||| {} oyuncu ||| игроков: {}
## 🎒 {}'s Inventory ||| ## 🎒 {} - Envanter ||| ## 🎒 Инвентарь: {}
## 🛒 {} Store ||| ## 🛒 {} Market ||| ## 🛒 Магазин {}
Banned by ID - this account was not in the server. ||| ID ile yasaklandı - bu hesap sunucuda değildi. ||| Забанен по ID - этого аккаунта не было на сервере.
Bet per player: ${:,} ||| Oyuncu başı bahis: ${:,} ||| Ставка с игрока: ${:,}
Blackjack! ||| Blackjack! ||| Блэкджек!
Bust ||| Battın ||| Перебор
Buy ||| Satın al ||| Купить
CASHED OUT ||| PARA ALINDI ||| ЗАБРАНО
Card ||| Kart ||| Карта
Cash out ${:,} ||| Parayı al ${:,} ||| Забрать ${:,}
Cash out ||| Parayı al ||| Забрать
Correct guesses: {} ||| Doğru tahmin: {} ||| Верных ответов: {}
Dealer ||| Krupiye ||| Дилер
Dealer: **{}** ||| Krupiye: **{}** ||| Дилер: **{}**
Flipping... **{}** for **${:,}** ||| Atılıyor... **{}**, **${:,}** ||| Подбрасываем... **{}** на **${:,}**
Higher ||| Büyük ||| Больше
Lower ||| Küçük ||| Меньше
Higher or Lower ||| Büyük mü Küçük mü ||| Больше или меньше
Higher: **{}** chance · Lower: **{}** chance ||| Büyük: **{}** şans · Küçük: **{}** şans ||| Больше: шанс **{}** · Меньше: шанс **{}**
LOST ||| KAYBETTİN ||| ПРОИГРЫШ
MAX WIN ||| MAKSİMUM ||| МАКСИМУМ
Open {}inv and press Use to use it. ||| Kullanmak için {}inv aç ve Kullan butonuna bas. ||| Открой {}inv и нажми «Использовать».
Players take turns - only the player whose turn it is can press the buttons. ||| Oyuncular sırayla oynar - butonlara yalnızca sırası gelen basabilir. ||| Игроки ходят по очереди - кнопки нажимает только тот, чей ход.
Press **Buy** under an item. Your items are in `{}inv`. ||| Bir eşyanın altındaki **Satın al** butonuna bas. Eşyaların `{}inv` içinde. ||| Нажми **Купить** под предметом. Твои предметы - в `{}inv`.
Push ||| Berabere ||| Ничья
Spinning... bet **${:,}** ||| Dönüyor... bahis **${:,}** ||| Крутим... ставка **${:,}**
Hit ||| Kart çek ||| Ещё
Stand ||| Dur ||| Хватит
Double ||| İkiye katla ||| Удвоить
Accept ||| Kabul et ||| Принять
Decline ||| Reddet ||| Отказаться
Start now ||| Şimdi başlat ||| Начать сейчас
Usage: `{}` ||| Kullanım: `{}` ||| Использование: `{}`
Use ||| Kullan ||| Использовать
Waiting ||| Bekliyor ||| Ждёт
Will the next card be higher or lower? A tie loses. ||| Sonraki kart büyük mü küçük mü? Eşitlik kaybettirir. ||| Следующая карта больше или меньше? Ничья - проигрыш.
Win ||| Kazanç ||| Выигрыш
{} invites you to blackjack. Bet: **${:,}** each.\nPress **Accept** within {} seconds. ||| {} seni blackjack oynamaya çağırıyor. Bahis: kişi başı **${:,}**.\n{} saniye içinde **Kabul et** butonuna bas. ||| {} зовёт тебя в блэкджек. Ставка: **${:,}** с каждого.\nНажми **Принять** в течение {} секунд.
⏰ Time is up - auto cash out: **${:,}**. ||| ⏰ Süre doldu - para otomatik alındı: **${:,}**. ||| ⏰ Время вышло - выигрыш забран автоматически: **${:,}**.
⏳ It is not your turn! ||| ⏳ Sıra sende değil! ||| ⏳ Сейчас не твой ход!
✅ **{}** - correct! Cash out or keep going. ||| ✅ **{}** - doğru! Paranı al ya da devam et. ||| ✅ **{}** - верно! Забери выигрыш или играй дальше.
✅ **{}** wins **+${:,}** ||| ✅ **{}** kazandı **+${:,}** ||| ✅ **{}** выигрывает **+${:,}**
✅ Used **{}** - you got {}! ||| ✅ **{}** kullanıldı - {} rolünü aldın! ||| ✅ **{}** использован - ты получил {}!
✅ Used **{}**. ||| ✅ **{}** kullanıldı. ||| ✅ **{}** использован.
✅ You bought **{}** for **${:,}**. Wallet: **${:,}** ||| ✅ **{}** satın alındı: **${:,}**. Cüzdan: **${:,}** ||| ✅ Ты купил **{}** за **${:,}**. Кошелёк: **${:,}**
❌ **{}** busted: **-${:,}** ||| ❌ **{}** battı: **-${:,}** ||| ❌ **{}** - перебор: **-${:,}**
❌ **{}** is already banned here. ||| ❌ **{}** bu sunucuda zaten yasaklı. ||| ❌ **{}** уже забанен здесь.
❌ **{}** loses **-${:,}** ||| ❌ **{}** kaybetti **-${:,}** ||| ❌ **{}** проигрывает **-${:,}**
❌ **{}** was wrong - the card was {}. You lost **${:,}**. ||| ❌ **{}** yanlış - kart {} çıktı. **${:,}** kaybettin. ||| ❌ **{}** - мимо, выпала карта {}. Ты проиграл **${:,}**.
❌ Already in a card game: {} ||| ❌ Zaten bir kart oyununda: {} ||| ❌ Уже в карточной игре: {}
❌ No Discord account has the ID `{}`. ||| ❌ `{}` ID'li bir Discord hesabı yok. ||| ❌ Нет аккаунта Discord с ID `{}`.
❌ Only {} can do this. ||| ❌ Bunu yalnızca {} yapabilir. ||| ❌ Это может сделать только {}.
❌ This invitation is not for you. ||| ❌ Bu davet senin için değil. ||| ❌ Это приглашение не для тебя.
❌ This is not your inventory! ||| ❌ Bu senin envanterin değil! ||| ❌ Это не твой инвентарь!
❌ This item is no longer in the store. ||| ❌ Bu eşya artık markette yok. ||| ❌ Этого предмета больше нет в магазине.
❌ You already answered. ||| ❌ Zaten cevap verdin. ||| ❌ Ты уже ответил.
❌ You already have a card game running! ||| ❌ Zaten devam eden bir kart oyunun var! ||| ❌ У тебя уже идёт карточная игра!
❌ You can invite up to {} members (no bots). ||| ❌ En fazla {} üye davet edebilirsin (bot olmaz). ||| ❌ Можно пригласить до {} участников (без ботов).
🃏 Blackjack table ||| 🃏 Blackjack masası ||| 🃏 Стол блэкджека
🃏 Higher or Lower ||| 🃏 Büyük mü Küçük mü ||| 🃏 Больше или меньше
🃏 Nobody accepted - the table is closed and the bet was returned. ||| 🃏 Kimse kabul etmedi - masa kapandı ve bahis iade edildi. ||| 🃏 Никто не принял - стол закрыт, ставка возвращена.
🃏 The table was cancelled and the bet was returned. ||| 🃏 Masa iptal edildi ve bahis iade edildi. ||| 🃏 Стол отменён, ставка возвращена.
🎉 **{}** - Blackjack! **+${:,}** ||| 🎉 **{}** - Blackjack! **+${:,}** ||| 🎉 **{}** - блэкджек! **+${:,}**
🎭 Role: {} ||| 🎭 Rol: {} ||| 🎭 Роль: {}
🎰 Slots ||| 🎰 Slot ||| 🎰 Слоты
🏆 Maximum reached - auto cash out: **+${:,}** ||| 🏆 Maksimuma ulaştın - para otomatik alındı: **+${:,}** ||| 🏆 Достигнут максимум - выигрыш забран: **+${:,}**
👉 **{}** is playing ({}s) ||| 👉 Sıra **{}** oyuncusunda ({} sn) ||| 👉 Ходит **{}** ({} с)
💰 **${:,}** ||| 💰 **${:,}** ||| 💰 **${:,}**
💰 Cashed out **${:,}** (×{:,.2f}). ||| 💰 **${:,}** alındı (×{:,.2f}). ||| 💰 Забрано **${:,}** (×{:,.2f}).
💵 **+${:,}** · Wallet: **${:,}** ||| 💵 **+${:,}** · Cüzdan: **${:,}** ||| 💵 **+${:,}** · Кошелёк: **${:,}**
🤝 **{}** - push, bet returned ||| 🤝 **{}** - berabere, bahis iade ||| 🤝 **{}** - ничья, ставка возвращена
🪙 Coinflip ||| 🪙 Yazı Tura ||| 🪙 Монетка
\nℹ️ The store is still switched off. Enable it with /setup feature. ||| \nℹ️ Market hâlâ kapalı. /setup feature ile aç. ||| \nℹ️ Магазин всё ещё отключён. Включи его через /setup feature.
\n🎭 Role: {} ||| \n🎭 Rol: {} ||| \n🎭 Роль: {}
**Prefix:** `{}`\nSupport: {}\n\nPick a category below. ||| **Önek:** `{}`\nDestek: {}\n\nAşağıdan bir kategori seç. ||| **Префикс:** `{}`\nПоддержка: {}\n\nВыбери категорию ниже.
**Prefix:** `{}` | Support: {} ||| **Önek:** `{}` | Destek: {} ||| **Префикс:** `{}` | Поддержка: {}
**Reason:** {}\n**By:** <@{}>\n**Date:** {} ||| **Sebep:** {}\n**Yetkili:** <@{}>\n**Tarih:** {} ||| **Причина:** {}\n**Модератор:** <@{}>\n**Дата:** {}
**Summary:** {}\n**Total:** {} ||| **Özet:** {}\n**Toplam:** {} ||| **Сводка:** {}\n**Всего:** {}
**Winners:** {} ||| **Kazananlar:** {} ||| **Победители:** {}
**{}** correct ||| **{}** doğru ||| **{}** верно
**{}** messages were deleted in {}. ||| **{}** mesaj {} kanalında silindi. ||| **{}** сообщений удалено в {}.
*No items yet!* ||| *Henüz eşya yok!* ||| *Предметов пока нет!*
Account Age ||| Hesap Yaşı ||| Возраст аккаунта
After ||| Sonra ||| После
Announced by {} ||| Duyuran: {} ||| Объявил: {}
Anyone who sends a message in this channel is banned automatically and their recent messages are deleted.\nThis catches spam bots and hacked accounts. Do not type here! ||| Bu kanala mesaj gönderen herkes otomatik olarak banlanır ve son mesajları silinir.\nBu, spam botlarını ve çalınmış hesapları yakalar. Buraya yazma! ||| Любой, кто отправит сообщение в этот канал, будет автоматически забанен, а его недавние сообщения удалены.\nТак ловят спам-ботов и взломанные аккаунты. Не пиши здесь!
Attachments ||| Ekler ||| Вложения
Author ||| Yazar ||| Автор
Before ||| Önce ||| До
Bet: ${:,} ||| Bahis: ${:,} ||| Ставка: ${:,}
By ||| Yapan ||| Кем
Case #{} ||| Kayıt #{} ||| Дело #{}
Channel ||| Kanal ||| Канал
Content ||| İçerik ||| Содержимое
Could not ban {} (`{}`): {} ||| {} (`{}`) banlanamadı: {} ||| Не удалось забанить {} (`{}`): {}
Count up together, starting at **1**!\nAnything that breaks the order is deleted. ||| Birlikte say, **1**'den başla!\nSırayı bozan her şey silinir. ||| Считайте вместе, начиная с **1**!\nВсё, что нарушает порядок, удаляется.
Dealer hand (?) ||| Krupiye eli (?) ||| Рука дилера (?)
Dealer hand ({}) ||| Krupiye eli ({}) ||| Рука дилера ({})
Description ||| Açıklama ||| Описание
Duration ||| Süre ||| Длительность
Duration: **{}** ||| Süre: **{}** ||| Длительность: **{}**
Emoji ||| Emoji ||| Эмодзи
Ends ||| Bitiş ||| Конец
Entries ||| Katılımcı ||| Участники
Expires ||| Bitiş zamanı ||| Истекает
Heads ||| Yazı ||| Орёл
Hey {}! 👋\n\nDescribe your issue and a staff member will help you soon.\n**Category:** {} {} ||| Merhaba {}! 👋\n\nSorununu anlat, bir yetkili yakında yardımcı olacak.\n**Kategori:** {} {} ||| Привет, {}! 👋\n\nОпиши свою проблему, и скоро тебе поможет сотрудник.\n**Категория:** {} {}
Host ||| Düzenleyen ||| Организатор
Item ||| Eşya ||| Предмет
Jump ||| Git ||| Перейти
Level ||| Seviye ||| Уровень
Level **{}** | **{:,}** XP ||| Seviye **{}** | **{:,}** XP ||| Уровень **{}** | **{:,}** XP
Member ||| Üye ||| Участник
Member Count ||| Üye Sayısı ||| Число участников
Message ||| Mesaj ||| Сообщение
Message `{}` ||| Mesaj `{}` ||| Сообщение `{}`
No ||| Hayır ||| Нет
Not set ||| Ayarlanmamış ||| Не задано
Permanent ||| Kalıcı ||| Навсегда
Poll by {} ||| Anketi açan: {} ||| Опрос от {}
Prefix: {} ||| Önek: {} ||| Префикс: {}
Price ||| Fiyat ||| Цена
Progress ||| İlerleme ||| Прогресс
Reason ||| Sebep ||| Причина
Remaining ||| Kalan ||| Осталось
Result ||| Sonuç ||| Результат
Role ||| Rol ||| Роль
Role Given ||| Verilen Rol ||| Выданная роль
Roles ||| Roller ||| Роли
Sent by {} via Versa Bot ||| {} tarafından Versa Bot ile gönderildi ||| Отправил {} через Versa Bot
Showing 10 of {} ||| {} kayıttan 10'u gösteriliyor ||| Показано 10 из {}
Tails ||| Tura ||| Решка
This channel has been locked by a moderator.\n**Can write:** {} ||| Bu kanal bir moderatör tarafından kilitlendi.\n**Yazabilenler:** {} ||| Этот канал заблокирован модератором.\n**Могут писать:** {}
This channel has been locked by a moderator.\n**No one can write here.** ||| Bu kanal bir moderatör tarafından kilitlendi.\n**Burada kimse yazamaz.** ||| Этот канал заблокирован модератором.\n**Здесь никто не может писать.**
Title ||| Başlık ||| Заголовок
Use /setup feature to toggle ||| Açıp kapatmak için /setup feature kullan ||| Используй /setup feature для переключения
Use `{}buy <item name>` to purchase! ||| Satın almak için `{}buy <eşya adı>` yaz! ||| Чтобы купить, напиши `{}buy <название предмета>`!
User ||| Kullanıcı ||| Пользователь
Winners ||| Kazananlar ||| Победители
XP ||| XP ||| XP
Yes ||| Evet ||| Да
You have **10 seconds**! Type the country name in English. ||| **10 saniyen** var! Ülke adını İngilizce yaz. ||| У тебя **10 секунд**! Напиши название страны по-английски.
Your hand ({}) ||| Elin ({}) ||| Твоя рука ({})
[Go to message]({}) ||| [Mesaja git]({}) ||| [Перейти к сообщению]({})
[Jump]({}) ||| [Git]({}) ||| [Перейти]({})
`{}` text | `{}` voice ||| `{}` yazı | `{}` ses ||| `{}` текстовых | `{}` голосовых
{} Case #{} — {} ||| {} Kayıt #{} — {} ||| {} Дело #{} — {}
{} Ticket #{:04d} ||| {} Ticket #{:04d} ||| {} Тикет #{:04d}
{} item(s) available ||| {} eşya mevcut ||| Доступно предметов: {}
{} {} — Case #{} ||| {} {} — Kayıt #{} ||| {} {} — Дело #{}
⏰ The blackjack game timed out and the bet was lost. ||| ⏰ Blackjack oyunu zaman aşımına uğradı ve bahis kaybedildi. ||| ⏰ Время игры в блэкджек вышло, ставка потеряна.
⏰ Time's up! It was **{}**! ||| ⏰ Süre doldu! Cevap **{}** idi! ||| ⏰ Время вышло! Это была **{}**!
⏱️ Slowmode set to **{}s** in {}! ||| ⏱️ Yavaş mod **{}sn** olarak ayarlandı: {}! ||| ⏱️ Медленный режим **{} с** установлен в {}!
⏱️ Timeout — {} ||| ⏱️ Zaman aşımı — {} ||| ⏱️ Тайм-аут — {}
⏳ A flag round is already running here! ||| ⏳ Burada zaten bir bayrak turu sürüyor! ||| ⏳ Здесь уже идёт раунд с флагами!
⏳ Working on {} for all members... ||| ⏳ {} rolü tüm üyeler için işleniyor... ||| ⏳ Обрабатываю роль {} для всех участников...
♻️ Channel reset by **{}**! ||| ♻️ Kanal **{}** tarafından sıfırlandı! ||| ♻️ Канал сброшен пользователем **{}**!
⚙️ Server Features ||| ⚙️ Sunucu Özellikleri ||| ⚙️ Функции сервера
⚙️ {} Settings ||| ⚙️ {} Ayarları ||| ⚙️ Настройки {}
⚠️ You already entered! ||| ⚠️ Zaten katıldın! ||| ⚠️ Ты уже участвуешь!
⚠️ {}'s Warnings ({}) ||| ⚠️ {} kullanıcısının Uyarıları ({}) ||| ⚠️ Предупреждения {} ({})
⛔ You are banned from using this bot. ||| ⛔ Bu botu kullanman yasaklandı. ||| ⛔ Тебе запрещено пользоваться этим ботом.
✅ **{}** has no moderation history. ||| ✅ **{}** kullanıcısının moderasyon geçmişi yok. ||| ✅ У **{}** нет истории модерации.
✅ **{}** is now logged! ||| ✅ **{}** artık kaydediliyor! ||| ✅ **{}** теперь записывается в лог!
✅ **{}** timeout removed! ||| ✅ **{}** zaman aşımı kaldırıldı! ||| ✅ Тайм-аут **{}** снят!
✅ **{}** unbanned! ||| ✅ **{}** banı kaldırıldı! ||| ✅ **{}** разбанен!
✅ **{}** was added for **${:,}**!{} ||| ✅ **{}** **${:,}** fiyatla eklendi!{} ||| ✅ **{}** добавлен за **${:,}**!{}
✅ **{}** was given to {}! ||| ✅ **{}** {} kişisine verildi! ||| ✅ **{}** передан {}!
✅ **{}** was removed from the store! ||| ✅ **{}** marketten kaldırıldı! ||| ✅ **{}** удалён из магазина!
✅ **{}**'s nickname is now `{}`! ||| ✅ **{}** kullanıcısının takma adı artık `{}`! ||| ✅ Ник **{}** теперь `{}`!
✅ **{}**'s nickname was reset! ||| ✅ **{}** kullanıcısının takma adı sıfırlandı! ||| ✅ Ник **{}** сброшен!
✅ Added ||| ✅ Eklenen ||| ✅ Добавлено
✅ Added **{}** level(s) to {}! Now: **Level {}** ||| ✅ **{}** seviye eklendi: {}! Şimdi: **Seviye {}** ||| ✅ Добавлено уровней: **{}** для {}! Теперь: **Уровень {}**
✅ Announcement sent to {}! ||| ✅ Duyuru {} kanalına gönderildi! ||| ✅ Объявление отправлено в {}!
✅ Bot commands channel: {} ||| ✅ Bot komutları kanalı: {} ||| ✅ Канал команд бота: {}
✅ Casino/Economy channel: {} ||| ✅ Casino/Ekonomi kanalı: {} ||| ✅ Канал казино/экономики: {}
✅ Cleared all reaction roles from `{}`! ||| ✅ `{}` mesajındaki tüm tepki rolleri temizlendi! ||| ✅ Все роли по реакции у `{}` очищены!
✅ Cleared all warns for {}! ||| ✅ {} için tüm uyarılar temizlendi! ||| ✅ Все предупреждения {} очищены!
✅ Counting channel: {}! ||| ✅ Sayı sayma kanalı: {}! ||| ✅ Канал для счёта: {}!
✅ Counting is switched off! ||| ✅ Sayı sayma kapatıldı! ||| ✅ Счёт отключён!
✅ Done! Changed **{}** members. ||| ✅ Tamam! **{}** üye değiştirildi. ||| ✅ Готово! Изменено участников: **{}**.
✅ Emoji **:{}:** added! {} ||| ✅ **:{}:** emojisi eklendi! {} ||| ✅ Эмодзи **:{}:** добавлено! {}
✅ Enabled ||| ✅ Açık ||| ✅ Включено
✅ Honeypot channel: {}!\n⚠️ Members must be able to see it and send messages there for the trap to work. Server admins are exempt. ||| ✅ Honeypot kanalı: {}!\n⚠️ Tuzağın çalışması için üyelerin kanalı görüp mesaj atabilmesi gerekir. Sunucu yöneticileri muaftır. ||| ✅ Канал-ловушка: {}!\n⚠️ Чтобы ловушка работала, участники должны видеть канал и писать в нём. Администраторы сервера освобождены.
✅ Honeypot is switched off! ||| ✅ Honeypot kapatıldı! ||| ✅ Ловушка отключена!
✅ Level {} gives {}! ||| ✅ Seviye {} artık {} rolünü veriyor! ||| ✅ Уровень {} теперь даёт {}!
✅ Level-up channel: {} ||| ✅ Seviye atlama kanalı: {} ||| ✅ Канал повышения уровня: {}
✅ Log channel: {} ||| ✅ Log kanalı: {} ||| ✅ Канал логов: {}
✅ Muted role set to {}!\nThis role will be given when `.mute` is used. ||| ✅ Susturma rolü {} olarak ayarlandı!\nBu rol `.mute` kullanıldığında verilir. ||| ✅ Роль мута: {}!\nЭта роль выдаётся при использовании `.mute`.
✅ No warnings! ||| ✅ Uyarı yok! ||| ✅ Предупреждений нет!
✅ On ||| ✅ Açık ||| ✅ Вкл
✅ Panel Updated ||| ✅ Panel Güncellendi ||| ✅ Панель обновлена
✅ Purchase Successful! ||| ✅ Satın Alma Başarılı! ||| ✅ Покупка совершена!
✅ Reaction Role Created! ||| ✅ Tepki Rolü Oluşturuldu! ||| ✅ Роль по реакции создана!
✅ Removed **{}** level(s) from {}! Now: **Level {}** ||| ✅ **{}** seviye silindi: {}! Şimdi: **Seviye {}** ||| ✅ Убрано уровней: **{}** у {}! Теперь: **Уровень {}**
✅ Removed {} → <@&{}> ||| ✅ Kaldırıldı: {} → <@&{}> ||| ✅ Удалено: {} → <@&{}>
✅ Reset {}'s level! ||| ✅ {} kullanıcısının seviyesi sıfırlandı! ||| ✅ Уровень {} сброшен!
✅ Role persist is on! Members who leave and rejoin get their roles back (roles with moderation permissions are never restored). ||| ✅ Rol koruma açık! Ayrılıp geri gelen üyeler rollerini geri alır (moderasyon yetkili roller asla geri verilmez). ||| ✅ Сохранение ролей включено! Участники, которые вышли и вернулись, получают роли обратно (роли с правами модерации не возвращаются).
✅ Set {} to **Level {}**! ||| ✅ {} **Seviye {}** olarak ayarlandı! ||| ✅ {} теперь **уровень {}**!
✅ Ticket channel: {} ||| ✅ Ticket kanalı: {} ||| ✅ Канал тикетов: {}
✅ Ticket panel sent to {}! ||| ✅ Ticket paneli {} kanalına gönderildi! ||| ✅ Панель тикетов отправлена в {}!
✅ Ticket staff role: {} ||| ✅ Ticket yetkili rolü: {} ||| ✅ Роль персонала тикетов: {}
✅ Used: {} ||| ✅ Kullanıldı: {} ||| ✅ Использовано: {}
✅ Welcome channel: {} ||| ✅ Karşılama kanalı: {} ||| ✅ Канал приветствий: {}
✅ Welcome role: {}! New members get it automatically. ||| ✅ Karşılama rolü: {}! Yeni üyeler bunu otomatik alır. ||| ✅ Приветственная роль: {}! Новые участники получают её автоматически.
✅ XP difficulty: **{}**\nXP per message: {}-{} ||| ✅ XP zorluğu: **{}**\nMesaj başına XP: {}-{} ||| ✅ Сложность XP: **{}**\nXP за сообщение: {}-{}
✅ You joined! Total entries: **{}** ||| ✅ Katıldın! Toplam katılımcı: **{}** ||| ✅ Ты участвуешь! Всего участников: **{}**
✅ You win! **+${:,}** ||| ✅ Kazandın! **+${:,}** ||| ✅ Ты выиграл! **+${:,}**
✅ {} got it! 🎉 It was **{}**! ||| ✅ {} bildi! 🎉 Cevap **{}** idi! ||| ✅ {} угадал! 🎉 Это была **{}**!
✅ {} warns → **{}**! ||| ✅ {} uyarı → **{}**! ||| ✅ {} предупреждений → **{}**!
✏️ Message Edited ||| ✏️ Mesaj Düzenlendi ||| ✏️ Сообщение изменено
✏️ Nickname Changed ||| ✏️ Takma Ad Değişti ||| ✏️ Ник изменён
❌ **{}** is no longer logged! ||| ❌ **{}** artık kaydedilmiyor! ||| ❌ **{}** больше не записывается в лог!
❌ Amount must be positive! ||| ❌ Miktar pozitif olmalı! ||| ❌ Сумма должна быть положительной!
❌ An item with this name already exists! ||| ❌ Bu isimde bir eşya zaten var! ||| ❌ Предмет с таким названием уже существует!
❌ Bust! You lost **${:,}** ||| ❌ Battın! **${:,}** kaybettin ||| ❌ Перебор! Ты потерял **${:,}**
❌ Can't pay yourself! ||| ❌ Kendine ödeme yapamazsın! ||| ❌ Нельзя заплатить самому себе!
❌ Can't rob yourself! ||| ❌ Kendini soyamazsın! ||| ❌ Нельзя ограбить самого себя!
❌ Cannot fetch flags right now, try again later! ||| ❌ Şu an bayraklar alınamıyor, sonra tekrar dene! ||| ❌ Сейчас не удаётся получить флаги, попробуй позже!
❌ Case `{}` not found! ||| ❌ `{}` numaralı kayıt bulunamadı! ||| ❌ Дело `{}` не найдено!
❌ Could not create the ticket: {} ||| ❌ Ticket oluşturulamadı: {} ||| ❌ Не удалось создать тикет: {}
❌ Dealer wins! You lost **${:,}** ||| ❌ Krupiye kazandı! **${:,}** kaybettin ||| ❌ Дилер выиграл! Ты потерял **${:,}**
❌ Disabled ||| ❌ Kapalı ||| ❌ Отключено
❌ Emoji not found! ||| ❌ Emoji bulunamadı! ||| ❌ Эмодзи не найдено!
❌ Game not found! ||| ❌ Oyun bulunamadı! ||| ❌ Игра не найдена!
❌ I cannot give that role: it is bot-managed, above my top role or has moderation permissions! ||| ❌ Bu rolü veremem: bot tarafından yönetiliyor, benim en yüksek rolümün üstünde veya moderasyon yetkileri var! ||| ❌ Я не могу выдать эту роль: она управляется ботом, выше моей высшей роли или имеет права модерации!
❌ I cannot manage that role! ||| ❌ Bu rolü yönetemem! ||| ❌ Я не могу управлять этой ролью!
❌ I could not react with that emoji. Use a normal emoji or one from this server. ||| ❌ Bu emojiyle tepki veremedim. Normal bir emoji veya bu sunucudan bir emoji kullan. ||| ❌ Не удалось поставить эту реакцию. Используй обычное эмодзи или эмодзи этого сервера.
❌ I don't have permission to do that! ||| ❌ Bunu yapmaya yetkim yok! ||| ❌ У меня нет прав для этого!
❌ I need the Ban Members permission first! ||| ❌ Önce Üyeleri Yasakla yetkisine ihtiyacım var! ||| ❌ Мне сначала нужно право «Банить участников»!
❌ Invalid argument! ||| ❌ Geçersiz argüman! ||| ❌ Неверный аргумент!
❌ Invalid duration! Use for example 10m, 2h or 1d. ||| ❌ Geçersiz süre! Örneğin 10m, 2h veya 1d kullan. ||| ❌ Неверная длительность! Например: 10m, 2h или 1d.
❌ Invalid emoji! ||| ❌ Geçersiz emoji! ||| ❌ Неверное эмодзи!
❌ Item `{}` was not found! ||| ❌ `{}` eşyası bulunamadı! ||| ❌ Предмет `{}` не найден!
❌ Item `{}` was not found! Use the store command to see all items. ||| ❌ `{}` eşyası bulunamadı! Tüm eşyaları görmek için market komutunu kullan. ||| ❌ Предмет `{}` не найден! Команда магазина покажет все предметы.
❌ Max 3 characters! ||| ❌ En fazla 3 karakter! ||| ❌ Максимум 3 символа!
❌ Message not found! Use the message ID or the message link. ||| ❌ Mesaj bulunamadı! Mesaj ID'sini veya mesaj bağlantısını kullan. ||| ❌ Сообщение не найдено! Используй ID сообщения или ссылку на него.
❌ Missing argument: `{}` ||| ❌ Eksik argüman: `{}` ||| ❌ Не хватает аргумента: `{}`
❌ No Manage Emojis permission! ||| ❌ Emojileri Yönet yetkim yok! ||| ❌ Нет права «Управлять эмодзи»!
❌ No XP data yet! ||| ❌ Henüz XP verisi yok! ||| ❌ Данных XP пока нет!
❌ No data yet! ||| ❌ Henüz veri yok! ||| ❌ Данных пока нет!
❌ No data! ||| ❌ Veri yok! ||| ❌ Нет данных!
❌ No permission! ||| ❌ Yetkin yok! ||| ❌ Нет прав!
❌ No scores yet! ||| ❌ Henüz skor yok! ||| ❌ Результатов пока нет!
❌ Off ||| ❌ Kapalı ||| ❌ Выкл
❌ Reaction role not found! ||| ❌ Tepki rolü bulunamadı! ||| ❌ Роль по реакции не найдена!
❌ Removed ||| ❌ Kaldırılan ||| ❌ Убрано
❌ Role persist is off. ||| ❌ Rol koruma kapalı. ||| ❌ Сохранение ролей выключено.
❌ Set ticket channel first with `/setup ticket`! ||| ❌ Önce `/setup ticket` ile ticket kanalını ayarla! ||| ❌ Сначала задай канал тикетов командой `/setup ticket`!
❌ Something went wrong. The bot owner has been notified. ||| ❌ Bir şeyler ters gitti. Bot sahibine bildirildi. ||| ❌ Что-то пошло не так. Владелец бота уведомлён.
❌ That message has no reaction roles! ||| ❌ Bu mesajda tepki rolü yok! ||| ❌ У этого сообщения нет ролей по реакции!
❌ That role cannot be sold: it is bot-managed, above my top role or has moderation permissions! ||| ❌ Bu rol satılamaz: bot tarafından yönetiliyor, benim en yüksek rolümün üstünde veya moderasyon yetkileri var! ||| ❌ Эту роль нельзя продавать: она управляется ботом, выше моей высшей роли или имеет права модерации!
❌ The level must be between 1 and 1000! ||| ❌ Seviye 1 ile 1000 arasında olmalı! ||| ❌ Уровень должен быть от 1 до 1000!
❌ The maximum timeout is 28 days! ||| ❌ En uzun zaman aşımı 28 gündür! ||| ❌ Максимальный тайм-аут — 28 дней!
❌ The price must be between 1 and 1,000,000,000! ||| ❌ Fiyat 1 ile 1.000.000.000 arasında olmalı! ||| ❌ Цена должна быть от 1 до 1 000 000 000!
❌ The store is full (maximum 24 items)! ||| ❌ Market dolu (en fazla 24 eşya)! ||| ❌ Магазин заполнен (максимум 24 предмета)!
❌ This giveaway has ended! ||| ❌ Bu çekiliş sona erdi! ||| ❌ Этот розыгрыш завершён!
❌ This is not your game! ||| ❌ Bu senin oyunun değil! ||| ❌ Это не твоя игра!
❌ This item's role can no longer be given (permissions or hierarchy changed). Ask an admin. ||| ❌ Bu eşyanın rolü artık verilemiyor (yetkiler veya hiyerarşi değişti). Bir yöneticiye sor. ||| ❌ Роль этого предмета больше нельзя выдать (права или иерархия изменились). Обратись к админу.
❌ This member is not muted! ||| ❌ Bu üye susturulmamış! ||| ❌ Этот участник не в муте!
❌ Ticket channel not found! ||| ❌ Ticket kanalı bulunamadı! ||| ❌ Канал тикетов не найден!
❌ Usage: `{}` ||| ❌ Kullanım: `{}` ||| ❌ Использование: `{}`
❌ Use bot commands in {}! ||| ❌ Bot komutlarını {} kanalında kullan! ||| ❌ Используй команды бота в {}!
❌ You already have a blackjack game running! ||| ❌ Zaten devam eden bir blackjack oyunun var! ||| ❌ У тебя уже идёт игра в блэкджек!
❌ You already have {} open ticket(s)! ||| ❌ Zaten {} açık ticketın var! ||| ❌ У тебя уже открыто тикетов: {}!
❌ You can only double on your first move and with enough money! ||| ❌ Sadece ilk hamlede ve yeterli paran varsa double yapabilirsin! ||| ❌ Удвоить можно только первым ходом и при достаточной сумме!
❌ You cannot close this ticket! ||| ❌ Bu ticketı kapatamazsın! ||| ❌ Ты не можешь закрыть этот тикет!
❌ You cannot manage a role that is higher than or equal to your top role! ||| ❌ Senin en yüksek rolünle aynı veya daha yüksek bir rolü yönetemezsin! ||| ❌ Нельзя управлять ролью, которая не ниже твоей высшей роли!
❌ You don't have `{}`! ||| ❌ `{}` eşyan yok! ||| ❌ У тебя нет `{}`!
❌ You don't have `{}`! Check your inventory. ||| ❌ `{}` eşyan yok! Envanterine bak. ||| ❌ У тебя нет `{}`! Проверь инвентарь.
❌ You need **${:,}** but only have **${:,}**! ||| ❌ **${:,}** gerekiyor ama sadece **${:,}** paran var! ||| ❌ Нужно **${:,}**, а у тебя только **${:,}**!
❌ You need the Mention Everyone permission to ping! ||| ❌ Etiketlemek için Herkesi Etiketle yetkisine ihtiyacın var! ||| ❌ Для упоминания нужно право «Упоминать всех»!
❌ `.slots <bet>` — Wallet: ${:,} ||| ❌ `.slots <bahis>` — Cüzdan: ${:,} ||| ❌ `.slots <ставка>` — Кошелёк: ${:,}
❌ {} The next number is **{}**! ||| ❌ {} Sıradaki sayı **{}**! ||| ❌ {} Следующее число — **{}**!
➕ Channel Created ||| ➕ Kanal Oluşturuldu ||| ➕ Канал создан
➖ Channel Deleted ||| ➖ Kanal Silindi ||| ➖ Канал удалён
🃏 Blackjack ||| 🃏 Blackjack ||| 🃏 Блэкджек
🆔 ID ||| 🆔 ID ||| 🆔 ID
🌐 Language ||| 🌐 Dil ||| 🌐 Язык
🍯 **{}** (`{}`) was banned for posting here. Their recent messages were deleted. ||| 🍯 **{}** (`{}`) buraya yazdığı için banlandı. Son mesajları silindi. ||| 🍯 **{}** (`{}`) забанен за сообщение здесь. Его недавние сообщения удалены.
🍯 HONEYPOT - DO NOT WRITE HERE ||| 🍯 HONEYPOT - BURAYA YAZMA ||| 🍯 ЛОВУШКА - НЕ ПИШИ СЮДА
🍯 Honeypot ||| 🍯 Honeypot ||| 🍯 Ловушка
🍯 You were banned from **{}** because you sent a message in a honeypot channel (used to catch spam bots and hacked accounts). If your account was hacked, secure it and contact the server staff. ||| 🍯 **{}** sunucusundan banlandın çünkü bir honeypot kanalına mesaj gönderdin (spam botlarını ve çalınmış hesapları yakalamak için kullanılır). Hesabın çalındıysa güvene al ve sunucu yetkilileriyle iletişime geç. ||| 🍯 Тебя забанили на **{}**, потому что ты написал в канал-ловушку (им ловят спам-ботов и взломанные аккаунты). Если твой аккаунт взломали, защити его и свяжись с администрацией сервера.
🎉 **{}** — No participants! ||| 🎉 **{}** — Katılımcı yok! ||| 🎉 **{}** — Нет участников!
🎉 Blackjack! You won **${:,}**! ||| 🎉 Blackjack! **${:,}** kazandın! ||| 🎉 Блэкджек! Ты выиграл **${:,}**!
🎉 Congrats {}! You won **{}**! ||| 🎉 Tebrikler {}! **{}** kazandın! ||| 🎉 Поздравляем, {}! Ты выиграл **{}**!
🎉 ENDED: {} ||| 🎉 SONA ERDİ: {} ||| 🎉 ЗАВЕРШЁН: {}
🎉 GIVEAWAY: {} ||| 🎉 ÇEKİLİŞ: {} ||| 🎉 РОЗЫГРЫШ: {}
🎒 {}'s Inventory ||| 🎒 {} kullanıcısının Envanteri ||| 🎒 Инвентарь {}
🎫 Ticket #{:04d} opened by {} — {} {} ||| 🎫 Ticket #{:04d} {} tarafından açıldı — {} {} ||| 🎫 Тикет #{:04d} открыт {} — {} {}
🎭 Reaction Roles ||| 🎭 Tepki Rolleri ||| 🎭 Роли по реакции
🎭 Role Created ||| 🎭 Rol Oluşturuldu ||| 🎭 Роль создана
🎭 Roles ||| 🎭 Roller ||| 🎭 Роли
🎭 Roles ({}) ||| 🎭 Roller ({}) ||| 🎭 Роли ({})
🎭 Roles Updated ||| 🎭 Roller Güncellendi ||| 🎭 Роли обновлены
🎰 {}\n\n✅ Two of a kind! +${:,} ||| 🎰 {}\n\n✅ İkili eşleşme! +${:,} ||| 🎰 {}\n\n✅ Две одинаковые! +${:,}
🎰 {}\n\n❌ No match. -${:,} ||| 🎰 {}\n\n❌ Eşleşme yok. -${:,} ||| 🎰 {}\n\n❌ Нет совпадений. -${:,}
🎰 {}\n\n🎉 **JACKPOT! +${:,}** (x{}) ||| 🎰 {}\n\n🎉 **JACKPOT! +${:,}** (x{}) ||| 🎰 {}\n\n🎉 **ДЖЕКПОТ! +${:,}** (x{})
🏓 **Pong!** `{}ms` ||| 🏓 **Pong!** `{}ms` ||| 🏓 **Pong!** `{}ms`
🏠 Server Updated ||| 🏠 Sunucu Güncellendi ||| 🏠 Сервер обновлён
🏦 Bank ||| 🏦 Banka ||| 🏦 Банк
🏳️ Flag Leaderboard ||| 🏳️ Bayrak Sıralaması ||| 🏳️ Таблица флагов
🏳️ Guess the Flag! ||| 🏳️ Bayrağı Tahmin Et! ||| 🏳️ Угадай флаг!
👑 Owner ||| 👑 Sahip ||| 👑 Владелец
👝 Wallet ||| 👝 Cüzdan ||| 👝 Кошелёк
👢 **{}** kicked!\nReason: {} ||| 👢 **{}** atıldı!\nSebep: {} ||| 👢 **{}** выгнан!\nПричина: {}
👤 Member ||| 👤 Üye ||| 👤 Участник
👤 Target ||| 👤 Hedef ||| 👤 Цель
👥 Members ||| 👥 Üyeler ||| 👥 Участники
💬 Channels ||| 💬 Kanallar ||| 💬 Каналы
💰 Economy Leaderboard ||| 💰 Ekonomi Sıralaması ||| 💰 Таблица экономики
💵 Total ||| 💵 Toplam ||| 💵 Всего
💸 **{}** → **{}**: **${:,}**\n*(10% tax: ${:,})* ||| 💸 **{}** → **{}**: **${:,}**\n*(%10 vergi: ${:,})* ||| 💸 **{}** → **{}**: **${:,}**\n*(налог 10%: ${:,})*
📅 Account Created ||| 📅 Hesap Oluşturulma ||| 📅 Аккаунт создан
📅 Created ||| 📅 Oluşturulma ||| 📅 Создан
📅 Date ||| 📅 Tarih ||| 📅 Дата
📅 Server Joined ||| 📅 Sunucuya Katılma ||| 📅 Вступил на сервер
📊 XP Leaderboard ||| 📊 XP Sıralaması ||| 📊 Таблица XP
📋 There are no reaction roles yet! ||| 📋 Henüz tepki rolü yok! ||| 📋 Ролей по реакции пока нет!
📋 {}'s History ||| 📋 {} kullanıcısının Geçmişi ||| 📋 История {}
📖 Versa Bot ||| 📖 Versa Bot ||| 📖 Versa Bot
📛 Nickname ||| 📛 Takma Ad ||| 📛 Ник
📝 Reason ||| 📝 Sebep ||| 📝 Причина
📤 Member Left ||| 📤 Üye Ayrıldı ||| 📤 Участник вышел
📥 Member Joined ||| 📥 Üye Katıldı ||| 📥 Участник присоединился
🔄 **{}** was reset! ||| 🔄 **{}** sıfırlandı! ||| 🔄 **{}** сброшено!
🔄 **{}** was softbanned! Their recent messages were deleted. ||| 🔄 **{}** softban yedi! Son mesajları silindi. ||| 🔄 **{}** получил софтбан! Его недавние сообщения удалены.
🔇 Muted — {} ||| 🔇 Susturuldu — {} ||| 🔇 Мут — {}
🔊 **{}** has been unmuted! ||| 🔊 **{}** susturması kaldırıldı! ||| 🔊 С **{}** снят мут!
🔒 All channels locked by {} ||| 🔒 Tüm kanallar {} tarafından kilitlendi ||| 🔒 Все каналы заблокированы: {}
🔒 Channel Locked ||| 🔒 Kanal Kilitlendi ||| 🔒 Канал заблокирован
🔒 Closing ticket... ||| 🔒 Ticket kapatılıyor... ||| 🔒 Закрываю тикет...
🔒 Locked **{}** channels. Failed: **{}**. ||| 🔒 **{}** kanal kilitlendi. Başarısız: **{}**. ||| 🔒 Заблокировано каналов: **{}**. Не удалось: **{}**.
🔒 Locking all text channels... ||| 🔒 Tüm yazı kanalları kilitleniyor... ||| 🔒 Блокирую все текстовые каналы...
🔒 Which roles may still write in this channel?\nMention up to 3 roles (for example @Moderator) or type `no` for nobody. ||| 🔒 Bu kanalda hangi roller yazmaya devam edebilsin?\nEn fazla 3 rol etiketle (örneğin @Moderatör) ya da kimse için `no` yaz. ||| 🔒 Какие роли смогут писать в этом канале?\nУпомяни до 3 ролей (например, @Модератор) или напиши `no`, если никто.
🔒 Your ticket in **{}** was closed by **{}**. ||| 🔒 **{}** sunucusundaki ticketın **{}** tarafından kapatıldı. ||| 🔒 Твой тикет на **{}** закрыт пользователем **{}**.
🔒 {} locked by {} ||| 🔒 {} kanalı {} tarafından kilitlendi ||| 🔒 {} заблокирован: {}
🔓 All channels unlocked by {} ||| 🔓 Tüm kanalların kilidi {} tarafından açıldı ||| 🔓 Все каналы разблокированы: {}
🔓 Member Unbanned ||| 🔓 Üyenin Banı Kaldırıldı ||| 🔓 Участник разбанен
🔓 Unlocked **{}** channels. Failed: **{}**. ||| 🔓 **{}** kanalın kilidi açıldı. Başarısız: **{}**. ||| 🔓 Разблокировано каналов: **{}**. Не удалось: **{}**.
🔓 Unlocking channels... ||| 🔓 Kanalların kilidi açılıyor... ||| 🔓 Разблокирую каналы...
🔓 {} unlocked by {} ||| 🔓 {} kanalının kilidi {} tarafından açıldı ||| 🔓 {} разблокирован: {}
🔓 {} unlocked! ||| 🔓 {} kilidi açıldı! ||| 🔓 {} разблокирован!
🔢 Counting Channel ||| 🔢 Sayı Sayma Kanalı ||| 🔢 Канал для счёта
🔨 Banned — {} ||| 🔨 Banlandı — {} ||| 🔨 Бан — {}
🔨 Member Banned ||| 🔨 Üye Banlandı ||| 🔨 Участник забанен
🗑️ Deleted **{}** messages! ||| 🗑️ **{}** mesaj silindi! ||| 🗑️ Удалено сообщений: **{}**!
🗑️ Message Deleted ||| 🗑️ Mesaj Silindi ||| 🗑️ Сообщение удалено
🗑️ Messages Purged ||| 🗑️ Mesajlar Toplu Silindi ||| 🗑️ Массовое удаление
🗑️ Role Deleted ||| 🗑️ Rol Silindi ||| 🗑️ Роль удалена
🛒 The store is empty! ||| 🛒 Market boş! ||| 🛒 Магазин пуст!
🛒 {} Store ||| 🛒 {} Marketi ||| 🛒 Магазин {}
🛡️ Mod ||| 🛡️ Yetkili ||| 🛡️ Модератор
🤖 Bot ||| 🤖 Bot ||| 🤖 Бот
🤝 Push! Your bet was returned. ||| 🤝 Berabere! Bahsin iade edildi. ||| 🤝 Ничья! Ставка возвращена.
🪙 **{}**!\n✅ You won **+${:,}**! ||| 🪙 **{}**!\n✅ **+${:,}** kazandın! ||| 🪙 **{}**!\n✅ Ты выиграл **+${:,}**!
🪙 **{}**!\n❌ You lost **-${:,}**! ||| 🪙 **{}**!\n❌ **-${:,}** kaybettin! ||| 🪙 **{}**!\n❌ Ты потерял **-${:,}**!
⏳ You are using commands too fast. Please slow down! ||| ⏳ Komutları çok hızlı kullanıyorsun. Lütfen yavaşla! ||| ⏳ Ты используешь команды слишком быстро. Пожалуйста, помедленнее!
⚠️ {} log entries were skipped to stay inside Discord's rate limits. ||| ⚠️ Discord'un hız sınırlarında kalmak için {} log kaydı atlandı. ||| ⚠️ Чтобы не превышать лимиты Discord, пропущено записей лога: {}.
{} second(s) ||| {} saniye ||| {} сек.
{} minute(s) ||| {} dakika ||| {} мин.
{} hour(s) ||| {} saat ||| {} ч.
{} day(s) ||| {} gün ||| {} дн.
{} week(s) ||| {} hafta ||| {} нед.
🔒 Close Ticket ||| 🔒 Ticketı Kapat ||| 🔒 Закрыть тикет
🎉 Enter ||| 🎉 Katıl ||| 🎉 Участвовать
📋 Log ||| 📋 Log ||| 📋 Лог
🎫 Ticket ||| 🎫 Ticket ||| 🎫 Тикеты
👋 Welcome ||| 👋 Karşılama ||| 👋 Приветствие
📊 Level-Up ||| 📊 Seviye Atlama ||| 📊 Повышение уровня
🎰 Casino ||| 🎰 Casino ||| 🎰 Казино
🤖 Bot Commands ||| 🤖 Bot Komutları ||| 🤖 Команды бота
🔢 Counting ||| 🔢 Sayı Sayma ||| 🔢 Счёт
🎭 Ticket Staff ||| 🎭 Ticket Yetkilisi ||| 🎭 Персонал тикетов
👋 Welcome Role ||| 👋 Karşılama Rolü ||| 👋 Приветственная роль
🔇 Muted Role ||| 🔇 Susturma Rolü ||| 🔇 Роль мута
♻️ Role Persist ||| ♻️ Rol Koruma ||| ♻️ Сохранение ролей
⌨️ Prefix ||| ⌨️ Önek ||| ⌨️ Префикс
📊 XP Difficulty ||| 📊 XP Zorluğu ||| 📊 Сложность XP
💰 Economy ||| 💰 Ekonomi ||| 💰 Экономика
🛒 Economy Store ||| 🛒 Ekonomi Marketi ||| 🛒 Магазин
📊 Leveling ||| 📊 Seviye Sistemi ||| 📊 Уровни
🎫 Tickets ||| 🎫 Ticketlar ||| 🎫 Тикеты
🎉 Giveaway ||| 🎉 Çekiliş ||| 🎉 Розыгрыши
🏳️ Flag Game ||| 🏳️ Bayrak Oyunu ||| 🏳️ Игра с флагами
📋 Poll ||| 📋 Anket ||| 📋 Опросы
🛡️ Moderation ||| 🛡️ Moderasyon ||| 🛡️ Модерация
🟢 Easiest ||| 🟢 En Kolay ||| 🟢 Самый лёгкий
🟢 Very Easy ||| 🟢 Çok Kolay ||| 🟢 Очень лёгкий
🔵 Easy ||| 🔵 Kolay ||| 🔵 Лёгкий
⚪ Normal ||| ⚪ Normal ||| ⚪ Обычный
🟠 Hard ||| 🟠 Zor ||| 🟠 Сложный
🔴 Very Hard ||| 🔴 Çok Zor ||| 🔴 Очень сложный
💀 Hardest ||| 💀 En Zor ||| 💀 Самый сложный
Buttons shown on the panel ||| Panelde gösterilen butonlar ||| Кнопки на панели
Choose which buttons the panel shows, add your own, then press **Send panel**.\nPanel channel: {} ||| Panelde hangi butonların görüneceğini seç, kendi butonunu ekle, sonra **Paneli gönder**'e bas.\nPanel kanalı: {} ||| Выбери, какие кнопки показывать на панели, добавь свои, затем нажми **Отправить панель**.\nКанал панели: {}
Close poll ||| Anketi kapat ||| Закрыть опрос
Created by ||| Oluşturan ||| Создал
Panel preview ||| Panel önizlemesi ||| Предпросмотр панели
Play: .slots <bet> · Wallet: ${:,} ||| Oyna: .slots <bahis> · Cüzdan: ${:,} ||| Играть: .slots <ставка> · Кошелёк: ${:,}
Three of a kind pays the big number, two of a kind the small one. 🍀 pays nothing. ||| Üç aynı sembol büyük çarpanı, iki aynı sembol küçük çarpanı öder. 🍀 hiçbir şey ödemez. ||| Три одинаковых платят большой множитель, две одинаковых — малый. 🍀 ничего не платит.
{} votes ||| {} oy ||| Голосов: {}
{}m {}s ||| {} dk {} sn ||| {} мин {} с
{}s ||| {} sn ||| {} с
↩️ Your vote was removed. ||| ↩️ Oyun geri alındı. ||| ↩️ Твой голос убран.
⏳ You can rob again in **{}**! ||| ⏳ Tekrar soyabilmek için **{}** beklemelisin! ||| ⏳ Грабить снова можно через **{}**!
✅ You voted for **{}**! ||| ✅ **{}** için oy verdin! ||| ✅ Ты проголосовал за **{}**!
❌ A panel can have at most 10 buttons! ||| ❌ Bir panelde en fazla 10 buton olabilir! ||| ❌ На панели может быть не более 10 кнопок!
❌ A poll needs at least 2 options! ||| ❌ Bir ankette en az 2 seçenek olmalı! ||| ❌ В опросе должно быть минимум 2 варианта!
❌ Only server admins can close polls! ||| ❌ Anketleri yalnızca sunucu yöneticileri kapatabilir! ||| ❌ Закрывать опросы могут только админы сервера!
❌ Pick at least one button! ||| ❌ En az bir buton seç! ||| ❌ Выбери хотя бы одну кнопку!
❌ Poll data not found! ||| ❌ Anket verisi bulunamadı! ||| ❌ Данные опроса не найдены!
❌ This poll is closed! ||| ❌ Bu anket kapalı! ||| ❌ Этот опрос закрыт!
❌ You can't rob a bot! ||| ❌ Bir botu soyamazsın! ||| ❌ Нельзя ограбить бота!
❌ {} Wait for someone else to count! ||| ❌ {} Başka birinin saymasını bekle! ||| ❌ {} Подожди, пока посчитает кто-то другой!
🎫 Ticket Panel Editor ||| 🎫 Ticket Paneli Düzenleyici ||| 🎫 Редактор панели тикетов
🎰 Slots Paytable ||| 🎰 Slot Ödeme Tablosu ||| 🎰 Таблица выплат слотов
🎰 {}\n\n✅ Two {}! x{:g} → **${:,}** ||| 🎰 {}\n\n✅ İki {}! x{:g} → **${:,}** ||| 🎰 {}\n\n✅ Два {}! x{:g} → **${:,}**
🎰 {}\n\n🎉 **Three {}!** x{:g} → **${:,}** ||| 🎰 {}\n\n🎉 **Üç {}!** x{:g} → **${:,}** ||| 🎰 {}\n\n🎉 **Три {}!** x{:g} → **${:,}**
🎰 {}\n\n💥 **JACKPOT!** x{:g} → **${:,}**! ||| 🎰 {}\n\n💥 **JACKPOT!** x{:g} → **${:,}**! ||| 🎰 {}\n\n💥 **ДЖЕКПОТ!** x{:g} → **${:,}**!
🎰 {}\n\n🤝 Two {}! Your bet is returned. ||| 🎰 {}\n\n🤝 İki {}! Bahsin iade edildi. ||| 🎰 {}\n\n🤝 Два {}! Ставка возвращена.
🔒 Closed · {} votes ||| 🔒 Kapandı · {} oy ||| 🔒 Закрыт · Голосов: {}
➕ Add button ||| ➕ Buton ekle ||| ➕ Добавить кнопку
📨 Send panel ||| 📨 Paneli gönder ||| 📨 Отправить панель
Cancel ||| İptal ||| Отмена
⛔ You are not allowed to use **{}** on this bot. ||| ⛔ Bu botta **{}** özelliğini kullanman yasaklandı. ||| ⛔ Тебе запрещено использовать **{}** в этом боте.
❌ This needs the **Manage Server** permission! ||| ❌ Bunun için **Sunucuyu Yönet** yetkisi gerekir! ||| ❌ Для этого нужно право **Управление сервером**!
❌ I need the Manage Channels and Manage Roles permissions first! ||| ❌ Önce bana Kanalları Yönet ve Rolleri Yönet yetkilerini ver! ||| ❌ Сначала дай мне права «Управление каналами» и «Управление ролями»!
⏳ Another mass lock/unlock is already running here! ||| ⏳ Burada başka bir toplu kilitleme/açma işlemi zaten sürüyor! ||| ⏳ Здесь уже выполняется другая массовая блокировка/разблокировка!
⏳ Working... {}/{} channels ||| ⏳ Çalışıyor... {}/{} kanal ||| ⏳ Работаю... {}/{} каналов
⏳ Working... ||| ⏳ Çalışıyor... ||| ⏳ Работаю...
🌑 Lockdown is on: hidden **{}** channels/categories. Failed: **{}**.\nUse `unlockdown` to restore everything. ||| 🌑 Lockdown açık: **{}** kanal/kategori gizlendi. Başarısız: **{}**.\nHer şeyi geri yüklemek için `unlockdown` kullan. ||| 🌑 Режим lockdown включён: скрыто каналов/категорий: **{}**. Ошибок: **{}**.\nЧтобы всё вернуть, используй `unlockdown`.
🌑 Lockdown started by {} ||| 🌑 Lockdown {} tarafından başlatıldı ||| 🌑 Lockdown запущен: {}
ℹ️ There is no active lockdown. ||| ℹ️ Aktif bir lockdown yok. ||| ℹ️ Активного lockdown нет.
ℹ️ No locked channels found. ||| ℹ️ Kilitli kanal bulunamadı. ||| ℹ️ Заблокированных каналов не найдено.
🌤️ Lockdown lifted: restored **{}** channels/categories. Failed: **{}**. ||| 🌤️ Lockdown kaldırıldı: **{}** kanal/kategori geri yüklendi. Başarısız: **{}**. ||| 🌤️ Lockdown снят: восстановлено каналов/категорий: **{}**. Ошибок: **{}**.
🌤️ Lockdown lifted by {} ||| 🌤️ Lockdown {} tarafından kaldırıldı ||| 🌤️ Lockdown снят: {}
🔒 Lock ALL channels ||| 🔒 TÜM kanalları kilitle ||| 🔒 Заблокировать ВСЕ каналы
Nobody can write in any text channel.\nPick the roles that may still write (optional), then press **Start**.\nYou keep your own access. `unlockall` restores every channel exactly as it was. ||| Hiçbir metin kanalında kimse yazamaz.\nHâlâ yazabilecek rolleri seç (isteğe bağlı), sonra **Başlat**'a bas.\nKendi erişimin korunur. `unlockall` her kanalı tam eskisi gibi geri yükler. ||| Никто не сможет писать ни в одном текстовом канале.\nВыбери роли, которые смогут писать (необязательно), затем нажми **Старт**.\nТвой доступ сохранится. `unlockall` вернёт каналы точно как было.
🌑 LOCKDOWN ||| 🌑 LOCKDOWN ||| 🌑 LOCKDOWN
Every channel and category is hidden from everyone.\nPick the roles that may still **see** (read-only) and the roles that may see **and write** - both optional - then press **Start**.\nNobody gains access they did not have before. You keep your own access. `unlockdown` restores everything exactly as it was. ||| Her kanal ve kategori herkesten gizlenir.\nHâlâ **görebilecek** (salt okunur) rolleri ve hem **görüp yazabilecek** rolleri seç - ikisi de isteğe bağlı - sonra **Başlat**'a bas.\nHiç kimse daha önce sahip olmadığı erişimi kazanmaz. Kendi erişimin korunur. `unlockdown` her şeyi tam eskisi gibi geri yükler. ||| Каждый канал и категория скрываются от всех.\nВыбери роли, которые смогут **видеть** (только чтение), и роли, которые смогут **видеть и писать** - оба списка необязательны - затем нажми **Старт**.\nНикто не получит доступ, которого не имел раньше. Твой доступ сохранится. `unlockdown` вернёт всё точно как было.
Roles that can still SEE and WRITE (optional) ||| Hâlâ GÖRÜP YAZABİLECEK roller (isteğe bağlı) ||| Роли, которые смогут ВИДЕТЬ и ПИСАТЬ (необязательно)
Roles that can still WRITE (optional) ||| Hâlâ YAZABİLECEK roller (isteğe bağlı) ||| Роли, которые смогут ПИСАТЬ (необязательно)
Roles that can still SEE (read-only, optional) ||| Hâlâ GÖREBİLECEK roller (salt okunur, isteğe bağlı) ||| Роли, которые смогут ВИДЕТЬ (только чтение, необязательно)
✅ Start ||| ✅ Başlat ||| ✅ Старт
🚫 Cancelled. ||| 🚫 İptal edildi. ||| 🚫 Отменено.
💤 AFK ||| 💤 AFK ||| 💤 AFK
📬 Modmail ||| 📬 Modmail ||| 📬 Модмейл
⚠️ Lift **{}** first - it was started after this one. ||| ⚠️ Önce **{}** işlemini geri al - bu işlemden sonra başlatıldı. ||| ⚠️ Сначала отмени **{}** - он был запущен позже.
...and {} more ||| ...ve {} tane daha ||| ...и ещё {}
No voice channels chosen yet - nobody earns voice XP. ||| Henüz ses kanalı seçilmedi - kimse ses XP'si kazanamaz. ||| Голосовые каналы пока не выбраны - никто не получает голосовой XP.
None yet - an admin must use /setup vc ||| Henüz yok - bir yönetici /setup vc kullanmalı ||| Пока нет - администратор должен использовать /setup vc
Set an Inactive channel in Server Settings: Discord moves idle members there and nobody earns XP in it. ||| Sunucu Ayarları'nda bir AFK kanalı belirle: Discord boşta kalan üyeleri oraya taşır ve orada kimse XP kazanmaz. ||| Укажи канал AFK в настройках сервера: Discord переносит туда неактивных, и в нём никто не получает XP.
Versa never joins voice channels and never hears or records anything. It only reads what Discord tells every bot: which channel you are in and whether your mic or headphones are off. The only thing it stores is your voice XP total of today (for the daily limit). ||| Versa ses kanallarına asla katılmaz, hiçbir şeyi duymaz ve kaydetmez. Yalnızca Discord'un her bota bildirdiği bilgiyi okur: hangi kanalda olduğunu ve mikrofonunun ya da kulaklığının kapalı olup olmadığını. Sakladığı tek şey bugünkü ses XP toplamındır (günlük sınır için). ||| Versa никогда не заходит в голосовые каналы и ничего не слышит и не записывает. Он читает только то, что Discord сообщает любому боту: в каком ты канале и выключены ли твои микрофон или наушники. Единственное, что хранится, - твой голосовой XP за сегодня (для дневного лимита).
You earn XP while you are in a chosen voice channel with your **microphone and headphones on**, and at least **2 people in total** (you included) have theirs on.\nNo XP while you are muted or deafened (by yourself or a moderator), in the AFK channel, timed out, set to `.afk`, or only listening in a stage.\nTime is counted to the second. The limit is **{}** hours of voice XP per day. ||| Seçili bir ses kanalındayken **mikrofonun ve kulaklığın açıksa** ve (sen dahil) toplam en az **2 kişinin** mikrofonu ve kulaklığı açıksa XP kazanırsın.\nSessize alınmışsan veya sağırlaştırılmışsan (kendin ya da bir yetkili tarafından), AFK kanalındaysan, zaman aşımındaysan, `.afk` durumundaysan ya da sahnede sadece dinleyiciysen XP kazanmazsın.\nSüre saniyesine kadar sayılır. Günlük sınır: **{}** saatlik ses XP'si. ||| Ты получаешь XP, пока находишься в выбранном голосовом канале с **включёнными микрофоном и наушниками** и как минимум **2 человека** (включая тебя) тоже их включили.\nXP не начисляется, если ты заглушён или оглушён (сам или модератором), находишься в канале AFK, в тайм-ауте, со статусом `.afk` или просто слушаешь на сцене.\nВремя считается с точностью до секунды. Лимит: **{}** ч. голосового XP в день.
{}\n{} XP per minute, up to {} XP a day ||| {}\nDakikada {} XP, günde en fazla {} XP ||| {}\n{} XP в минуту, до {} XP в день
⚠️ Voice XP is not active yet: switch on **Voice XP** (and Leveling) with /setup feature. ||| ⚠️ Ses XP henüz aktif değil: /setup feature ile **Ses XP**'yi (ve Seviye sistemini) aç. ||| ⚠️ Голосовой XP пока не активен: включи **Голосовой XP** (и Уровни) через /setup feature.
✅ Added {} channels. ||| ✅ {} kanal eklendi. ||| ✅ Добавлено каналов: {}.
✅ Removed {} channels. ||| ✅ {} kanal kaldırıldı. ||| ✅ Убрано каналов: {}.
✅ Voice XP difficulty: **{}**\nXP per minute: **{}**, daily limit: **{}** XP ({} hours) ||| ✅ Ses XP zorluğu: **{}**\nDakika başına XP: **{}**, günlük sınır: **{}** XP ({} saat) ||| ✅ Сложность голосового XP: **{}**\nXP в минуту: **{}**, дневной лимит: **{}** XP ({} ч.)
➕ Add voice channels... ||| ➕ Ses kanalı ekle... ||| ➕ Добавить голосовые каналы...
➕ All voice channels ||| ➕ Tüm ses kanalları ||| ➕ Все голосовые каналы
➖ Remove channels... ||| ➖ Kanal kaldır... ||| ➖ Убрать каналы...
➡️ Next: choose the voice channels with `/setup vc` (Voice XP gives nothing until you do). ||| ➡️ Sıradaki adım: `/setup vc` ile ses kanallarını seç (sen seçmeden Ses XP hiçbir şey vermez). ||| ➡️ Дальше: выбери голосовые каналы через `/setup vc` (пока не выберешь, голосовой XP не начисляется).
🎙️ Voice XP ||| 🎙️ Ses XP ||| 🎙️ Голосовой XP
🎙️ Voice XP Channels ||| 🎙️ Ses XP Kanalları ||| 🎙️ Каналы голосового XP
🎙️ Voice XP Difficulty ||| 🎙️ Ses XP Zorluğu ||| 🎙️ Сложность голосового XP
💡 Tip ||| 💡 İpucu ||| 💡 Совет
📅 Your voice XP today ||| 📅 Bugünkü ses XP'n ||| 📅 Твой голосовой XP сегодня
📌 Status ||| 📌 Durum ||| 📌 Статус
🔒 Privacy ||| 🔒 Gizlilik ||| 🔒 Конфиденциальность
🗑️ Clear list ||| 🗑️ Listeyi temizle ||| 🗑️ Очистить список
**Prefix commands** ||| **Önek komutları** ||| **Команды с префиксом**
**Slash commands** ||| **Slash komutları** ||| **Слэш-команды**
Messages counted since {} · days change at 00:00 UTC ||| Mesajlar {} tarihinden beri sayılıyor · gün 00:00 UTC'de değişir ||| Сообщения считаются с {} · день меняется в 00:00 UTC
Sent by Versa for the server's staff (anonymous). Stop these DMs: /dms off ||| Versa tarafından sunucu yetkilileri adına gönderildi (anonim). Bu DM'leri durdur: /dms off ||| Отправлено Versa от имени модераторов сервера (анонимно). Отключить такие сообщения: /dms off
⏳ Slow down! Try again in {}s. ||| ⏳ Yavaş! {} sn sonra tekrar dene. ||| ⏳ Не так быстро! Попробуй снова через {} с.
⛔ DMs from Versa are **off**. You will no longer get moderation notices or ticket updates by DM. ||| ⛔ Versa'dan gelen DM'ler **kapalı**. Artık moderasyon bildirimlerini ve ticket güncellemelerini DM ile almayacaksın. ||| ⛔ Личные сообщения от Versa **выключены**. Ты больше не будешь получать уведомления о модерации и обновления тикетов в личку.
✅ DMs from Versa are **on**. ||| ✅ Versa'dan gelen DM'ler **açık**. ||| ✅ Личные сообщения от Versa **включены**.
❌ I need the **{}** permission first. ||| ❌ Önce bana **{}** yetkisi vermelisin. ||| ❌ Сначала дай мне право **{}**.
❌ This command only works in servers. ||| ❌ Bu komut yalnızca sunucularda çalışır. ||| ❌ Эта команда работает только на серверах.
❌ You need the **{}** permission to use this command. ||| ❌ Bu komutu kullanmak için **{}** yetkisine ihtiyacın var. ||| ❌ Для этой команды нужно право **{}**.
👋 I am **Versa**! My prefix here is `{}` - type `{}help` or `/help` to see everything I can do.\nSupport: {} ||| 👋 Ben **Versa**! Buradaki önekim `{}` - yapabildiğim her şeyi görmek için `{}help` veya `/help` yaz.\nDestek: {} ||| 👋 Я **Versa**! Мой префикс здесь: `{}` - напиши `{}help` или `/help`, чтобы увидеть все мои команды.\nПоддержка: {}
💬 Messages ||| 💬 Mesajlar ||| 💬 Сообщения
📅 Today: **{}**\n🗓️ Last 7 days: **{}**\n📆 Last 30 days: **{}**\n💬 Total: **{}** ||| 📅 Bugün: **{}**\n🗓️ Son 7 gün: **{}**\n📆 Son 30 gün: **{}**\n💬 Toplam: **{}** ||| 📅 Сегодня: **{}**\n🗓️ За 7 дней: **{}**\n📆 За 30 дней: **{}**\n💬 Всего: **{}**
📋 All commands ||| 📋 Tüm komutlar ||| 📋 Все команды
📬 DMs from Versa: {}\nChange it with `/dms` or `{}dms on` / `{}dms off`. ||| 📬 Versa DM'leri: {}\n`/dms` veya `{}dms on` / `{}dms off` ile değiştir. ||| 📬 Личные сообщения от Versa: {}\nИзменить: `/dms` или `{}dms on` / `{}dms off`.
**Color changed** ||| **Renk değişti** ||| **Цвет изменён**
**Hoisted:** {} → {} ||| **Ayrı gösterim:** {} → {} ||| **Отдельно в списке:** {} → {}
**Mentionable:** {} → {} ||| **Etiketlenebilir:** {} → {} ||| **Можно упоминать:** {} → {}
**NSFW:** {} → {} ||| **NSFW:** {} → {} ||| **NSFW:** {} → {}
**Name:** {} → {} ||| **Ad:** {} → {} ||| **Название:** {} → {}
**Permissions changed** ||| **İzinler değişti** ||| **Права изменены**
**Slowmode:** {}s → {}s ||| **Yavaş mod:** {}sn → {}sn ||| **Медленный режим:** {}с → {}с
**Topic changed** ||| **Konu değişti** ||| **Тема изменена**
Added ||| Eklendi ||| Добавлено
Bulk delete ||| Toplu silme ||| Массовое удаление
Channel created ||| Kanal oluşturuldu ||| Канал создан
Channel deleted ||| Kanal silindi ||| Канал удалён
Channel edited ||| Kanal düzenlendi ||| Канал изменён
Choose a category ||| Bir kategori seç ||| Выбери категорию
Click a button to turn that log on or off. ||| Bir düğmeye tıklayarak o logu aç veya kapat. ||| Нажми на кнопку, чтобы включить или выключить этот лог.
Close ||| Kapat ||| Закрыть
Code ||| Kod ||| Код
Emoji changes ||| Emoji değişiklikleri ||| Изменения эмодзи
Enabled: **{}** / **{}** ||| Açık: **{}** / **{}** ||| Включено: **{}** из **{}**
Invite created ||| Davet oluşturuldu ||| Приглашение создано
Invite deleted ||| Davet silindi ||| Приглашение удалено
Joined voice ||| Sese katıldı ||| Вошёл в голос
Left voice ||| Sesten ayrıldı ||| Вышел из голоса
Log channel: {} ||| Log kanalı: {} ||| Канал логов: {}
Max uses ||| Maks. kullanım ||| Макс. использований
Member banned ||| Üye banlandı ||| Участник забанен
Member joined ||| Üye katıldı ||| Участник вошёл
Member left ||| Üye ayrıldı ||| Участник вышел
Member unbanned ||| Üyenin banı açıldı ||| Участник разбанен
Message deleted ||| Mesaj silindi ||| Сообщение удалено
Message edited ||| Mesaj düzenlendi ||| Сообщение изменено
Mod cases (warn, kick, mute...) ||| Mod kayıtları (warn, kick, mute...) ||| Кейсы модерации (warn, kick, mute...)
Moved voice ||| Ses kanalı değiştirdi ||| Сменил голосовой канал
Nickname changed ||| Takma ad değişti ||| Ник изменён
Parent ||| Üst kanal ||| Родитель
Removed ||| Kaldırıldı ||| Удалено
Renamed ||| Yeniden adlandırıldı ||| Переименовано
Role created ||| Rol oluşturuldu ||| Роль создана
Role deleted ||| Rol silindi ||| Роль удалена
Role edited ||| Rol düzenlendi ||| Роль изменена
Roles changed ||| Roller değişti ||| Роли изменены
Server boost ||| Sunucu boostu ||| Буст сервера
Server edited ||| Sunucu düzenlendi ||| Сервер изменён
Thread created ||| Alt konu oluşturuldu ||| Ветка создана
Thread deleted ||| Alt konu silindi ||| Ветка удалена
Timeout ||| Zaman aşımı ||| Тайм-аут
Until ||| Bitiş ||| До
{} joined {} ||| {} {} kanalına katıldı ||| {} зашёл в {}
{} left {} ||| {} {} kanalından ayrıldı ||| {} вышел из {}
{} moved from {} to {} ||| {} {} kanalından {} kanalına geçti ||| {} перешёл из {} в {}
{} started boosting the server ||| {} sunucuyu boostlamaya başladı ||| {} начал буст сервера
{} stopped boosting the server ||| {} sunucuyu boostlamayı bıraktı ||| {} перестал бустить сервер
ℹ️ {} can already see this ticket. ||| ℹ️ {} bu ticket'ı zaten görebiliyor. ||| ℹ️ {} уже видит этот тикет.
ℹ️ {} was not added to this ticket. ||| ℹ️ {} bu ticket'a eklenmemişti. ||| ℹ️ {} не был добавлен в этот тикет.
⏱️ Member Timed Out ||| ⏱️ Üye zaman aşımına alındı ||| ⏱️ Участник в тайм-ауте
⚠️ No log channel yet. Set one with `/setup log`. ||| ⚠️ Henüz log kanalı yok. `/setup log` ile ayarla. ||| ⚠️ Канал логов не задан. Укажи его через `/setup log`.
⚠️ That is not a valid emoji, so 🎫 is used. ||| ⚠️ Bu geçerli bir emoji değil, bu yüzden 🎫 kullanıldı. ||| ⚠️ Это не эмодзи, поэтому использован 🎫.
✅ Log settings saved. ||| ✅ Log ayarları kaydedildi. ||| ✅ Настройки логов сохранены.
✅ Timeout Removed ||| ✅ Zaman aşımı kaldırıldı ||| ✅ Тайм-аут снят
✏️ Channel Edited ||| ✏️ Kanal Düzenlendi ||| ✏️ Канал изменён
✓ All in category ||| ✓ Kategoride hepsi ||| ✓ Все в категории
✓ Everything ||| ✓ Hepsi ||| ✓ Всё
✕ None in category ||| ✕ Kategoride hiçbiri ||| ✕ Ничего в категории
✕ Nothing ||| ✕ Hiçbiri ||| ✕ Ничего
❌ Give the button a name! ||| ❌ Düğmeye bir ad ver! ||| ❌ Дай кнопке название!
❌ Only ticket staff can do this! ||| ❌ Bunu yalnızca ticket yetkilileri yapabilir! ||| ❌ Это могут делать только сотрудники тикетов!
❌ This is not a ticket channel! ||| ❌ Bu bir ticket kanalı değil! ||| ❌ Это не канал тикета!
❌ You cannot add a bot! ||| ❌ Bir bot ekleyemezsin! ||| ❌ Нельзя добавить бота!
❌ You cannot remove the ticket owner! ||| ❌ Ticket sahibini çıkaramazsın! ||| ❌ Нельзя убрать владельца тикета!
❌ You cannot remove the ticket staff role! ||| ❌ Ticket yetkili rolünü çıkaramazsın! ||| ❌ Нельзя убрать роль сотрудников тикетов!
➕ {} was added to this ticket by {}. ||| ➕ {} bu ticket'a {} tarafından eklendi. ||| ➕ {} добавлен в этот тикет: {}.
➖ {} was removed from this ticket by {}. ||| ➖ {} bu ticket'tan {} tarafından çıkarıldı. ||| ➖ {} убран из этого тикета: {}.
🎭 Role Edited ||| 🎭 Rol Düzenlendi ||| 🎭 Роль изменена
🏠 Server ||| 🏠 Sunucu ||| 🏠 Сервер
💜 Server Boost ||| 💜 Sunucu Boostu ||| 💜 Буст сервера
📜 Log settings ||| 📜 Log ayarları ||| 📜 Настройки логов
🔊 Voice ||| 🔊 Ses ||| 🔊 Голос
🔊 Voice Activity ||| 🔊 Ses Etkinliği ||| 🔊 Голосовая активность
🔗 Invite Created ||| 🔗 Davet Oluşturuldu ||| 🔗 Приглашение создано
🔗 Invite Deleted ||| 🔗 Davet Silindi ||| 🔗 Приглашение удалено
🔨 Moderation ||| 🔨 Moderasyon ||| 🔨 Модерация
🖼️ Emoji Changes ||| 🖼️ Emoji Değişiklikleri ||| 🖼️ Изменения эмодзи
🧩 Roles & channels ||| 🧩 Roller ve kanallar ||| 🧩 Роли и каналы
🧵 Thread Created ||| 🧵 Alt Konu Oluşturuldu ||| 🧵 Ветка создана
🧵 Thread Deleted ||| 🧵 Alt Konu Silindi ||| 🧵 Ветка удалена
📨 Moderation DMs ||| 📨 Moderasyon DM'leri ||| 📨 ЛС о модерации
'''
_load_phrases(_PHRASE_TABLE)

_silent_deletes = set()

async def silent_delete(message):
    """Delete a message on purpose without it appearing as a user deletion in the admin log."""
    if message is None:
        return False
    if len(_silent_deletes) > 5000:
        _silent_deletes.clear()
    _silent_deletes.add(message.id)
    try:
        await message.delete()
        return True
    except Exception:
        _silent_deletes.discard(message.id)
        return False





def next_case_s(s):
    """Next moderation case number for a settings dict."""
    n = s.get("case_counter", s.get("ticket_counter", 0)) + 1
    s["case_counter"] = n
    save_settings()
    return n

def _clean_name(text):
    return (text or "").strip().strip("\"'“”‘’").strip()

GENERAL_CMDS = {"balance", "daily", "work", "deposit", "withdraw", "rob", "pay", "elb", "blackjack", "slots",
                "coinflip", "rank", "leaderboard", "flag", "flag-leaderboard", "afk", "estore", "buy", "inv",
                "giveitem", "higherlower"}

_DANGEROUS_PERMS = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages",
                    "manage_nicknames", "kick_members", "ban_members", "moderate_members", "view_audit_log",
                    "manage_webhooks", "manage_threads", "mention_everyone", "mute_members", "deafen_members",
                    "move_members")

def role_is_dangerous(role):
    """True for roles with moderation-level permissions (never sold, auto-given or reaction-given)."""
    return any(getattr(role.permissions, name, False) for name in _DANGEROUS_PERMS)

def role_assignable(guild, role):
    return (role is not None and not role.managed and not role.is_default()
            and role < guild.me.top_role and not role_is_dangerous(role))

def emoji_key(e):
    return f"{e.name}:{e.id}" if getattr(e, "id", None) else str(e)

def emoji_from_key(key):
    if ":" in key and key.rsplit(":", 1)[1].isdigit():
        name, eid = key.rsplit(":", 1)
        return f"<:{name}:{eid}>"
    return key

def find_muted_role(guild):
    rid = get_settings(guild.id).get("mutedrole")
    if rid:
        role = guild.get_role(int(rid))
        if role:
            return role
    return discord.utils.get(guild.roles, name="Muted")

# ---------- persistent timers (temp-ban, timed mute, giveaways survive restarts) ----------
SCHEDULE_FILE = "schedule.json"
schedule_db = load_json(SCHEDULE_FILE)
if "tasks" not in schedule_db:
    schedule_db["tasks"] = []

def save_schedule():
    save_json(SCHEDULE_FILE, schedule_db)

def schedule_task(kind, guild_id, target, at_ts):
    schedule_db["tasks"].append({"type": kind, "guild": str(guild_id), "target": str(target), "at": float(at_ts)})
    save_schedule()

async def _run_task(task):
    guild = bot.get_guild(int(task["guild"]))
    if guild is None:
        return
    set_lang(guild.id)
    kind, target = task["type"], task["target"]
    if kind == "unban":
        try:
            await guild.unban(discord.Object(id=int(target)), reason="Temporary ban expired")
        except discord.NotFound:
            pass
    elif kind == "unmute":
        member, role = guild.get_member(int(target)), find_muted_role(guild)
        if member and role and role in member.roles:
            await member.remove_roles(role, reason="Mute expired")
    elif kind == "giveaway":
        await end_giveaway(guild, str(guild.id), target)
    elif kind == "poll":
        ch_id, _, msg_id = target.partition(":")
        poll = polls_db.get(str(guild.id), {}).get(msg_id)
        channel = guild.get_channel(int(ch_id)) if ch_id else None
        if poll and not poll.get("closed") and channel:
            await finish_poll(await channel.fetch_message(int(msg_id)), poll)

async def scheduler_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now = _time.time()
            due = [x for x in schedule_db["tasks"] if x["at"] <= now]
            for task in due:
                try:
                    await _run_task(task)
                except Exception as e:
                    print(f"[SCHEDULER] {task.get('type')} failed: {e}")
                try:
                    schedule_db["tasks"].remove(task)
                except ValueError:
                    pass
            if due:
                save_schedule()
        except Exception as e:
            print(f"[SCHEDULER] loop error: {e}")
        await asyncio.sleep(15)


# ============================================================
# TICKETS — owner id lives in the channel topic (survives restarts)
# ============================================================
def _ticket_owner(channel):
    m = re.match(r"^ticket:(\d+)$", channel.topic or "")
    return int(m.group(1)) if m else None

class CloseTicketView(BaseView):
    def __init__(self, ticket_num=None, owner_id=None):
        super().__init__(timeout=None)
        self.ticket_num = ticket_num
        self.owner_id = owner_id

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_v3")
    async def close_ticket(self, interaction: discord.Interaction, btn: discord.ui.Button):
        channel = interaction.channel
        owner_id = _ticket_owner(channel)
        staff_id = get_settings(interaction.guild.id).get("ticketstaff")
        is_staff = (interaction.user.guild_permissions.manage_channels
                    or (staff_id and any(r.id == int(staff_id) for r in interaction.user.roles)))
        if not is_staff and interaction.user.id != owner_id:
            await interaction.response.send_message(L('❌ You cannot close this ticket!'), ephemeral=True)
            return
        await interaction.response.send_message(L('🔒 Closing ticket...'))
        if owner_id:
            member = interaction.guild.get_member(owner_id)
            if member:
                try:
                    await send_dm(member, guild=member.guild, embed=discord.Embed(description=L('🔒 Your ticket in **{}** was closed by **{}**.', interaction.guild.name, interaction.user), color=0x808080))
                except Exception:
                    pass
        await asyncio.sleep(2)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception:
            pass

async def create_ticket(interaction, category, emoji):
    guild = interaction.guild
    gid = guild.id
    s = get_settings(gid)
    if user_restricted(interaction.user.id, "tickets"):
        await interaction.response.send_message(restricted_text("tickets"), ephemeral=True)
        return
    if not is_feature_enabled(gid, "tickets"):
        await interaction.response.send_message(t(gid, "feature_off", L(FEATURE_LABELS["tickets"]), "tickets"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    _mp = guild.me.guild_permissions
    if not (_mp.administrator or (_mp.manage_channels and _mp.manage_roles)):
        await interaction.followup.send(L("❌ I need the **{}** permission first.", "Manage Channels, Manage Roles"), ephemeral=True)
        return
    mine = [c for c in guild.text_channels if c.topic == f"ticket:{interaction.user.id}"]
    max_tickets = int(s.get("max_tickets", 2))
    if len(mine) >= max_tickets:
        await interaction.followup.send(L('❌ You already have {} open ticket(s)!', max_tickets), ephemeral=True)
        return
    s["ticket_counter"] = s.get("ticket_counter", 0) + 1
    num = s["ticket_counter"]
    save_settings()
    safe = re.sub(r"[^a-z0-9]", "", interaction.user.name.lower())[:12] or "user"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    staff_role = guild.get_role(int(s["ticketstaff"])) if s.get("ticketstaff") else None
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    slug = re.sub(r"[^a-z]", "", category.lower())[:20]
    try:
        ch = await guild.create_text_channel(f"ticket{num:04d}-{safe}-{slug}", overwrites=overwrites,
                                             topic=f"ticket:{interaction.user.id}", reason=f"Ticket by {interaction.user}")
    except Exception as e:
        await interaction.followup.send(L('❌ Could not create the ticket: {}', e), ephemeral=True)
        return
    embed = discord.Embed(title=L('{} Ticket #{:04d}', emoji, num), color=0x5865F2, timestamp=datetime.now(timezone.utc),
                          description=L('Hey {}! 👋\n\nDescribe your issue and a staff member will help you soon.\n**Category:** {} {}', interaction.user.mention, emoji, category))
    mention = staff_role.mention if staff_role else ""
    await ch.send(content=f"{interaction.user.mention} {mention}".strip(), embed=embed, view=CloseTicketView(num, interaction.user.id))
    await interaction.followup.send(t(gid, "ticket_created", ch.mention), ephemeral=True)
    await send_log(guild, discord.Embed(description=L('🎫 Ticket #{:04d} opened by {} — {} {}', num, interaction.user.mention, emoji, category), color=0x57F287, timestamp=datetime.now(timezone.utc)))


# ============================================================
# CHANNEL LOCK / UNLOCK — one API call per channel, exact restore on unlock
# ============================================================
_LOCK_PERMS = ("send_messages", "add_reactions", "create_public_threads", "create_private_threads",
               "send_messages_in_threads", "use_application_commands", "embed_links", "attach_files",
               "send_polls", "send_voice_messages")

def _lock_perm_names():
    valid = getattr(discord.Permissions, "VALID_FLAGS", None)
    if not valid:
        return list(_LOCK_PERMS[:6])
    return [p for p in _LOCK_PERMS if p in valid]

def _ow_copy(ow):
    return discord.PermissionOverwrite.from_pair(*ow.pair())

def _pair(ow):
    allow, deny = ow.pair()
    return [allow.value, deny.value]



@bot.command(name="lock")
@commands.bot_has_permissions(manage_roles=True)
async def lock_p(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    ch = channel or ctx.channel
    # ask first, lock afterwards - otherwise the moderator could not answer in the locked channel
    prompt = await ctx.send(embed=discord.Embed(
        description=L('🔒 Which roles may still write in this channel?\nMention up to 3 roles (for example @Moderator) or type `no` for nobody.'),
        color=0xED4245))
    reply, roles = None, []
    try:
        reply = await bot.wait_for("message", timeout=30.0, check=lambda m: m.channel == ctx.channel and m.author == ctx.author)
        if reply.content.strip().lower() not in ("no", "none", "-", "yox", "hayır", "hayir", "нет"):
            roles = [r for r in reply.role_mentions if not r.is_default()][:3]
    except asyncio.TimeoutError:
        pass
    try:
        await lock_channel(ch, roles)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=8)
        return
    for m in (ctx.message, prompt, reply):          # only the command, the question and the answer are removed
        await silent_delete(m)
    if roles:
        who = " ".join(r.mention for r in roles)
        desc = L('This channel has been locked by a moderator.\n**Can write:** {}', who)
    else:
        desc = L('This channel has been locked by a moderator.\n**No one can write here.**')
    notice = await ch.send(embed=discord.Embed(title=L('🔒 Channel Locked'), description=desc, color=0xED4245, timestamp=datetime.now(timezone.utc)))
    s = get_settings(ctx.guild.id)
    s.setdefault("lock_notices", {})[str(ch.id)] = notice.id
    save_settings()
    await send_log(ctx.guild, discord.Embed(description=L('🔒 {} locked by {}', ch.mention, ctx.author.mention), color=0xED4245, timestamp=datetime.now(timezone.utc)))

@bot.command(name="unlock")
@commands.bot_has_permissions(manage_roles=True)
async def unlock_p(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    ch = channel or ctx.channel
    try:
        await unlock_channel(ch)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=8)
        return
    s = get_settings(ctx.guild.id)
    old = s.get("lock_notices", {}).pop(str(ch.id), None)
    if old:
        try:
            await silent_delete(await ch.fetch_message(int(old)))
        except Exception:
            pass
    save_settings()
    await silent_delete(ctx.message)
    await ch.send(embed=discord.Embed(description=L('🔓 {} unlocked!', ch.mention), color=0x57F287), delete_after=15)
    await send_log(ctx.guild, discord.Embed(description=L('🔓 {} unlocked by {}', ch.mention, ctx.author.mention), color=0x57F287, timestamp=datetime.now(timezone.utc)))




# ============================================================
# MODERATION (rewritten: hierarchy checks, persistent timers, localized)
# ============================================================
@bot.command(name="ban")
@commands.bot_has_permissions(ban_members=True)
async def ban_p(ctx, member: discord.Member = None, duration: str = None, *, reason: str = "No reason"):
    gid = ctx.guild.id
    duration, reason, notify = mod_args(duration, reason, None)
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send(t(gid, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.ban @user [1d/2h/30m] [reason]'), delete_after=5)
        return
    if member.id == bot.user.id or not can_act_on(ctx.author, member, ctx.guild):
        await ctx.send(t(gid, "cannot_act"), delete_after=5)
        return
    ban_secs, label = None, L("Permanent")
    if duration:
        secs, lbl = parse_duration(duration)
        if secs:
            ban_secs, label = secs, lbl
        else:
            reason = f"{duration} {reason}".strip()
    try:
        case_id = next_case_s(get_settings(gid))
        dm_text = t(gid, "ban_dm", ctx.guild.name, reason)
        if ban_secs:
            dm_text += "\n" + L("Duration: **{}**", label)
        try:
            await send_dm(member, guild=ctx.guild, notify=notify, embed=discord.Embed(description=dm_text, color=0xED4245))
        except Exception:
            pass
        await member.ban(reason=f"{reason} (by {ctx.author})")
        embed = discord.Embed(color=0xED4245)
        embed.set_author(name=L('🔨 Banned — {}', member), icon_url=member.display_avatar.url)
        embed.add_field(name=L('Duration'), value=f"`{label}`", inline=True)
        embed.add_field(name=L('Reason'), value=reason, inline=False)
        await ctx.send(embed=embed, delete_after=15)
        await ctx.message.add_reaction("✅")
        await post_case_log(ctx.guild, case_id, "ban", member, ctx.author, f"[{label}] {reason}")
        if ban_secs:
            schedule_task("unban", gid, member.id, _time.time() + ban_secs)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="mute")
@commands.bot_has_permissions(manage_roles=True)
async def mute_p(ctx, member: discord.Member = None, duration: str = None, *, reason: str = "No reason"):
    gid = ctx.guild.id
    duration, reason, notify = mod_args(duration, reason, None)
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send(t(gid, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.mute @user [2h] [reason]'), delete_after=8)
        return
    if not can_act_on(ctx.author, member, ctx.guild):
        await ctx.send(t(gid, "cannot_act"), delete_after=5)
        return
    mute_secs, label = None, L("Permanent")
    if duration:
        secs, lbl = parse_duration(duration)
        if secs:
            mute_secs, label = secs, lbl
        else:
            reason = f"{duration} {reason}".strip()
    try:
        role = await get_muted_role(ctx.guild)
        await member.add_roles(role, reason=f"{reason} (by {ctx.author})")
        embed = discord.Embed(color=0x808080)
        embed.set_author(name=L('🔇 Muted — {}', member), icon_url=member.display_avatar.url)
        embed.add_field(name=L('Duration'), value=f"`{label}`", inline=True)
        embed.add_field(name=L('Reason'), value=reason, inline=False)
        await ctx.send(embed=embed, delete_after=15)
        await ctx.message.add_reaction("✅")
        try:
            await send_dm(member, guild=ctx.guild, notify=notify, embed=discord.Embed(description=t(gid, "mute_dm", ctx.guild.name, label, reason), color=0x808080))
        except Exception:
            pass
        await post_case_log(ctx.guild, next_case_s(get_settings(gid)), "mute", member, ctx.author, f"[{label}] {reason}")
        if mute_secs:
            schedule_task("unmute", gid, member.id, _time.time() + mute_secs)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="unmute")
@commands.bot_has_permissions(manage_roles=True)
async def unmute_p(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.unmute @user'), delete_after=5)
        return
    role = find_muted_role(ctx.guild)
    if not role or role not in member.roles:
        await ctx.send(L('❌ This member is not muted!'), delete_after=5)
        return
    try:
        await member.remove_roles(role, reason=f"Unmuted by {ctx.author}")
        await ctx.send(embed=discord.Embed(description=L('🔊 **{}** has been unmuted!', member), color=0x57F287), delete_after=10)
        await ctx.message.add_reaction("✅")
        await post_case_log(ctx.guild, next_case_s(get_settings(ctx.guild.id)), "unmute", member, ctx.author, "Unmuted")
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="timeout", aliases=["tm"])
@commands.bot_has_permissions(moderate_members=True)
async def timeout_p(ctx, member: discord.Member = None, duration: str = "10m", *, reason: str = "No reason"):
    gid = ctx.guild.id
    duration, reason, notify = mod_args(duration, reason, "10m")
    if not ctx.author.guild_permissions.moderate_members:
        await ctx.send(t(gid, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.timeout @user <10s/5m/2h/1d> [reason]'), delete_after=8)
        return
    if not can_act_on(ctx.author, member, ctx.guild):
        await ctx.send(t(gid, "cannot_act"), delete_after=5)
        return
    secs, label = parse_duration(duration)
    if not secs:
        reason = f"{duration} {reason}".strip()
        secs, label = parse_duration("10m")
    if secs > 28 * 86400:
        await ctx.send(L('❌ The maximum timeout is 28 days!'), delete_after=6)
        return
    try:
        until = discord.utils.utcnow() + timedelta(seconds=secs)
        await member.timeout(until, reason=f"{reason} (by {ctx.author})")
        embed = discord.Embed(color=0xFEE75C)
        embed.set_author(name=L('⏱️ Timeout — {}', member), icon_url=member.display_avatar.url)
        embed.add_field(name=L('Duration'), value=f"`{label}`", inline=True)
        embed.add_field(name=L('Expires'), value=dts(until, "R"), inline=True)
        embed.add_field(name=L('Reason'), value=reason, inline=False)
        await ctx.send(embed=embed, delete_after=20)
        await ctx.message.add_reaction("✅")
        try:
            await send_dm(member, guild=ctx.guild, notify=notify, embed=discord.Embed(description=t(gid, "timeout_dm", ctx.guild.name, label, reason), color=0xFEE75C))
        except Exception:
            pass
        await post_case_log(ctx.guild, next_case_s(get_settings(gid)), "timeout", member, ctx.author, f"[{label}] {reason}")
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="softban")
@commands.bot_has_permissions(ban_members=True)
async def softban_p(ctx, member: discord.Member = None, *, reason: str = "No reason"):
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.softban @user [reason]'), delete_after=5)
        return
    if member.id == bot.user.id or not can_act_on(ctx.author, member, ctx.guild):
        await ctx.send(t(ctx.guild.id, "cannot_act"), delete_after=5)
        return
    try:
        await member.ban(reason=f"Softban: {reason} (by {ctx.author})", delete_message_seconds=604800)
        await ctx.guild.unban(member, reason="Softban")
        await ctx.send(embed=discord.Embed(description=L('🔄 **{}** was softbanned! Their recent messages were deleted.', member), color=0xFEE75C), delete_after=10)
        await ctx.message.add_reaction("✅")
        await post_case_log(ctx.guild, next_case_s(get_settings(ctx.guild.id)), "softban", member, ctx.author, reason)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="nick")
@commands.bot_has_permissions(manage_nicknames=True)
async def nick_p(ctx, member: discord.Member = None, *, nick: str = None):
    if not ctx.author.guild_permissions.manage_nicknames:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    if not member:
        await ctx.send(L('❌ Usage: `{}`', '.nick @user [nickname]'), delete_after=5)
        return
    if member != ctx.author and not can_act_on(ctx.author, member, ctx.guild):
        await ctx.send(t(ctx.guild.id, "cannot_act"), delete_after=5)
        return
    try:
        await member.edit(nick=nick, reason=f"Nickname changed by {ctx.author}")
        if nick:
            await ctx.send(embed=discord.Embed(description=L("✅ **{}**'s nickname is now `{}`!", member, nick), color=0x57F287), delete_after=10)
        else:
            await ctx.send(embed=discord.Embed(description=L("✅ **{}**'s nickname was reset!", member), color=0x57F287), delete_after=10)
        await silent_delete(ctx.message)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=5)

@bot.command(name="massrole")
@commands.bot_has_permissions(manage_roles=True)
async def massrole_p(ctx, action: str = None, role: discord.Role = None):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    if (action or "").lower() not in ("add", "remove") or role is None:
        await ctx.send(L('❌ Usage: `{}`', '.massrole add/remove @role'), delete_after=5)
        return
    action = action.lower()
    if role.managed or role.is_default() or role >= ctx.guild.me.top_role:
        await ctx.send(L('❌ I cannot manage that role!'), delete_after=6)
        return
    if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
        await ctx.send(L('❌ You cannot manage a role that is higher than or equal to your top role!'), delete_after=6)
        return
    status = await ctx.send(L('⏳ Working on {} for all members...', role.mention))
    count = 0
    for member in list(ctx.guild.members):
        if member.bot:
            continue
        try:
            if action == "add" and role not in member.roles:
                await member.add_roles(role, reason=f"Massrole by {ctx.author}")
                count += 1
            elif action == "remove" and role in member.roles:
                await member.remove_roles(role, reason=f"Massrole by {ctx.author}")
                count += 1
        except Exception:
            pass
        await asyncio.sleep(0.35)
    await status.edit(content=L('✅ Done! Changed **{}** members.', count))

@bot.command(name="resetchannel")
@commands.bot_has_permissions(manage_channels=True, manage_roles=True)
async def resetchannel_p(ctx):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    ch = ctx.channel
    try:
        new_ch = await ch.clone(reason=f"Channel reset by {ctx.author}")
        await new_ch.edit(position=ch.position)
        s = get_settings(ctx.guild.id)
        for key in ("log", "ticket", "welcome", "levelup", "casino", "botcom", "counting_channel", "honeypot"):
            if s.get(key) == str(ch.id):
                s[key] = str(new_ch.id)
        save_settings()
        await ch.delete(reason=f"Channel reset by {ctx.author}")
        await new_ch.send(embed=discord.Embed(description=L('♻️ Channel reset by **{}**!', ctx.author.display_name), color=0xff6b35), delete_after=15)
    except Exception as e:
        try:
            await ctx.send(f"❌ {e}", delete_after=5)
        except Exception:
            pass

@bot.command(name="say")
async def say_p(ctx, *, message: str = None):
    no_watermark = is_whitelisted(ctx.author.id, "say_no_watermark")
    if not ctx.author.guild_permissions.manage_messages:
        return
    if not message:
        await ctx.send(L('❌ Usage: `{}`', '.say <message>'), delete_after=5)
        return
    await silent_delete(ctx.message)
    can_ping = ctx.author.guild_permissions.mention_everyone
    allowed = discord.AllowedMentions(everyone=can_ping, roles=can_ping, users=True)
    if no_watermark:
        await ctx.send(message, allowed_mentions=allowed)
    else:
        embed = discord.Embed(description=message, color=0x5865F2)
        embed.set_footer(text=L('Sent by {} via Versa Bot', ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


# ============================================================
# ECONOMY STORE + CASINO + FLAG GAME (rewritten)
# ============================================================
def store_embed(guild):
    items = estore_db.get(str(guild.id), {})
    if not items:
        return None
    pfx = get_settings(guild.id).get("prefix", ".")
    embed = discord.Embed(title=L('🛒 {} Store', guild.name), description=L("Use `{}buy <item name>` to purchase!", pfx), color=0xff6b35)
    for item in list(items.values())[:24]:
        role = guild.get_role(int(item["role"])) if item.get("role") else None
        extra = L("\n🎭 Role: {}", role.mention) if role else ""
        embed.add_field(name=f"🏷️ {item['name']}", value=f"💰 **${item['price']:,}**{extra}\n{item.get('description', '')}", inline=True)
    embed.set_footer(text=L('{} item(s) available', len(items)))
    return embed






@bot.command(name="giveitem")
@feature_required("estore")
async def giveitem_p(ctx, *, args: str = None):
    member = next((m for m in ctx.message.mentions if isinstance(m, discord.Member) and m.id != ctx.author.id and not m.bot), None)
    name = _clean_name(re.sub(r"<@!?\d+>", "", args or ""))
    if not member or not name:
        await ctx.send(L('❌ Usage: `{}`', '.giveitem <item name> @user'), delete_after=6)
        return
    inventory = get_econ(ctx.guild.id, ctx.author.id)["inventory"]
    found = next((i for i in inventory if i.lower() == name.lower()), None)
    if not found:
        await ctx.send(L("❌ You don't have `{}`!", name), delete_after=8)
        return
    inventory.remove(found)
    get_econ(ctx.guild.id, member.id)["inventory"].append(found)
    save_econ()
    await ctx.send(embed=discord.Embed(description=L('✅ **{}** was given to {}!', found, member.mention), color=0x57F287))







# ============================================================
# GIVEAWAYS — entry belongs to the clicked message, timers survive restarts
# ============================================================
class GiveawayView(BaseView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Enter", style=discord.ButtonStyle.green, custom_id="giveaway_enter_v2")
    async def enter(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if user_restricted(interaction.user.id, "giveaway"):
            await interaction.response.send_message(restricted_text("giveaway"), ephemeral=True)
            return
        ga = next((g for g in giveaways_db.get(str(interaction.guild.id), {}).values()
                   if str(g.get("message_id")) == str(interaction.message.id)), None)
        if not ga or ga.get("ended"):
            await interaction.response.send_message(L('❌ This giveaway has ended!'), ephemeral=True)
            return
        uid = str(interaction.user.id)
        if uid in ga["participants"]:
            await interaction.response.send_message(L('⚠️ You already entered!'), ephemeral=True)
            return
        ga["participants"].append(uid)
        save_giveaways()
        count = len(ga["participants"])
        try:
            embed = interaction.message.embeds[0]
            if len(embed.fields) > 2:
                embed.set_field_at(2, name=embed.fields[2].name, value=f"`{count}`", inline=True)
            await interaction.message.edit(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message(L('✅ You joined! Total entries: **{}**', count), ephemeral=True)

def giveaway_embed(prize, ends_at, winners, host):
    embed = discord.Embed(title=L('🎉 GIVEAWAY: {}', prize), color=0xff6b35)
    embed.add_field(name=L('Ends'), value=dts(ends_at, "R"), inline=True)
    embed.add_field(name=L('Winners'), value=f"`{winners}`", inline=True)
    embed.add_field(name=L('Entries'), value="`0`", inline=True)
    embed.add_field(name=L('Host'), value=host.mention, inline=True)
    return embed

def register_giveaway(guild_id, channel_id, message_id, prize, winners, ends_at):
    ga_id = str(int(_time.time() * 1000))
    giveaways_db.setdefault(str(guild_id), {})[ga_id] = {
        "prize": prize, "winners": winners, "ends_at": ends_at.isoformat(), "participants": [],
        "ended": False, "message_id": str(message_id), "channel_id": str(channel_id)}
    save_giveaways()
    schedule_task("giveaway", guild_id, ga_id, ends_at.timestamp())
    return ga_id

@bot.command(name="giveaway")
@feature_required("giveaway")
async def giveaway_p(ctx, duration: str = None, *, rest: str = None):
    if not ctx.author.guild_permissions.manage_guild:
        await ctx.send(t(ctx.guild.id, "no_perm"), delete_after=5)
        return
    secs, _label = parse_duration(duration) if duration else (None, "")
    winners, prize = 1, (rest or "").strip()
    first, _, tail = prize.partition(" ")
    if first.isdigit() and tail.strip():
        winners, prize = int(first), tail.strip()
    if not secs or not prize:
        await ctx.send(L('❌ Usage: `{}`', '.giveaway <10m|2h|1d> [winners] <prize>'), delete_after=8)
        return
    secs, winners = max(10, min(secs, 30 * 86400)), max(1, min(winners, 20))
    ends_at = datetime.now(timezone.utc) + timedelta(seconds=secs)
    msg = await ctx.send(embed=giveaway_embed(prize, ends_at, winners, ctx.author), view=GiveawayView())
    register_giveaway(ctx.guild.id, ctx.channel.id, msg.id, prize, winners, ends_at)
    await silent_delete(ctx.message)

@bot.tree.command(name="giveaway", description="Create a giveaway")
@app_commands.guild_only()
@app_commands.describe(duration="Duration (10m, 2h, 1d)", prize="Prize", winners="Number of winners")
async def giveaway_s(interaction: discord.Interaction, duration: str, prize: str, winners: int = 1):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    if not await slash_check_feature(interaction, "giveaway"):
        return
    secs, _label = parse_duration(duration)
    if not secs:
        await interaction.response.send_message(L('❌ Invalid duration! Use for example 10m, 2h or 1d.'), ephemeral=True)
        return
    secs, winners = max(10, min(secs, 30 * 86400)), max(1, min(winners, 20))
    ends_at = datetime.now(timezone.utc) + timedelta(seconds=secs)
    await interaction.response.send_message(embed=giveaway_embed(prize, ends_at, winners, interaction.user), view=GiveawayView())
    msg = await interaction.original_response()
    register_giveaway(interaction.guild.id, interaction.channel.id, msg.id, prize, winners, ends_at)


# ============================================================
# COUNTING CHANNEL + HONEYPOT + ROLE-PERSIST STORAGE
# ============================================================
COUNTING_FILE = "counting.json"
counting_db = load_json(COUNTING_FILE)
ROLE_PERSIST_FILE = "role_persist.json"
role_persist_db = load_json(ROLE_PERSIST_FILE)

def save_counting():
    save_json(COUNTING_FILE, counting_db)

def save_role_persist():
    save_json(ROLE_PERSIST_FILE, role_persist_db)


async def handle_honeypot(message):
    """Returns True when the message was posted in the honeypot channel (and was handled)."""
    guild = message.guild
    s = get_settings(guild.id)
    if not s.get("honeypot") or str(message.channel.id) != str(s["honeypot"]):
        return False
    member = message.author
    if not isinstance(member, discord.Member):
        return True
    if member.id == BOT_CREATOR_ID or member.id == guild.owner_id or member.guild_permissions.administrator:
        return True                                    # staff are exempt (a ban on them would fail anyway)
    content = (message.content or "").replace("`", "'")[:150] or "[attachment/embed]"
    await silent_delete(message)
    banned, error = False, None
    try:
        try:
            await send_dm(member, guild=member.guild, embed=discord.Embed(description=L('🍯 You were banned from **{}** because you sent a message in a honeypot channel (used to catch spam bots and hacked accounts). If your account was hacked, secure it and contact the server staff.', guild.name), color=0xED4245))
        except Exception:
            pass
        await guild.ban(member, reason="Honeypot: posted in the honeypot channel", delete_message_seconds=604800)
        banned = True
    except discord.Forbidden:
        error = "missing permission or role hierarchy"
    except Exception as e:
        error = str(e)
    if banned:
        await post_case_log(guild, next_case_s(get_settings(guild.id)), "ban", member, guild.me, f"[Honeypot] {content}")
        try:
            await message.channel.send(embed=discord.Embed(description=L('🍯 **{}** (`{}`) was banned for posting here. Their recent messages were deleted.', member, member.id), color=0xED4245),
                                       delete_after=20, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            pass
    else:
        await send_log(guild, discord.Embed(title=L('🍯 Honeypot'), description=L('Could not ban {} (`{}`): {}', member.mention, member.id, error), color=0xFEE75C))
    return True


# ============================================================
# OWNER TOOLS — whitelist DM panel, modmail, daily backup, role persist
# ============================================================
async def handle_whitelist_dm(message):
    """DM panel for the bot owner: typing 'whitelist' opens it."""
    uid = message.author.id
    if uid != BOT_CREATOR_ID:
        return False
    text = message.content.strip()
    if text.lower() == "whitelist":
        embed = discord.Embed(title="🔐 Whitelist Manager", color=0xff6b35,
                              description="Whitelist gives people access to *bot owner* commands only - never to server moderation. Access is permanent until you remove it.")
        await message.channel.send(embed=embed, view=WhitelistPanel())
        await _send_chunks(message.channel, ["**Permissions** (groups: `bans`, `money`, `levels`, `messaging`, `info`, `all`)"] + [f"• `{k}` — {v}" for k, v in WL_DESC.items()])
        return True
    session = WL_SESSIONS.get(uid)
    if not session:
        return False
    if text.lower() in ("cancel", "iptal", "отмена"):
        WL_SESSIONS.pop(uid, None)
        await message.channel.send("🚫 Cancelled.")
        return True
    step = session["step"]
    if step == "get_uid":
        try:
            target = await bot.fetch_user(int(text))
        except Exception:
            await message.channel.send("❌ Invalid user ID! Type `cancel` to stop.")
            return True
        session.update({"step": "get_perms", "target_uid": target.id, "target_name": str(target), "perms": []})
        await message.channel.send(f"✅ User: **{target}**\n\nType permission names (one or several separated by spaces), then `done`.\nAvailable: " + ", ".join(f"`{k}`" for k in WL_PERMS))
        return True
    if step == "remove_uid":
        key = re.sub(r"\D", "", text)
        if key in whitelist_db:
            del whitelist_db[key]
            save_whitelist()
            await message.channel.send(f"✅ `{key}` removed from the whitelist!")
        else:
            await message.channel.send(f"⚠️ `{key}` is not whitelisted!")
        WL_SESSIONS.pop(uid, None)
        return True
    if step == "get_perms":
        if text.lower() in ("done", "completed", "finish", "tamam", "bitti"):
            if not session["perms"]:
                await message.channel.send("⚠️ No permission chosen yet. Add at least one or type `cancel`.")
                return True
            commands_ = sorted({c for p in session["perms"] for c in WL_PERMS[p]})
            whitelist_db[str(session["target_uid"])] = {"perms": commands_, "perm_groups": session["perms"],
                                                        "name": session.get("target_name"), "added_at": datetime.now(timezone.utc).isoformat()}
            save_whitelist()
            WL_SESSIONS.pop(uid, None)
            await message.channel.send(f"🎉 **{session.get('target_name')}** is whitelisted!\nAccess: " + ", ".join(f"`{p}`" for p in session["perms"]))
            return True
        added, unknown = [], []
        for word in re.split(r"[\s,]+", text.lower()):
            if not word:
                continue
            if word in WL_PERMS:
                if word not in session["perms"]:
                    session["perms"].append(word)
                added.append(word)
            else:
                unknown.append(word)
        reply = ""
        if added:
            reply += "✔️ Added: " + ", ".join(f"`{w}`" for w in added) + "\n"
        if unknown:
            reply += "❌ Unknown: " + ", ".join(f"`{w}`" for w in unknown) + "\n"
        reply += "Chosen so far: " + (", ".join(f"`{p}`" for p in session["perms"]) or "none") + "\nType more or `done`."
        await message.channel.send(reply)
        return True
    return False

# ---------- modmail: every DM to the bot and /modmail reach the owner, who answers with buttons ----------
_dm_rate = {}
_modmail_cd = {}

def _target_from_message(interaction):
    try:
        m = re.search(r"\((\d{15,25})\)\s*$", interaction.message.embeds[0].author.name or "")
        return int(m.group(1)) if m else None
    except Exception:
        return None

async def forward_to_owner(user, text, attachments=(), title="📨 New DM", guild=None):
    try:
        owner = await bot.fetch_user(BOT_CREATOR_ID)
        embed = discord.Embed(title=title, description=(text or "*[no text]*")[:4000], color=0x5865F2, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
        if guild:
            embed.add_field(name="Server", value=f"{guild.name} (`{guild.id}`)", inline=True)
        if attachments:
            embed.add_field(name="Attachments", value="\n".join(a.url for a in attachments)[:1000], inline=False)
        await owner.send(embed=embed, view=ModmailOwnerView())
        return True
    except Exception as e:
        print(f"[MODMAIL] could not reach the owner: {e}")
        return False

class ModmailReplyModal(discord.ui.Modal, title="Reply"):
    reply_text = discord.ui.TextInput(label="Message", style=discord.TextStyle.long, max_length=1900)

    def __init__(self, target_id):
        super().__init__()
        self.target_id = target_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await bot.fetch_user(self.target_id)
            embed = discord.Embed(description=self.reply_text.value, color=0xff6b35, timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Versa Bot - Support", icon_url=bot.user.display_avatar.url)
            embed.set_footer(text="Reply to this DM to continue the conversation.")
            await user.send(embed=embed)
            await interaction.response.send_message(f"✅ Reply sent to **{user}**!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not send: {e}", ephemeral=True)

class ModmailOwnerView(BaseView):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_CREATOR_ID:
            try:
                await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="💬 Reply", style=discord.ButtonStyle.blurple, custom_id="mm_reply_v3")
    async def reply_mail(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = _target_from_message(interaction)
        if not target:
            await interaction.response.send_message("❌ Could not find the user ID in this message.", ephemeral=True)
            return
        await interaction.response.send_modal(ModmailReplyModal(target))

    @discord.ui.button(label="✅ Close", style=discord.ButtonStyle.green, custom_id="mm_close_v3")
    async def close_mail(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = _target_from_message(interaction)
        if target:
            try:
                user = await bot.fetch_user(target)
                await user.send(embed=discord.Embed(description="✅ Your conversation with support was closed.\nSend a new message any time to start again.", color=0x57F287))
            except Exception:
                pass
        done = ModmailOwnerView()
        for item in done.children:
            item.disabled = True
        await interaction.response.edit_message(view=done)

    @discord.ui.button(label="🚫 Block", style=discord.ButtonStyle.danger, custom_id="mm_block_v3")
    async def block_mail(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = _target_from_message(interaction)
        if target and target != BOT_CREATOR_ID and str(target) not in bot_bans_db["banned"]:
            bot_bans_db["banned"].append(str(target))
            save_bot_bans()
        await interaction.response.send_message(f"⛔ `{target}` is now blocked from the bot.", ephemeral=True)

@bot.tree.command(name="modmail", description="Send a message to the bot owner / support")
@app_commands.describe(message="Your message")
async def modmail_s(interaction: discord.Interaction, message: str):
    if user_restricted(interaction.user.id, "modmail"):
        await interaction.response.send_message(restricted_text("modmail"), ephemeral=True)
        return
    now = _time.time()
    if now - _modmail_cd.get(interaction.user.id, 0) < 60:
        await interaction.response.send_message("⏳ Please wait a minute before sending another message.", ephemeral=True)
        return
    _modmail_cd[interaction.user.id] = now
    ok = await forward_to_owner(interaction.user, message, title="📬 New Modmail", guild=interaction.guild)
    await interaction.response.send_message("✅ Your message was sent! You will get the answer by DM." if ok else "❌ Your message could not be delivered right now.", ephemeral=True)

# ---------- daily backup ----------


async def backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now(timezone.utc)
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((nxt - now).total_seconds())
        await send_backup()


# ---------- role persist (opt-in per server via /setup rolepersist) ----------
def save_member_roles(member):
    if not get_settings(member.guild.id).get("role_persist", False):
        return
    gid, uid = str(member.guild.id), str(member.id)
    roles = [str(r.id) for r in member.roles if not r.is_default() and not r.managed]
    if roles:
        role_persist_db.setdefault(gid, {})[uid] = {"roles": roles, "left_at": datetime.now(timezone.utc).isoformat()}
    else:
        role_persist_db.get(gid, {}).pop(uid, None)
    touch("role_persist", gid, uid); save_role_persist()

async def restore_member_roles(member):
    if not get_settings(member.guild.id).get("role_persist", False):
        return
    saved = role_persist_db.get(str(member.guild.id), {}).pop(str(member.id), None)
    if not saved:
        return
    touch("role_persist", str(member.guild.id), str(member.id)); save_role_persist()
    give = [r for r in (member.guild.get_role(int(rid)) for rid in saved.get("roles", [])) if r and role_assignable(member.guild, r)]
    if give:
        try:
            await member.add_roles(*give, reason="Role persist (member rejoined)")
        except Exception:
            pass

def prune_role_persist(days=60):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for gid in list(role_persist_db):
        for uid in list(role_persist_db[gid]):
            try:
                if datetime.fromisoformat(role_persist_db[gid][uid]["left_at"]) < cutoff:
                    del role_persist_db[gid][uid]
            except Exception:
                del role_persist_db[gid][uid]
    touch_all("role_persist"); save_role_persist()

# ---------- /say and /announcement ----------
@bot.tree.command(name="say", description="Send a message as the bot")
@app_commands.guild_only()
@app_commands.describe(message="Message to send")
async def say_s(interaction: discord.Interaction, message: str):
    no_watermark = is_whitelisted(interaction.user.id, "say_no_watermark")
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    can_ping = interaction.user.guild_permissions.mention_everyone
    allowed = discord.AllowedMentions(everyone=can_ping, roles=can_ping, users=True)
    if no_watermark:
        await interaction.response.send_message(message, allowed_mentions=allowed)
    else:
        embed = discord.Embed(description=message, color=0x5865F2)
        embed.set_footer(text=L('Sent by {} via Versa Bot', interaction.user.display_name), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="announcement", description="Send an announcement embed")
@app_commands.guild_only()
@app_commands.describe(channel="Channel to announce in", title="Title", message="Message", ping="Who to ping")
@app_commands.choices(ping=[app_commands.Choice(name="Nobody", value="none"), app_commands.Choice(name="@everyone", value="everyone"), app_commands.Choice(name="@here", value="here")])
async def announcement_s(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str, ping: str = "none"):
    perms = interaction.user.guild_permissions
    if not perms.manage_messages:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    if ping != "none" and not perms.mention_everyone:
        await interaction.response.send_message(L('❌ You need the Mention Everyone permission to ping!'), ephemeral=True)
        return
    embed = discord.Embed(title=title, description=message, color=0xff6b35, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=L('Announced by {}', interaction.user.display_name))
    try:
        await channel.send(content={"everyone": "@everyone", "here": "@here"}.get(ping), embed=embed,
                           allowed_mentions=discord.AllowedMentions(everyone=ping != "none"))
    except Exception as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return
    await interaction.response.send_message(L('✅ Announcement sent to {}!', channel.mention), ephemeral=True)


# ============================================================
# /SETUP + /RROLES (rewritten: role safety, honeypot, role persist, counting toggle)
# ============================================================
async def _deny_unless_manager(interaction):
    """True (after replying) when the user may NOT configure the server."""
    if interaction.user.guild_permissions.manage_guild:
        return False
    await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
    return True

@setup_group.command(name="welrole", description="Auto-assign a role to new members")
@app_commands.describe(role="Role to give new members")
async def setup_welrole(interaction: discord.Interaction, role: discord.Role):
    if await _deny_unless_manager(interaction):
        return
    if not role_assignable(interaction.guild, role):
        await interaction.response.send_message(L('❌ I cannot give that role: it is bot-managed, above my top role or has moderation permissions!'), ephemeral=True)
        return
    s = get_settings(interaction.guild.id)
    s["welrole"] = str(role.id)
    save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Welcome role: {}! New members get it automatically.', role.mention), color=0x57F287))

@setup_group.command(name="levelrole", description="Give a role when members reach a level")
@app_commands.describe(level="Level that gives the role", role="Role to give")
async def setup_levelrole(interaction: discord.Interaction, level: int, role: discord.Role):
    if await _deny_unless_manager(interaction):
        return
    if not 1 <= level <= 1000:
        await interaction.response.send_message(L('❌ The level must be between 1 and 1000!'), ephemeral=True)
        return
    if not role_assignable(interaction.guild, role):
        await interaction.response.send_message(L('❌ I cannot give that role: it is bot-managed, above my top role or has moderation permissions!'), ephemeral=True)
        return
    s = get_settings(interaction.guild.id)
    s.setdefault("levelroles", {})[str(level)] = str(role.id)
    save_settings()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Level {} gives {}!', level, role.mention), color=0x57F287))

@setup_group.command(name="estore", description="Add or remove items of the economy store")
@app_commands.describe(action="Add or remove", name="Item name", price="Price (when adding)", description="Item description (when adding)", role="Role the item gives when USED (optional)")
@app_commands.choices(action=[app_commands.Choice(name="Add item", value="add"), app_commands.Choice(name="Remove item", value="remove")])
async def setup_estore(interaction: discord.Interaction, action: str, name: str, price: int = 0, description: str = "No description", role: discord.Role = None):
    if await _deny_unless_manager(interaction):
        return
    items = estore_db.setdefault(str(interaction.guild.id), {})
    name = _clean_name(name)[:60]
    if action == "remove":
        key = next((k for k, it in items.items() if it["name"].lower() == name.lower()), None)
        if not key:
            await interaction.response.send_message(L('❌ Item `{}` was not found!', name), ephemeral=True)
            return
        del items[key]
        save_estore()
        await interaction.response.send_message(embed=discord.Embed(description=L('✅ **{}** was removed from the store!', name), color=0x57F287))
        return
    if not 1 <= price <= 1_000_000_000:
        await interaction.response.send_message(L('❌ The price must be between 1 and 1,000,000,000!'), ephemeral=True)
        return
    if role is not None and not role_assignable(interaction.guild, role):
        await interaction.response.send_message(L('❌ That role cannot be sold: it is bot-managed, above my top role or has moderation permissions!'), ephemeral=True)
        return
    if any(it["name"].lower() == name.lower() for it in items.values()):
        await interaction.response.send_message(L('❌ An item with this name already exists!'), ephemeral=True)
        return
    if len(items) >= 24:
        await interaction.response.send_message(L('❌ The store is full (maximum 24 items)!'), ephemeral=True)
        return
    items[str(int(_time.time() * 1000))] = {"name": name, "price": price, "description": description[:200], "role": str(role.id) if role else None}
    save_estore()
    hint = ""
    if not is_feature_enabled(interaction.guild.id, "estore"):
        hint = L("\nℹ️ The store is still switched off. Enable it with /setup feature.")
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ **{}** was added for **${:,}**!{}', name, price, hint), color=0x57F287))

@setup_group.command(name="counting", description="Set up or switch off the counting channel")
@app_commands.describe(channel="Counting channel (leave empty to switch it off)")
async def setup_counting(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if await _deny_unless_manager(interaction):
        return
    s = get_settings(interaction.guild.id)
    gid = str(interaction.guild.id)
    if channel is None:
        s.pop("counting_channel", None)
        s["features"]["counting"] = "disabled"
        counting_db.pop(gid, None)
        save_settings()
        save_counting()
        await interaction.response.send_message(L('✅ Counting is switched off!'), ephemeral=True)
        return
    s["counting_channel"] = str(channel.id)
    s["features"]["counting"] = "enabled"
    counting_db[gid] = {"count": 0}
    save_settings()
    save_counting()
    try:
        await channel.send(embed=discord.Embed(title=L('🔢 Counting Channel'), color=0xff6b35,
                           description=L('Count up together, starting at **1**!\nAnything that breaks the order is deleted.')))
    except Exception:
        pass
    await interaction.response.send_message(L('✅ Counting channel: {}!', channel.mention), ephemeral=True)

@setup_group.command(name="honeypot", description="Honeypot channel: anyone who posts there is banned at once")
@app_commands.describe(channel="Honeypot channel (leave empty to switch it off)")
async def setup_honeypot(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if await _deny_unless_manager(interaction):
        return
    s = get_settings(interaction.guild.id)
    if channel is None:
        s.pop("honeypot", None)
        save_settings()
        await interaction.response.send_message(L('✅ Honeypot is switched off!'), ephemeral=True)
        return
    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.response.send_message(L('❌ I need the Ban Members permission first!'), ephemeral=True)
        return
    s["honeypot"] = str(channel.id)
    save_settings()
    try:
        await channel.send(embed=discord.Embed(title=L('🍯 HONEYPOT - DO NOT WRITE HERE'), color=0xED4245,
                           description=L('Anyone who sends a message in this channel is banned automatically and their recent messages are deleted.\nThis catches spam bots and hacked accounts. Do not type here!')))
    except Exception:
        pass
    await interaction.response.send_message(L('✅ Honeypot channel: {}!\n⚠️ Members must be able to see it and send messages there for the trap to work. Server admins are exempt.', channel.mention), ephemeral=True)

@setup_group.command(name="rolepersist", description="Give members their old roles back when they rejoin")
@app_commands.describe(enabled="Turn role persist on or off")
@app_commands.choices(enabled=[app_commands.Choice(name="✅ Enable", value="on"), app_commands.Choice(name="❌ Disable", value="off")])
async def setup_rolepersist(interaction: discord.Interaction, enabled: str):
    if await _deny_unless_manager(interaction):
        return
    s = get_settings(interaction.guild.id)
    s["role_persist"] = enabled == "on"
    save_settings()
    if enabled == "on":
        await interaction.response.send_message(L('✅ Role persist is on! Members who leave and rejoin get their roles back (roles with moderation permissions are never restored).'))
    else:
        await interaction.response.send_message(L('❌ Role persist is off.'))

_RESET_KEYS = {"welrole": ["welrole"], "botcom": ["botcom"], "log": ["log"], "ticket": ["ticket"], "casino": ["casino"],
               "welcome": ["welcome"], "levelup": ["levelup"], "warnpunish": ["warnpunish"], "prefix": ["prefix"],
               "language": ["language"], "mutedrole": ["mutedrole"], "honeypot": ["honeypot"],
               "rolepersist": ["role_persist"], "levelroles": ["levelroles"]}

@setup_group.command(name="reset", description="Reset one setting (or all)")
@app_commands.describe(setting="Setting to reset")
@app_commands.choices(setting=[
    app_commands.Choice(name="Welcome Role", value="welrole"), app_commands.Choice(name="Bot Commands Channel", value="botcom"),
    app_commands.Choice(name="Log Channel", value="log"), app_commands.Choice(name="Ticket Channel", value="ticket"),
    app_commands.Choice(name="Casino Channel", value="casino"), app_commands.Choice(name="Welcome Channel", value="welcome"),
    app_commands.Choice(name="Level Up Channel", value="levelup"), app_commands.Choice(name="Warn Punishments", value="warnpunish"),
    app_commands.Choice(name="Prefix", value="prefix"), app_commands.Choice(name="Language", value="language"),
    app_commands.Choice(name="Muted Role", value="mutedrole"), app_commands.Choice(name="Counting", value="counting"),
    app_commands.Choice(name="Honeypot", value="honeypot"), app_commands.Choice(name="Role Persist", value="rolepersist"),
    app_commands.Choice(name="Level Roles", value="levelroles"), app_commands.Choice(name="ALL settings", value="all")])
async def setup_reset(interaction: discord.Interaction, setting: str):
    if await _deny_unless_manager(interaction):
        return
    gid = str(interaction.guild.id)
    s = get_settings(interaction.guild.id)
    if setting == "all":
        keep = {k: s[k] for k in ("ticket_counter", "case_counter", "lock_snapshots", "lock_notices") if k in s}
        settings_db[gid] = keep
        touch("settings", gid)
        counting_db.pop(gid, None)
        save_counting()
    elif setting == "counting":
        s.pop("counting_channel", None)
        s["features"]["counting"] = "disabled"
        counting_db.pop(gid, None)
        save_counting()
    else:
        for key in _RESET_KEYS.get(setting, [setting]):
            s.pop(key, None)
    save_settings()
    await interaction.response.send_message(L('🔄 **{}** was reset!', setting), ephemeral=True)

LOG_EVENTS = [("Message Delete", "message_delete"), ("Message Edit", "message_edit"), ("Bulk Delete", "message_bulk"),
              ("Member Join", "member_join"), ("Member Leave", "member_leave"), ("Member Ban", "member_ban"),
              ("Member Unban", "member_unban"), ("Nickname Change", "member_nick"), ("Role Change", "member_role"),
              ("Channel Create", "channel_create"), ("Channel Delete", "channel_delete"), ("Role Create", "role_create"),
              ("Role Delete", "role_delete"), ("Server Update", "server_update")]


@setup_group.command(name="view", description="Show all settings of this server")
async def setup_view(interaction: discord.Interaction):
    s = get_settings(interaction.guild.id)
    g = interaction.guild
    none = L("Not set")

    def chan(key):
        val = s.get(key)
        if not val:
            return none
        c = g.get_channel(int(val))
        return c.mention if c else f"<#{val}>"

    def role(key):
        val = s.get(key)
        if not val:
            return none
        r = g.get_role(int(val))
        return r.mention if r else f"<@&{val}>"

    on, off = L("✅ On"), L("❌ Off")
    embed = discord.Embed(title=L('⚙️ {} Settings', g.name), color=0xff6b35)
    for name, value in [("📋 Log", chan("log")), ("🎫 Ticket", chan("ticket")), ("👋 Welcome", chan("welcome")),
                        ("📊 Level-Up", chan("levelup")), ("🎰 Casino", chan("casino")), ("🤖 Bot Commands", chan("botcom")),
                        ("🔢 Counting", chan("counting_channel")), ("🍯 Honeypot", chan("honeypot")),
                        ("🎭 Ticket Staff", role("ticketstaff")), ("👋 Welcome Role", role("welrole")), ("🔇 Muted Role", role("mutedrole")),
                        ("♻️ Role Persist", on if s.get("role_persist") else off), ("⌨️ Prefix", f"`{s.get('prefix', '.')}`"),
                        ("🌐 Language", s.get("language", "en").upper()),
                        ("📊 XP Difficulty", L(LEVEL_DIFFICULTIES.get(s.get("leveldiff", "normal"), {}).get("label", "Normal"))),
                        ("🎙️ Voice XP Channels", str(len(s.get("vc_channels", []))) if s.get("vc_channels") else none),
                        ("🎙️ Voice XP Difficulty", L(VC_DIFFICULTIES.get(s.get("vcxpdiff", "normal"), VC_DIFFICULTIES["normal"])["label"]))]:
        embed.add_field(name=L(name), value=value, inline=True)
    embed.add_field(name=L('⚙️ Server Features'), value="\n".join(f"{'✅' if is_feature_enabled(g.id, k) else '❌'} {L(lbl)}" for k, lbl in FEATURE_LABELS.items()), inline=False)
    embed.set_footer(text=L('Use /setup feature to toggle'))
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- reaction roles ----------
async def _find_message(guild, current_channel, raw):
    raw = (raw or "").strip()
    m = re.search(r"/channels/\d+/(\d+)/(\d+)", raw)
    if m:
        ch = guild.get_channel(int(m.group(1)))
        try:
            return await ch.fetch_message(int(m.group(2))) if ch else None
        except Exception:
            return None
    if not raw.isdigit():
        return None
    for ch in [current_channel] + [c for c in guild.text_channels if c.id != current_channel.id]:
        try:
            return await ch.fetch_message(int(raw))
        except Exception:
            continue
    return None

def _parse_emoji(text):
    try:
        pe = discord.PartialEmoji.from_str((text or "").strip())
    except Exception:
        return None, None
    if not pe or not pe.name:
        return None, None
    return pe, emoji_key(pe)

@rroles_group.command(name="create", description="Give a role when members react to a message")
@app_commands.describe(message_id="Message ID or message link", emoji="Emoji to react with", role="Role to give")
@app_commands.checks.bot_has_permissions(manage_roles=True, add_reactions=True, read_message_history=True)
async def rroles_create(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    if not role_assignable(interaction.guild, role):
        await interaction.response.send_message(L('❌ I cannot give that role: it is bot-managed, above my top role or has moderation permissions!'), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    msg = await _find_message(interaction.guild, interaction.channel, message_id)
    if not msg:
        await interaction.followup.send(L('❌ Message not found! Use the message ID or the message link.'), ephemeral=True)
        return
    pe, key = _parse_emoji(emoji)
    if not pe:
        await interaction.followup.send(L('❌ Invalid emoji!'), ephemeral=True)
        return
    try:
        await msg.add_reaction(pe)
    except Exception:
        await interaction.followup.send(L('❌ I could not react with that emoji. Use a normal emoji or one from this server.'), ephemeral=True)
        return
    reaction_roles_db.setdefault(str(interaction.guild.id), {}).setdefault(str(msg.id), {})[key] = str(role.id)
    save_reaction_roles()
    embed = discord.Embed(title=L('✅ Reaction Role Created!'), color=0x57F287)
    embed.add_field(name=L('Message'), value=L('[Jump]({})', msg.jump_url), inline=True)
    embed.add_field(name=L('Emoji'), value=emoji_from_key(key), inline=True)
    embed.add_field(name=L('Role'), value=role.mention, inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

@rroles_group.command(name="remove", description="Remove one reaction role")
@app_commands.describe(message_id="Message ID", emoji="Emoji to remove")
async def rroles_remove(interaction: discord.Interaction, message_id: str, emoji: str):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    mid = re.sub(r"\D", "", message_id.split("/")[-1])
    _pe, key = _parse_emoji(emoji)
    entry = reaction_roles_db.get(str(interaction.guild.id), {}).get(mid, {})
    if not key or key not in entry:
        await interaction.response.send_message(L('❌ Reaction role not found!'), ephemeral=True)
        return
    rid = entry.pop(key)
    if not entry:
        reaction_roles_db[str(interaction.guild.id)].pop(mid, None)
    save_reaction_roles()
    await interaction.response.send_message(embed=discord.Embed(description=L('✅ Removed {} → <@&{}>', emoji_from_key(key), rid), color=0xED4245), ephemeral=True)

@rroles_group.command(name="list", description="List all reaction roles of this server")
async def rroles_list(interaction: discord.Interaction):
    data = reaction_roles_db.get(str(interaction.guild.id), {})
    if not data:
        await interaction.response.send_message(L('📋 There are no reaction roles yet!'), ephemeral=True)
        return
    embed = discord.Embed(title=L('🎭 Reaction Roles'), color=0xff6b35)
    for mid, entry in list(data.items())[:25]:
        embed.add_field(name=L('Message `{}`', mid), value="\n".join(f"{emoji_from_key(k)} → <@&{rid}>" for k, rid in entry.items())[:1000] or "-", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@rroles_group.command(name="clear", description="Remove all reaction roles from a message")
@app_commands.describe(message_id="Message ID")
async def rroles_clear(interaction: discord.Interaction, message_id: str):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(t(interaction.guild.id, "no_perm"), ephemeral=True)
        return
    mid = re.sub(r"\D", "", message_id.split("/")[-1])
    removed = reaction_roles_db.get(str(interaction.guild.id), {}).pop(mid, None)
    save_reaction_roles()
    if removed is None:
        await interaction.response.send_message(L('❌ That message has no reaction roles!'), ephemeral=True)
        return
    await interaction.response.send_message(L('✅ Cleared all reaction roles from `{}`!', mid), ephemeral=True)


# ============================================================
# HELP — every command listed here exists (verified by check.py)
# ============================================================
_SETUP_LIST = "`/setup` log · ticket · ticketstaff · ticketpanel · tickettitle · welcome · welrole · levelup · casino · botcom · prefix · mutedrole · levelrole · leveldiff · warnpunish · counting · honeypot · rolepersist · feature · estore · logsettings · view · reset · vc · vcxpdiff"

HELP_TEXT = {
    "en": {
        "mod": ("🛡️ Moderation",
                "`{p}ban @user [1d/2h] [reason]` · `{p}forceban <id> [reason]` (not in the server) · `{p}unban <id>` · `{p}kick @user` · `{p}softban @user`\n"
                "`{p}mute @user [2h]` · `{p}unmute @user` · `{p}timeout @user 10m` · `{p}untimeout @user`\n"
                "`{p}warn @user` · `{p}warnings [@user]` · `{p}clearwarns @user`\n"
                "`{p}history @user` · `{p}case <id>` · `{p}purge <1-100>` · `{p}nick @user [name]`\n"
                "`{p}lock [#channel]` · `{p}unlock [#channel]` · `{p}lockall` · `{p}unlockall` · `{p}lockdown` · `{p}unlockdown`\n"
                "`{p}slowmode <seconds>` · `{p}resetchannel` (admins) · `{p}massrole add/remove @role`"),
        "eco": ("💰 Economy",
                "`{p}bal [@user]` — wallet and bank\n`{p}daily` · `{p}work`\n`{p}dep <amount|all|half|25%>` · `{p}with <amount|all|half|25%>`\n"
                "`{p}rob @user` · `{p}pay @user <amount|all|half|25%>` (10% tax)\n`{p}elb` — richest members"),
        "store": ("🛒 Store",
                  "`{p}estore` — the store, with a **Buy** button under every item\n`{p}buy <item>` — buy by name\n`{p}inv [@user]` — inventory, with a **Use** button under every item (gives its role)\n"
                  "`{p}giveitem <item> @user` — give an item\n"
                  "Admins: `/setup estore`, `/setup feature`"),
        "casino": ("🎰 Casino",
                   "`{p}bj <bet>` — Blackjack · `{p}bj @user1 @user2 <bet>` — up to 4 players\n`{p}hl <bet>` — Higher or Lower (cash out any time)\n`{p}slots <bet>` — Slots\n`{p}cf <bet> heads/tails` — Coinflip\nBets and amounts accept `all`, `half`, `quarter`, `25%`, `1.5k`, `2m`, `100,000,000`"),
        "level": ("📊 Leveling",
                  "`{p}rank [@user]` · `{p}lb` — leaderboard\nXP per message (30s cooldown)\nVoice XP: `{p}vcxp` · `/vcxp`\n"
                  "Admins: `/setup leveldiff`, `/setup levelrole`, `/setup levelup`, `/setup vc`, `/setup vcxpdiff`"),
        "games": ("🏳️ Games",
                  "`{p}flag` — guess the flag in 10 seconds\n`{p}flb` — flag leaderboard\n"
                  "Counting: `/setup counting #channel` (wrong numbers are deleted)"),
        "tickets": ("🎫 Tickets",
                    "Press a button in the ticket panel to open a ticket.\n"
                    "Admins: `/setup ticket`, `/setup ticketstaff`, `/setup ticketpanel`, `/setup tickettitle`"),
        "events": ("🎉 Events",
                   "`{p}giveaway <10m|2h|1d> [winners] <prize>` · `/giveaway`\n`/poll` · `/announcement`\n"
                   "Admins: `/rroles create|remove|list|clear` reaction roles"),
        "general": ("💬 General",
                    "`{p}help` · `{p}ping` · `{p}afk [reason]` · `{p}say <text>` (moderators)\n"
                    "`/userinfo` · `/serverinfo` · `/language` · `{p}dms` · `/dms` · `/modmail` — contact the bot owner"),
        "setup": ("⚙️ Setup", _SETUP_LIST),
    },
    "tr": {
        "mod": ("🛡️ Moderasyon",
                "`{p}ban @üye [1d/2h] [sebep]` · `{p}forceban <id> [sebep]` (sunucuda olmayan) · `{p}unban <id>` · `{p}kick @üye` · `{p}softban @üye`\n"
                "`{p}mute @üye [2h]` · `{p}unmute @üye` · `{p}timeout @üye 10m` · `{p}untimeout @üye`\n"
                "`{p}warn @üye` · `{p}warnings [@üye]` · `{p}clearwarns @üye`\n"
                "`{p}history @üye` · `{p}case <id>` · `{p}purge <1-100>` · `{p}nick @üye [isim]`\n"
                "`{p}lock [#kanal]` · `{p}unlock [#kanal]` · `{p}lockall` · `{p}unlockall` · `{p}lockdown` · `{p}unlockdown`\n"
                "`{p}slowmode <saniye>` · `{p}resetchannel` (yöneticiler) · `{p}massrole add/remove @rol`"),
        "eco": ("💰 Ekonomi",
                "`{p}bal [@üye]` — cüzdan ve banka\n`{p}daily` · `{p}work`\n`{p}dep <miktar|all|half|25%>` · `{p}with <miktar|all|half|25%>`\n"
                "`{p}rob @üye` · `{p}pay @üye <miktar|all|half|25%>` (%10 vergi)\n`{p}elb` — en zenginler"),
        "store": ("🛒 Market",
                  "`{p}estore` — market, her eşyanın altında **Satın al** butonu\n`{p}buy <eşya>` — isimle satın al\n`{p}inv [@üye]` — envanter, her eşyanın altında **Kullan** butonu (rolünü verir)\n"
                  "`{p}giveitem <eşya> @üye` — eşya ver\n"
                  "Yöneticiler: `/setup estore`, `/setup feature`"),
        "casino": ("🎰 Casino",
                   "`{p}bj <bahis>` — Blackjack · `{p}bj @üye1 @üye2 <bahis>` — 4 kişiye kadar\n`{p}hl <bahis>` — Büyük mü küçük mü (istediğin an parayı al)\n`{p}slots <bahis>` — Slot\n`{p}cf <bahis> heads/tails` — Yazı tura\nMiktar: `all`, `half`, `quarter`, `25%`, `1.5k`, `2m`, `100,000,000`"),
        "level": ("📊 Seviye",
                  "`{p}rank [@üye]` · `{p}lb` — sıralama\nHer mesajda XP (30 sn bekleme)\nSes XP: `{p}vcxp` · `/vcxp`\n"
                  "Yöneticiler: `/setup leveldiff`, `/setup levelrole`, `/setup levelup`, `/setup vc`, `/setup vcxpdiff`"),
        "games": ("🏳️ Oyunlar",
                  "`{p}flag` — 10 saniyede bayrağı tahmin et\n`{p}flb` — bayrak sıralaması\n"
                  "Sayı sayma: `/setup counting #kanal` (yanlış sayılar silinir)"),
        "tickets": ("🎫 Ticket",
                    "Ticket panelindeki butona basarak ticket aç.\n"
                    "Yöneticiler: `/setup ticket`, `/setup ticketstaff`, `/setup ticketpanel`, `/setup tickettitle`"),
        "events": ("🎉 Etkinlik",
                   "`{p}giveaway <10m|2h|1d> [kazanan] <ödül>` · `/giveaway`\n`/poll` · `/announcement`\n"
                   "Yöneticiler: `/rroles create|remove|list|clear` tepki rolleri"),
        "general": ("💬 Genel",
                    "`{p}help` · `{p}ping` · `{p}afk [sebep]` · `{p}say <metin>` (moderatörler)\n"
                    "`/userinfo` · `/serverinfo` · `/language` · `{p}dms` · `/dms` · `/modmail` — bot sahibiyle iletişim"),
        "setup": ("⚙️ Kurulum", _SETUP_LIST),
    },
    "ru": {
        "mod": ("🛡️ Модерация",
                "`{p}ban @user [1d/2h] [причина]` · `{p}forceban <id> [причина]` (не на сервере) · `{p}unban <id>` · `{p}kick @user` · `{p}softban @user`\n"
                "`{p}mute @user [2h]` · `{p}unmute @user` · `{p}timeout @user 10m` · `{p}untimeout @user`\n"
                "`{p}warn @user` · `{p}warnings [@user]` · `{p}clearwarns @user`\n"
                "`{p}history @user` · `{p}case <id>` · `{p}purge <1-100>` · `{p}nick @user [ник]`\n"
                "`{p}lock [#канал]` · `{p}unlock [#канал]` · `{p}lockall` · `{p}unlockall` · `{p}lockdown` · `{p}unlockdown`\n"
                "`{p}slowmode <секунды>` · `{p}resetchannel` (админы) · `{p}massrole add/remove @роль`"),
        "eco": ("💰 Экономика",
                "`{p}bal [@user]` — кошелёк и банк\n`{p}daily` · `{p}work`\n`{p}dep <сумма|all|half|25%>` · `{p}with <сумма|all|half|25%>`\n"
                "`{p}rob @user` · `{p}pay @user <сумма|all|half|25%>` (налог 10%)\n`{p}elb` — самые богатые"),
        "store": ("🛒 Магазин",
                  "`{p}estore` — магазин, кнопка **Купить** под каждым предметом\n`{p}buy <предмет>` — купить по названию\n`{p}inv [@user]` — инвентарь, кнопка **Использовать** под каждым предметом (выдаёт роль)\n"
                  "`{p}giveitem <предмет> @user` — передать предмет\n"
                  "Админы: `/setup estore`, `/setup feature`"),
        "casino": ("🎰 Казино",
                   "`{p}bj <ставка>` — Блэкджек · `{p}bj @user1 @user2 <ставка>` — до 4 игроков\n`{p}hl <ставка>` — Больше или меньше (забрать выигрыш можно в любой момент)\n`{p}slots <ставка>` — Слоты\n`{p}cf <ставка> heads/tails` — Монетка\nСумма: `all`, `half`, `quarter`, `25%`, `1.5k`, `2m`, `100,000,000`"),
        "level": ("📊 Уровни",
                  "`{p}rank [@user]` · `{p}lb` — таблица лидеров\nXP за сообщения (пауза 30 сек)\nXP в голосе: `{p}vcxp` · `/vcxp`\n"
                  "Админы: `/setup leveldiff`, `/setup levelrole`, `/setup levelup`, `/setup vc`, `/setup vcxpdiff`"),
        "games": ("🏳️ Игры",
                  "`{p}flag` — угадай флаг за 10 секунд\n`{p}flb` — таблица флагов\n"
                  "Счёт: `/setup counting #канал` (неверные числа удаляются)"),
        "tickets": ("🎫 Тикеты",
                    "Нажми кнопку на панели, чтобы открыть тикет.\n"
                    "Админы: `/setup ticket`, `/setup ticketstaff`, `/setup ticketpanel`, `/setup tickettitle`"),
        "events": ("🎉 События",
                   "`{p}giveaway <10m|2h|1d> [победители] <приз>` · `/giveaway`\n`/poll` · `/announcement`\n"
                   "Админы: `/rroles create|remove|list|clear` роли по реакции"),
        "general": ("💬 Общее",
                    "`{p}help` · `{p}ping` · `{p}afk [причина]` · `{p}say <текст>` (модераторы)\n"
                    "`/userinfo` · `/serverinfo` · `/language` · `{p}dms` · `/dms` · `/modmail` — связь с владельцем бота"),
        "setup": ("⚙️ Настройка", _SETUP_LIST),
    },
}
HELP_PLACEHOLDER = {"en": "📖 Choose a category...", "tr": "📖 Bir kategori seç...", "ru": "📖 Выбери категорию..."}

def _help_lang():
    lang = _LANG.get()
    return lang if lang in HELP_TEXT else "en"

class HelpDropdown(discord.ui.Select):
    def __init__(self, pfx):
        self.pfx = pfx
        lang = _help_lang()
        options = [discord.SelectOption(label=v[0], value=k) for k, v in HELP_TEXT[lang].items()]
        options.append(discord.SelectOption(label=L("📋 All commands"), value="__all__"))
        super().__init__(placeholder=HELP_PLACEHOLDER[lang], options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__all__":
            title, body = L("📋 All commands"), build_all_commands_text(self.pfx)
        else:
            title, body = HELP_TEXT[_help_lang()].get(self.values[0], ("?", "?"))
        embed = discord.Embed(title=title, description=body.replace("{p}", self.pfx), color=0xff6b35)
        embed.set_footer(text=L('Prefix: {}', self.pfx))
        await interaction.response.edit_message(embed=embed)

class HelpView(BaseView):
    def __init__(self, pfx):
        super().__init__(timeout=180)
        self.add_item(HelpDropdown(pfx))

@bot.command(name="help")
async def help_p(ctx):
    pfx = get_settings(ctx.guild.id).get("prefix", ".")
    embed = discord.Embed(title=L('📖 Versa Bot'), color=0xff6b35,
                          description=L('**Prefix:** `{}`\nSupport: {}\n\nPick a category below.', pfx, SUPPORT_LINK))
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    await ctx.send(embed=embed, view=HelpView(pfx))
# ============================================================
# ROUND 2 - fair casino RNG, slots paytable, rob rules, flag game, counting v2, public-server join notice
# ============================================================
_RNG = random.SystemRandom()          # OS entropy: casino results cannot be predicted or biased

# ---------- slots: every emoji has its own value ----------
# (emoji, weight out of 1000, pair multiplier, triple multiplier). Rarer emoji pay more; the clover pays nothing.
SLOT_SYMBOLS = [
    ("🍒", 194, 1, 2), ("🍋", 153, 1.5, 3), ("🍊", 123, 2.5, 5), ("🍇", 92, 5, 10), ("🍉", 71, 7.5, 15),
    ("⭐", 56, 10, 20), ("🔔", 46, 15, 50), ("💎", 39, 25, 100), ("🎰", 31, 30, 300), ("🍀", 195, 0, 0),
]
SLOT_JACKPOT = "🎰"

def slot_spin():
    """Returns (reels, multiplier, kind); kind is 'jackpot', 'triple', 'pair' or 'none'."""
    reels = _RNG.choices([s[0] for s in SLOT_SYMBOLS], weights=[s[1] for s in SLOT_SYMBOLS], k=3)
    top, n = collections.Counter(reels).most_common(1)[0]
    info = next(s for s in SLOT_SYMBOLS if s[0] == top)
    if n == 3 and info[3]:
        return reels, info[3], ("jackpot" if top == SLOT_JACKPOT else "triple")
    if n == 2 and info[2]:
        return reels, info[2], "pair"
    return reels, 0, "none"

def slots_paytable():
    return "\n".join(f"{e}{e}{e} **x{tm:g}**  ·  {e}{e} x{pm:g}" for e, _w, pm, tm in SLOT_SYMBOLS if tm)


# ---------- rob: 30 minute cooldown, a caught robber loses 70% of the wallet ----------
ROB_COOLDOWN = 1800
ROB_FINE_RATE = 0.70

def _fmt_wait(seconds):
    m, s = divmod(int(max(0, seconds)), 60)
    return L("{}m {}s", m, s) if m else L("{}s", s)

@bot.command(name="rob")
@feature_required("economy")
async def rob_p(ctx, member: discord.Member = None):
    gid = ctx.guild.id
    if not member:
        await ctx.send(L("❌ Usage: `{}`", ".rob @user"), delete_after=5)
        return
    if member.id == ctx.author.id:
        await ctx.send(L("❌ Can't rob yourself!"), delete_after=5)
        return
    if member.bot:
        await ctx.send(L("❌ You can't rob a bot!"), delete_after=5)
        return
    victim, robber = get_econ(gid, member.id), get_econ(gid, ctx.author.id)
    wait = ROB_COOLDOWN - (_time.time() - robber.get("last_rob", 0))
    if wait > 0:
        await ctx.send(L("⏳ You can rob again in **{}**!", _fmt_wait(wait)), delete_after=8)
        return
    if victim["wallet"] < 100:
        await ctx.send(embed=discord.Embed(description=t(gid, "rob_poor", member.display_name), color=0xED4245))
        return
    robber["last_rob"] = _time.time()                      # every real attempt starts the cooldown
    if random.random() < 0.4:                              # caught
        fine = int(robber["wallet"] * ROB_FINE_RATE)
        robber["wallet"] -= fine
        save_econ()
        await ctx.send(embed=discord.Embed(description=t(gid, "rob_caught", f"{fine:,}", f"{robber['wallet']:,}"), color=0xED4245))
        return
    stolen = random.randint(50, victim["wallet"] // 2)
    victim["wallet"] -= stolen
    robber["wallet"] += stolen
    save_econ()
    await ctx.send(embed=discord.Embed(description=t(gid, "rob_success", member.display_name, f"{stolen:,}", f"{robber['wallet']:,}"), color=0x57F287))

# ---------- flag game: built-in country list (no web API that can break) ----------
_FLAG_DATA = r'''
ad|Andorra
ae|United Arab Emirates|UAE
af|Afghanistan
ag|Antigua and Barbuda|Antigua
al|Albania
am|Armenia
ao|Angola
ar|Argentina
at|Austria
au|Australia
az|Azerbaijan
ba|Bosnia and Herzegovina|Bosnia
bb|Barbados
bd|Bangladesh
be|Belgium
bf|Burkina Faso
bg|Bulgaria
bh|Bahrain
bi|Burundi
bj|Benin
bn|Brunei
bo|Bolivia
br|Brazil
bs|Bahamas|The Bahamas
bt|Bhutan
bw|Botswana
by|Belarus
bz|Belize
ca|Canada
cd|DR Congo|Democratic Republic of the Congo|Congo Kinshasa
cf|Central African Republic
cg|Republic of the Congo|Congo|Congo Brazzaville
ch|Switzerland
ci|Ivory Coast|Cote d'Ivoire
cl|Chile
cm|Cameroon
cn|China
co|Colombia
cr|Costa Rica
cu|Cuba
cv|Cape Verde|Cabo Verde
cy|Cyprus
cz|Czechia|Czech Republic
de|Germany
dj|Djibouti
dk|Denmark
dm|Dominica
do|Dominican Republic
dz|Algeria
ec|Ecuador
ee|Estonia
eg|Egypt
er|Eritrea
es|Spain
et|Ethiopia
fi|Finland
fj|Fiji
fm|Micronesia
fr|France
ga|Gabon
gb|United Kingdom|UK|Great Britain|Britain
gd|Grenada
ge|Georgia
gh|Ghana
gm|Gambia|The Gambia
gn|Guinea
gq|Equatorial Guinea
gr|Greece
gt|Guatemala
gw|Guinea-Bissau
gy|Guyana
hn|Honduras
hr|Croatia
ht|Haiti
hu|Hungary
id|Indonesia
ie|Ireland
il|Israel
in|India
iq|Iraq
ir|Iran
is|Iceland
it|Italy
jm|Jamaica
jo|Jordan
jp|Japan
ke|Kenya
kg|Kyrgyzstan
kh|Cambodia
ki|Kiribati
km|Comoros
kn|Saint Kitts and Nevis|St Kitts and Nevis
kp|North Korea
kr|South Korea|Korea
kw|Kuwait
kz|Kazakhstan
la|Laos
lb|Lebanon
lc|Saint Lucia|St Lucia
li|Liechtenstein
lk|Sri Lanka
lr|Liberia
ls|Lesotho
lt|Lithuania
lu|Luxembourg
lv|Latvia
ly|Libya
ma|Morocco
mc|Monaco
md|Moldova
me|Montenegro
mg|Madagascar
mh|Marshall Islands
mk|North Macedonia|Macedonia
ml|Mali
mm|Myanmar|Burma
mn|Mongolia
mr|Mauritania
mt|Malta
mu|Mauritius
mv|Maldives
mw|Malawi
mx|Mexico
my|Malaysia
mz|Mozambique
na|Namibia
ne|Niger
ng|Nigeria
ni|Nicaragua
nl|Netherlands|Holland|The Netherlands
no|Norway
np|Nepal
nr|Nauru
nz|New Zealand
om|Oman
pa|Panama
pe|Peru
pg|Papua New Guinea
ph|Philippines|The Philippines
pk|Pakistan
pl|Poland
ps|Palestine
pt|Portugal
pw|Palau
py|Paraguay
qa|Qatar
ro|Romania
rs|Serbia
ru|Russia
rw|Rwanda
sa|Saudi Arabia
sb|Solomon Islands
sc|Seychelles
sd|Sudan
se|Sweden
sg|Singapore
si|Slovenia
sk|Slovakia
sl|Sierra Leone
sm|San Marino
sn|Senegal
so|Somalia
sr|Suriname
ss|South Sudan
st|Sao Tome and Principe
sv|El Salvador
sy|Syria
sz|Eswatini|Swaziland
td|Chad
tg|Togo
th|Thailand
tj|Tajikistan
tl|Timor-Leste|East Timor
tm|Turkmenistan
tn|Tunisia
to|Tonga
tr|Turkey|Turkiye
tt|Trinidad and Tobago|Trinidad
tv|Tuvalu
tw|Taiwan
tz|Tanzania
ua|Ukraine
ug|Uganda
us|United States|USA|US|America|United States of America
uy|Uruguay
uz|Uzbekistan
va|Vatican City|Vatican|Holy See
vc|Saint Vincent and the Grenadines|St Vincent
ve|Venezuela
vn|Vietnam|Viet Nam
vu|Vanuatu
ws|Samoa
xk|Kosovo
ye|Yemen
za|South Africa
zm|Zambia
zw|Zimbabwe
'''
FLAGS = []            # [(iso code, display name)]
FLAG_ANSWERS = {}     # iso code -> accepted normalised answers

def _norm_answer(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)

def _load_flags():
    for line in _FLAG_DATA.strip().split("\n"):
        parts = line.split("|")
        if len(parts) >= 2:
            FLAGS.append((parts[0], parts[1]))
            FLAG_ANSWERS[parts[0]] = {_norm_answer(x) for x in parts[1:]}

_load_flags()

@bot.command(name="flag", aliases=["flagguess"])
@feature_required("flag")
async def flag_p(ctx):
    gid = str(ctx.guild.id)
    if ctx.channel.id in active_flags:
        await ctx.send(L("⏳ A flag round is already running here!"), delete_after=5)
        return
    code, name = random.choice(FLAGS)
    accepted = FLAG_ANSWERS[code]
    active_flags[ctx.channel.id] = True
    try:
        embed = discord.Embed(title=L("🏳️ Guess the Flag!"), description=L("You have **10 seconds**! Type the country name in English."), color=0xff6b35)
        embed.set_image(url=f"https://flagcdn.com/w640/{code}.png")
        await ctx.send(embed=embed)
        end, winner = _time.monotonic() + 10, None
        while winner is None:
            left = end - _time.monotonic()
            if left <= 0:
                break
            try:
                msg = await bot.wait_for("message", timeout=left, check=lambda m: m.channel == ctx.channel and not m.author.bot and not user_restricted(m.author.id, "flag"))
            except asyncio.TimeoutError:
                break
            if _norm_answer(msg.content) in accepted:
                winner = msg.author
        if winner:
            flag_scores_db.setdefault(gid, {}).setdefault(str(winner.id), {"total": 0})["total"] += 1
            touch("flag_scores", gid, str(winner.id))
            save_flag_scores()
            await ctx.send(embed=discord.Embed(description=L("✅ {} got it! 🎉 It was **{}**!", winner.mention, name), color=0x57F287))
        else:
            await ctx.send(embed=discord.Embed(description=L("⏰ Time's up! It was **{}**!", name), color=0xED4245))
    finally:
        active_flags.pop(ctx.channel.id, None)

# ---------- counting v2: in order, nobody counts twice in a row, no check-mark reaction ----------
async def handle_counting(message):
    """Returns True when the message was posted in the counting channel (and was handled)."""
    gid = str(message.guild.id)
    s = get_settings(message.guild.id)
    if not s.get("counting_channel") or str(message.channel.id) != str(s["counting_channel"]):
        return False
    if not is_feature_enabled(message.guild.id, "counting"):
        return False
    if user_restricted(message.author.id, "counting"):
        await silent_delete(message)
        return True
    state = counting_db.setdefault(gid, {"count": 0})
    expected, uid = state.get("count", 0) + 1, str(message.author.id)
    text = message.content.strip()
    if text.isascii() and text.isdigit() and int(text) == expected:
        if state.get("last_user") == uid:                      # the same person may not count twice in a row
            await silent_delete(message)
            try:
                await message.channel.send(L("❌ {} Wait for someone else to count!", message.author.mention), delete_after=4)
            except Exception:
                pass
            return True
        state.update(count=expected, last_user=uid, last_msg=message.id)
        touch("counting", gid)
        if expected % 50 == 0:                                 # only milestones get a reaction
            try:
                await message.add_reaction("🎉" if expected % 100 == 0 else "⭐")
            except Exception:
                pass
        return True
    await silent_delete(message)                               # anything that breaks the order is removed
    try:
        await message.channel.send(L("❌ {} The next number is **{}**!", message.author.mention, expected), delete_after=4)
    except Exception:
        pass
    return True

async def handle_counting_edit(before, after):
    """Editing the latest number would fake the sequence: remove it and roll the counter back by one."""
    s = get_settings(after.guild.id)
    if not s.get("counting_channel") or str(after.channel.id) != str(s["counting_channel"]) or not is_feature_enabled(after.guild.id, "counting"):
        return False
    gid = str(after.guild.id)
    state = counting_db.get(gid)
    if not state or state.get("last_msg") != after.id:
        return False
    state.update(count=max(0, state.get("count", 0) - 1), last_user=None, last_msg=None)
    touch("counting", gid)
    await silent_delete(after)
    return True

# ---------- a server added Versa: public servers get a support invite, private ones only a notice ----------
PUBLIC_GUILD_FEATURES = {"DISCOVERABLE", "PARTNERED", "VERIFIED"}


@bot.event
async def on_guild_join(guild):
    if str(guild.id) in bot_bans_db.get("servers", []):          # a banned server is left at once; nobody is messaged and no invite is made
        try:
            if guild.system_channel:
                await guild.system_channel.send("⛔ This server is banned from Versa Bot.")
        except Exception:
            pass
        await guild.leave()


# ============================================================
# POLLS v2 - button voting, live result bars, admin-only close button
# ============================================================
polls_db = load_json("polls.json")
POLL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
_poll_pending = {}

def poll_embed(poll):
    opts, votes = poll["opts"], poll["votes"]
    counts = [0] * len(opts)
    for idx in votes.values():
        if 0 <= idx < len(opts):
            counts[idx] += 1
    total, top, closed = sum(counts), (max(counts) if counts else 0), bool(poll.get("closed"))
    blocks = []
    for i, opt in enumerate(opts):
        pct = counts[i] * 100 / total if total else 0
        filled = round(pct / 10)
        crown = " 🏆" if closed and total and counts[i] == top else ""
        blocks.append(f"{POLL_EMOJIS[i]} **{opt}**{crown}\n`{'█' * filled}{'░' * (10 - filled)}` {pct:.0f}% · {counts[i]}")
    embed = discord.Embed(title=("🔒 " if closed else "📊 ") + poll["q"], description="\n\n".join(blocks), color=0x747F8D if closed else 0x5865F2)
    embed.add_field(name=L("Created by"), value=f"<@{poll['by']}>", inline=True)
    if poll.get("ends") and not closed:
        embed.add_field(name=L("Ends"), value=f"<t:{int(poll['ends'])}:R>", inline=True)
    embed.set_footer(text=L("🔒 Closed · {} votes", total) if closed else L("{} votes", total))
    return embed

def _poll_of(interaction):
    return polls_db.get(str(interaction.guild.id), {}).get(str(interaction.message.id))

def schedule_poll_refresh(message, poll):
    """Edits are batched: many quick votes cause one edit, so the poll never runs into Discord's edit rate limit."""
    if message.id in _poll_pending:
        return
    async def _go():
        await asyncio.sleep(1.5)
        try:
            await message.edit(embed=poll_embed(poll))
        except Exception:
            pass
    task = asyncio.create_task(_go())
    _poll_pending[message.id] = task
    task.add_done_callback(lambda _t, mid=message.id: _poll_pending.pop(mid, None))

async def finish_poll(message, poll):
    poll["closed"] = True
    poll["closed_at"] = _time.time()
    touch("polls", str(message.guild.id))
    await message.edit(embed=poll_embed(poll), view=None)

class PollOptionButton(discord.ui.Button):
    def __init__(self, idx, row):
        super().__init__(style=discord.ButtonStyle.secondary, emoji=POLL_EMOJIS[idx], custom_id=f"poll_opt_{idx}", row=row)
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        if user_restricted(interaction.user.id, "poll"):
            await interaction.response.send_message(restricted_text("poll"), ephemeral=True)
            return
        poll = _poll_of(interaction)
        if not poll or poll.get("closed") or self.idx >= len(poll["opts"]):
            await interaction.response.send_message(L("❌ This poll is closed!"), ephemeral=True)
            return
        uid = str(interaction.user.id)
        if poll["votes"].get(uid) == self.idx:                 # clicking the same option again takes the vote back
            del poll["votes"][uid]
            reply = L("↩️ Your vote was removed.")
        else:
            poll["votes"][uid] = self.idx
            reply = L("✅ You voted for **{}**!", poll["opts"][self.idx])
        touch("polls", str(interaction.guild.id))
        await interaction.response.send_message(reply, ephemeral=True)
        schedule_poll_refresh(interaction.message, poll)

class PollCloseButton(discord.ui.Button):
    def __init__(self, row):
        super().__init__(label=L("Close poll"), emoji="🔒", style=discord.ButtonStyle.danger, custom_id="poll_close", row=row)

    async def callback(self, interaction: discord.Interaction):
        perms = interaction.user.guild_permissions
        if not (perms.manage_guild or perms.administrator):
            await interaction.response.send_message(L("❌ Only server admins can close polls!"), ephemeral=True)
            return
        poll = _poll_of(interaction)
        if not poll:
            await interaction.response.send_message(L("❌ Poll data not found!"), ephemeral=True)
            return
        poll["closed"] = True
        poll["closed_at"] = _time.time()
        touch("polls", str(interaction.guild.id))
        await interaction.response.edit_message(embed=poll_embed(poll), view=None)

class PollView(BaseView):
    def __init__(self, n=10):
        super().__init__(timeout=None)
        n = max(2, min(n, 10))
        for i in range(n):
            self.add_item(PollOptionButton(i, row=i // 5))
        self.add_item(PollCloseButton(row=1 if n <= 5 else 2))

@bot.tree.command(name="poll", description="Create a poll with voting buttons")
@app_commands.guild_only()
@app_commands.describe(question="Poll question", options="Options separated by | (e.g. Yes | No | Maybe)", duration="Auto-close after, e.g. 1h or 1d (optional)")
async def poll_s(interaction: discord.Interaction, question: str, options: str = "Yes | No", duration: str = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
        return
    if not await slash_check_feature(interaction, "poll"):
        return
    opts = [o.strip()[:80] for o in options.split("|") if o.strip()][:10]
    if len(opts) < 2:
        await interaction.response.send_message(L("❌ A poll needs at least 2 options!"), ephemeral=True)
        return
    ends = None
    if duration:
        secs, _label = parse_duration(duration)
        if not secs:
            await interaction.response.send_message(L("❌ Invalid duration! Use for example 10m, 2h or 1d."), ephemeral=True)
            return
        ends = _time.time() + max(60, min(secs, 30 * 86400))
    poll = {"q": question.strip()[:240], "opts": opts, "votes": {}, "closed": False, "by": str(interaction.user.id), "ends": ends}
    await interaction.response.send_message(embed=poll_embed(poll), view=PollView(len(opts)))
    msg = await interaction.original_response()
    gid = str(interaction.guild.id)
    polls_db.setdefault(gid, {})[str(msg.id)] = poll
    touch("polls", gid)
    if ends:
        schedule_task("poll", gid, f"{interaction.channel.id}:{msg.id}", ends)

def prune_polls(days=30):
    cutoff, changed = _time.time() - days * 86400, False
    for gid in list(polls_db):
        for mid in list(polls_db[gid]):
            p = polls_db[gid][mid]
            if p.get("closed") and p.get("closed_at", _time.time()) < cutoff:
                del polls_db[gid][mid]
                changed = True
        if not polls_db[gid]:
            del polls_db[gid]
    if changed:
        touch_all("polls")

# ============================================================
# TICKET PANEL EDITOR - choose / add the buttons, then send the panel
# ============================================================
def ticket_panel_indices(guild_id):
    pool = get_ticket_buttons(guild_id)
    enabled = get_settings(guild_id).get("ticket_panel")
    if enabled is None:
        return list(range(len(pool)))
    return [i for i in enabled if 0 <= i < len(pool)]

class DynamicTicketView(BaseView):
    """The panel. Button ids stay `tkt_<pool index>_<guild>`, so panels sent earlier keep working after the buttons are edited."""
    def __init__(self, guild_id=0, include_all=False):
        super().__init__(timeout=None)
        self._gid = guild_id
        pool = get_ticket_buttons(guild_id) if guild_id else DEFAULT_TICKET_BUTTONS
        indices = list(range(len(pool))) if (include_all or not guild_id) else ticket_panel_indices(guild_id)
        for pos, i in enumerate(indices[:10]):
            b = pool[i]
            self.add_item(TicketButton(label=b["label"][:80], style=STYLE_MAP.get(b.get("style", "blurple"), discord.ButtonStyle.blurple),
                                       custom_id=f"tkt_{i}_{guild_id}", category=b["category"], emoji_label=b.get("emoji", "🎫"), row=pos // 5))

class AddTicketButtonModal(discord.ui.Modal, title="Add a ticket button"):
    button_name = discord.ui.TextInput(label="Button name", max_length=30)
    button_emoji = discord.ui.TextInput(label="Emoji (optional)", required=False, max_length=40)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor

    async def on_submit(self, interaction: discord.Interaction):
        s = get_settings(interaction.guild.id)
        pool = s.setdefault("ticket_buttons", [dict(b) for b in DEFAULT_TICKET_BUTTONS])
        if len(pool) >= 10:
            await interaction.response.send_message(L("❌ A panel can have at most 10 buttons!"), ephemeral=True)
            return
        name = " ".join(self.button_name.value.split())
        if not name:
            await interaction.response.send_message(L("❌ Give the button a name!"), ephemeral=True)
            return
        raw = (self.button_emoji.value or "").strip()
        emoji_txt = clean_button_emoji(raw) or "🎫"
        pool.append({"label": f"{emoji_txt} {name}", "category": name, "emoji": emoji_txt, "style": "blurple"})
        s["ticket_panel"] = ticket_panel_indices(interaction.guild.id) + [len(pool) - 1]
        save_settings()
        await self.editor.refresh_and_edit(interaction)
        if raw and emoji_txt == "🎫" and raw != "🎫":
            try:
                await interaction.followup.send(L("⚠️ That is not a valid emoji, so 🎫 is used."), ephemeral=True)
            except Exception:
                pass

class TicketPanelEditor(BaseView):
    def __init__(self, guild, channel, user_id):
        super().__init__(timeout=600)
        self.guild, self.channel, self.user_id, self.select, self.emojis = guild, channel, user_id, None, True
        self.refresh_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
            return False
        return True

    def refresh_select(self):
        pool = get_ticket_buttons(self.guild.id)
        enabled, options = set(ticket_panel_indices(self.guild.id)), []
        for i, b in enumerate(pool[:10]):
            em = clean_button_emoji(b.get("emoji")) if self.emojis else None
            options.append(discord.SelectOption(label=(b.get("category") or "?")[:100], value=str(i), emoji=em, default=i in enabled))
        if self.select is not None:
            self.remove_item(self.select)
        self.select = discord.ui.Select(placeholder=L("Buttons shown on the panel"), min_values=1, max_values=len(options), options=options, row=0)
        self.select.callback = self._changed
        self.add_item(self.select)

    async def refresh_and_edit(self, interaction: discord.Interaction):
        """Redraw the editor; if Discord rejects an emoji the editor is redrawn without emojis instead of failing."""
        self.refresh_select()
        try:
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        except discord.HTTPException:
            self.emojis = False
            self.refresh_select()
            await interaction.response.edit_message(embed=self.make_embed(), view=self)

    def make_embed(self):
        pool = get_ticket_buttons(self.guild.id)
        shown = " · ".join(pool[i]["label"] for i in ticket_panel_indices(self.guild.id)) or "-"
        embed = discord.Embed(title=L("🎫 Ticket Panel Editor"), color=0x5865F2,
                              description=L("Choose which buttons the panel shows, add your own, then press **Send panel**.\nPanel channel: {}", self.channel.mention))
        embed.add_field(name=L("Panel preview"), value=shown[:1000], inline=False)
        return embed

    async def _changed(self, interaction: discord.Interaction):
        s = get_settings(self.guild.id)
        s["ticket_panel"] = sorted(int(v) for v in self.select.values)
        save_settings()
        await self.refresh_and_edit(interaction)

    @discord.ui.button(label="➕ Add button", style=discord.ButtonStyle.secondary, row=1)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddTicketButtonModal(self))

    @discord.ui.button(label="📨 Send panel", style=discord.ButtonStyle.success, row=1)
    async def send_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = get_settings(self.guild.id)
        if not ticket_panel_indices(self.guild.id):
            await interaction.response.send_message(L("❌ Pick at least one button!"), ephemeral=True)
            return
        embed = discord.Embed(title=s.get("ticket_panel_title", "🎫 Ticket Support"), color=0x5865F2,
                              description=s.get("ticket_panel_desc", "Do you need help? Click a button below!\nOur staff will assist you as soon as possible."))
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        try:
            await self.channel.send(embed=embed, view=DynamicTicketView(self.guild.id))
        except Exception as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content=L("✅ Ticket panel sent to {}!", self.channel.mention), embed=None, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_editor(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="🚫", embed=None, view=None)

@setup_group.command(name="ticketpanel", description="Choose the panel buttons and send the ticket panel")
@app_commands.describe(channel="Where to send the panel (default: the ticket channel)")
async def setup_ticketpanel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
        return
    s = get_settings(interaction.guild.id)
    target = channel
    if target is None:
        if not s.get("ticket"):
            await interaction.response.send_message(L("❌ Set ticket channel first with `/setup ticket`!"), ephemeral=True)
            return
        target = interaction.guild.get_channel(int(s["ticket"]))
        if target is None:
            await interaction.response.send_message(L("❌ Ticket channel not found!"), ephemeral=True)
            return
    editor = TicketPanelEditor(interaction.guild, target, interaction.user.id)
    try:
        await interaction.response.send_message(embed=editor.make_embed(), view=editor, ephemeral=True)
    except discord.HTTPException:
        editor.emojis = False
        editor.refresh_select()
        await interaction.response.send_message(embed=editor.make_embed(), view=editor, ephemeral=True)

# ============================================================
# DELETE DATA - what the bot stores ABOUT A PERSON (moderation records are never deletable here)
# ============================================================
_DD_NESTED = {"economy": economy_db, "levels": levels_db, "msgstats": msgstats_db, "flag_scores": flag_scores_db, "role_persist": role_persist_db}

DD_USER = {
    "economy": "💰 Whole economy profile (wallet, bank, inventory, timers)",
    "wallet": "💵 Wallet only (reset to 0)",
    "bank": "🏦 Bank only (reset to 0)",
    "inventory": "🎒 Inventory only (store items)",
    "cooldowns": "⏳ Daily / work / rob timers",
    "levels": "📊 Level / XP",
    "msgstats": "💬 Message counts (today / 7 days / 30 days / total)",
    "flag_scores": "🏳️ Flag game score",
    "role_persist": "♻️ Saved roles (role persist)",
    "giveaways": "🎉 Giveaway entries",
    "poll_votes": "🗳️ Poll votes",
    "afk": "💤 AFK status",
    "games": "🃏 Running blackjack game (the bet is lost)",
    "limits": "🧠 Rate-limit and XP-cooldown memory",
}

def _econ_profiles(uid):
    return [(g, users[uid]) for g, users in economy_db.items() if isinstance(users.get(uid), dict)]

def dd_user_counts(uid):
    uid = str(uid)
    iu = int(uid)
    counts = {c: sum(1 for users in db.values() if uid in users) for c, db in _DD_NESTED.items()}
    profs = _econ_profiles(uid)
    counts["wallet"] = sum(1 for _g, p in profs if p.get("wallet"))
    counts["bank"] = sum(1 for _g, p in profs if p.get("bank"))
    counts["inventory"] = sum(1 for _g, p in profs if p.get("inventory"))
    counts["cooldowns"] = sum(1 for _g, p in profs if any(k.startswith("last_") for k in p))
    counts["giveaways"] = sum(1 for gas in giveaways_db.values() for ga in gas.values() if uid in ga.get("participants", []))
    counts["poll_votes"] = sum(1 for polls in polls_db.values() for p in polls.values() if uid in p.get("votes", {}))
    counts["afk"] = int(iu in afk_db)
    counts["games"] = int(iu in active_bj)
    counts["limits"] = sum(1 for d in (_cmd_hits, _dm_rate, _modmail_cd) if iu in d) + sum(1 for k in xp_cooldown if k.endswith(f"_{uid}"))
    return counts

def dd_delete_user(uid, cats):
    uid, removed = str(uid), {}
    iu = int(uid)
    for cat in cats:
        n = 0
        if cat in _DD_NESTED:
            for g, users in _DD_NESTED[cat].items():
                if uid in users:
                    del users[uid]
                    touch(cat, g, uid)
                    n += 1
        elif cat in ("wallet", "bank"):
            for g, p in _econ_profiles(uid):
                if p.get(cat):
                    p[cat] = 0
                    touch("economy", g, uid)
                    n += 1
        elif cat == "inventory":
            for g, p in _econ_profiles(uid):
                if p.get("inventory"):
                    p["inventory"] = []
                    touch("economy", g, uid)
                    n += 1
        elif cat == "cooldowns":
            for g, p in _econ_profiles(uid):
                keys = [k for k in p if k.startswith("last_")]
                for k in keys:
                    del p[k]
                if keys:
                    touch("economy", g, uid)
                    n += 1
        elif cat == "giveaways":
            for gas in giveaways_db.values():
                for ga in gas.values():
                    if uid in ga.get("participants", []):
                        ga["participants"].remove(uid)
                        n += 1
            if n:
                touch_all("giveaways")
        elif cat == "poll_votes":
            for g, polls in polls_db.items():
                hit = False
                for p in polls.values():
                    if uid in p.get("votes", {}):
                        del p["votes"][uid]
                        n += 1
                        hit = True
                if hit:
                    touch("polls", g)
        elif cat == "afk":
            n = int(afk_db.pop(iu, None) is not None)
        elif cat == "games":
            n = int(active_bj.pop(iu, None) is not None)
        elif cat == "limits":
            for d in (_cmd_hits, _dm_rate, _modmail_cd):
                if d.pop(iu, None) is not None:
                    n += 1
            for k in [k for k in xp_cooldown if k.endswith(f"_{uid}")]:
                del xp_cooldown[k]
                n += 1
        removed[cat] = n
    return removed



DD_SESSIONS = {}

class DeleteDataPanel(BaseView):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_CREATOR_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        DD_SESSIONS.pop(interaction.user.id, None)
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self, embed=discord.Embed(description="🚫 Cancelled.", color=0x808080))

class DeleteDataView(BaseView):
    def __init__(self, target, found):
        super().__init__(timeout=300)
        self.target, self.found = target, found
        self.chosen, self.armed, self.armed_all = [], False, False
        options = [discord.SelectOption(label=DD_USER[c][:100], value=c, description=f"{n} item(s)") for c, n in found.items()]
        self.menu = discord.ui.Select(placeholder="Choose what to delete...", min_values=1, max_values=len(options), options=options)
        self.menu.callback = self._picked
        self.add_item(self.menu)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_CREATOR_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return False
        return True

    async def _picked(self, interaction: discord.Interaction):
        self.chosen = list(self.menu.values)
        self.armed = self.armed_all = False
        self.delete_selected.label, self.delete_all.label = "🗑️ Delete selected", "💥 Delete everything listed"
        await interaction.response.edit_message(view=self)

    async def _run(self, interaction, cats):
        removed = dd_delete_user(self.target, cats)
        await flush_pending()                                # write the deletion to SQLite right now
        lines = "\n".join(f"• {DD_USER[c]} - removed **{n}**" for c, n in removed.items())
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self, embed=discord.Embed(title="✅ Data deleted", color=0x57F287,
                                                description=f"User `{self.target}`\n\n{lines}\n\nThe deletion is already written to the database."))
        print(f"[PRIVACY] deleted {list(removed)} for user {self.target}")

    @discord.ui.button(label="🗑️ Delete selected", style=discord.ButtonStyle.danger)
    async def delete_selected(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.chosen:
            await interaction.response.send_message("Pick at least one category in the menu first.", ephemeral=True)
            return
        if not self.armed:                                   # two clicks: nothing is deleted by accident
            self.armed = True
            button.label = "⚠️ Click again to confirm"
            await interaction.response.edit_message(view=self)
            return
        await self._run(interaction, self.chosen)

    @discord.ui.button(label="💥 Delete everything listed", style=discord.ButtonStyle.danger)
    async def delete_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.armed_all:
            self.armed_all = True
            button.label = "⚠️ Click again to confirm"
            await interaction.response.edit_message(view=self)
            return
        await self._run(interaction, list(self.found))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self, embed=discord.Embed(description="🚫 Cancelled - nothing was deleted.", color=0x808080))

async def handle_deletedata_dm(message):
    """Bot owner DM: `deletedata` -> panel asks for a user ID -> choose which stored data to delete."""
    uid = message.author.id
    if uid != BOT_CREATOR_ID:
        return False
    text = message.content.strip()
    if text.lower() == "deletedata":
        DD_SESSIONS[uid] = True
        await message.channel.send(embed=discord.Embed(title="🗑️ Data Deletion", color=0xED4245,
            description="Removes the data the bot stores **about one person** (economy, inventory, XP, flag score, saved roles, giveaway entries, temporary memory). **This cannot be undone.**\n\nSend the **user ID** now."),
            view=DeleteDataPanel())
        return True
    if uid not in DD_SESSIONS:
        return False
    if text.lower() in ("cancel", "iptal", "отмена"):
        DD_SESSIONS.pop(uid, None)
        await message.channel.send("🚫 Cancelled.")
        return True
    ids = re.findall(r"\d{15,25}", text)
    if not ids:
        await message.channel.send("❌ Send the numeric user ID (or `cancel`).")
        return True
    DD_SESSIONS.pop(uid, None)
    target = ids[0]
    try:
        who = f"**{await bot.fetch_user(int(target))}** (`{target}`)"
    except Exception:
        who = f"`{target}`"
    found = {c: n for c, n in dd_user_counts(target).items() if n}
    if not found:
        await message.channel.send(f"✅ The bot stores nothing deletable about {who}.")
        return True
    lines = "\n".join(f"• {DD_USER[c]} - **{n}**" for c, n in found.items())
    await message.channel.send(embed=discord.Embed(title="🗑️ Stored data found", color=0xED4245,
        description=f"{who}\n\n{lines}\n\nPick the categories to delete, then confirm with a second click.\n*Moderation records (warnings, bans, timeouts, mutes, case history) are never deleted here.*"),
        view=DeleteDataView(target, found))
    return True

async def _prune_old_backups(owner, keep_days=7):
    """Backups hold personal data - keep them 7 days, then delete the old ones from the owner's DM."""
    try:
        dm = owner.dm_channel or await owner.create_dm()
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        async for m in dm.history(limit=300):
            if m.author.id == bot.user.id and m.created_at < cutoff and m.attachments and m.attachments[0].filename.startswith("versa_backup_"):
                await m.delete()
                await asyncio.sleep(1)
    except Exception as e:
        print(f"[BACKUP] could not prune old backups: {e}")





# ============================================================
# USER RESTRICTIONS - ban a user from the whole bot or only from some features (managed by DM, see the DM commands)
# ============================================================
bot_bans_db.setdefault("restricted", {})
_restrict_notice = {}
RESTRICTABLE = ["economy", "casino", "estore", "leveling", "vcxp", "tickets", "giveaway", "flag", "poll", "reaction_roles", "counting", "afk", "modmail"]
_EXTRA_RESTRICT_LABELS = {"afk": "💤 AFK", "modmail": "📬 Modmail"}

def restrict_label(feature):
    return _EXTRA_RESTRICT_LABELS.get(feature) or FEATURE_LABELS.get(feature, feature)

def user_restricted(uid, feature):
    """True when the user is banned from the whole bot or from this feature (the bot creator never is)."""
    uid = int(uid)
    if uid == BOT_CREATOR_ID:
        return False
    s = str(uid)
    return s in bot_bans_db.get("banned", []) or feature in bot_bans_db.get("restricted", {}).get(s, [])

def current_restrictions(uid):
    s = str(uid)
    out = set(bot_bans_db.get("restricted", {}).get(s, []))
    if s in bot_bans_db.get("banned", []):
        out.add("all")
    return out

def apply_restrictions(uid, chosen):
    """chosen: 'all' (full ban) and/or feature keys. Replaces the user's state; returns (fully_banned, features)."""
    s, chosen = str(uid), set(chosen)
    banned = bot_bans_db.setdefault("banned", [])
    if "all" in chosen:
        if s not in banned:
            banned.append(s)
    elif s in banned:
        banned.remove(s)
    feats = [f for f in RESTRICTABLE if f in chosen]
    if feats:
        bot_bans_db.setdefault("restricted", {})[s] = feats
    else:
        bot_bans_db.setdefault("restricted", {}).pop(s, None)
    save_bot_bans()
    return "all" in chosen, feats

def restricted_text(feature):
    return L("⛔ You are not allowed to use **{}** on this bot.", L(restrict_label(feature)))

async def notify_restricted(ctx, feature):
    """A restricted user used a text command: one short SILENT, self-deleting reply per minute (no DM, no ping)."""
    key, now = (ctx.author.id, feature), _time.time()
    if now - _restrict_notice.get(key, 0) < 60:
        return
    _restrict_notice[key] = now
    text = restricted_text(feature)
    try:
        await ctx.message.reply(text, mention_author=False, silent=True, delete_after=10)
    except Exception:
        try:
            await ctx.channel.send(text, silent=True, delete_after=10)
        except Exception:
            pass


# ============================================================
# OWNER / WHITELIST COMMANDS - they work ONLY in a DM with the bot (no prefix needed, a leading "." is accepted)
# ============================================================
def _id_of(text):
    m = re.search(r"\d{15,25}", text or "")
    return int(m.group(0)) if m else None

def guild_label(g):
    """Public servers show their name; every other server only as 'Private server' + the last digits of its id."""
    if PUBLIC_GUILD_FEATURES & set(g.features):
        return g.name
    return f"Private server …{str(g.id)[-4:]}"

class _OwnerView(BaseView):
    """Base for DM menus: only the person who asked may press anything."""
    def __init__(self, owner_id, timeout=180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This menu is not yours.", ephemeral=True)
            return False
        return True

class GuildPickView(_OwnerView):
    def __init__(self, owner_id, guilds, allow_all=False):
        super().__init__(owner_id, timeout=120)
        self.choice = None
        options = [discord.SelectOption(label=guild_label(g)[:100], value=str(g.id), description=f"{g.member_count} members") for g in guilds[:24]]
        if allow_all:
            options.insert(0, discord.SelectOption(label="🌐 All shared servers", value="all"))
        self.menu = discord.ui.Select(placeholder="Choose the server...", options=options[:25])
        self.menu.callback = self._pick
        self.add_item(self.menu)

    async def _pick(self, interaction: discord.Interaction):
        self.choice = self.menu.values[0]
        await interaction.response.edit_message(content="✅ Server chosen.", view=None)
        self.stop()

async def pick_guilds(message, uid, guild_arg=None, allow_all=False, only=None):
    """Which server(s) a DM command applies to: an explicit id, the only candidate, or a menu."""
    if guild_arg:
        g = bot.get_guild(_id_of(guild_arg) or 0)
        if not g:
            await message.channel.send("❌ I am not in that server.")
            return None
        return [g]
    candidates = only if only is not None else [g for g in bot.guilds if g.get_member(uid)]
    if not candidates:
        await message.channel.send("❌ I share no server with that user. Add the server id as the last argument.")
        return None
    if len(candidates) == 1:
        return candidates
    view = GuildPickView(message.author.id, candidates, allow_all)
    await message.channel.send(f"Which server? ({len(candidates)} candidates)", view=view)
    await view.wait()
    if view.choice is None:
        await message.channel.send("⏰ Timed out.")
        return None
    return candidates if view.choice == "all" else [bot.get_guild(int(view.choice))]

async def _send_chunks(channel, lines, limit=1900):
    buf = ""
    for line in lines:
        if len(buf) + len(line) + 1 > limit:
            await channel.send(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        await channel.send(buf)

# ---------- economy ----------
async def _money(message, args, op):
    reset = op == "reset"
    uid = _id_of(args[0]) if args else None
    amt = None if reset else (parse_amount(args[1], 0) if len(args) > 1 else None)
    if uid is None or (not reset and (amt is None or amt < (0 if op == "set" else 1))):
        await message.channel.send(f"❌ Usage: `{op}money <USER_ID>{'' if reset else ' <AMOUNT>'} [SERVER_ID]`")
        return
    guilds = await pick_guilds(message, uid, args[1 if reset else 2] if len(args) > (1 if reset else 2) else None)
    if not guilds:
        return
    lines = []
    for g in guilds:
        e = get_econ(g.id, uid)
        if op == "add": e["wallet"] += amt
        elif op == "remove": e["wallet"] = max(0, e["wallet"] - amt)
        elif op == "set": e["wallet"] = amt
        else: e["wallet"], e["bank"] = 0, 0
        lines.append(f"• {guild_label(g)} → wallet **${e['wallet']:,}**, bank **${e['bank']:,}**")
    save_econ()
    await message.channel.send(embed=discord.Embed(title=f"✅ {op}money", description=f"<@{uid}> (`{uid}`)\n" + "\n".join(lines), color=0x57F287))

async def dm_addmoney(message, args): await _money(message, args, "add")
async def dm_removemoney(message, args): await _money(message, args, "remove")
async def dm_setmoney(message, args): await _money(message, args, "set")
async def dm_resetmoney(message, args): await _money(message, args, "reset")

# ---------- levels / xp ----------
async def _level(message, args, op):
    uid = _id_of(args[0]) if args else None
    needs_n = op not in ("reset",)
    raw = args[1] if len(args) > 1 else ("1" if op in ("add", "remove", "addxp", "removexp") and uid else None)
    n = int(raw) if raw and raw.lstrip("-").isdigit() else None
    if uid is None or (needs_n and (n is None or n < 0)):
        await message.channel.send(f"❌ Usage: `{ {'addxp': 'addxp', 'removexp': 'removexp'}.get(op, op + 'level') } <USER_ID>{' <NUMBER>' if needs_n else ''} [SERVER_ID]`")
        return
    gi = 1 if op == "reset" else 2
    guilds = await pick_guilds(message, uid, args[gi] if len(args) > gi else None)
    if not guilds:
        return
    lines = []
    for g in guilds:
        gid, u = g.id, get_user_xp(g.id, uid)
        cur = get_level(u["xp"], gid)
        if op == "reset":
            levels_db.get(str(gid), {}).pop(str(uid), None)
            touch("levels", str(gid), str(uid))
            lines.append(f"• {guild_label(g)} → reset")
            continue
        if op in ("addxp", "removexp"):
            u["xp"] = max(0, u["xp"] + (n if op == "addxp" else -n))
        else:
            lvl = max(0, cur + n if op == "add" else cur - n if op == "remove" else n)
            u["xp"] = xp_for_level(lvl, gid)
        u["level"] = get_level(u["xp"], gid)
        lines.append(f"• {guild_label(g)} → level **{u['level']}**, xp **{u['xp']:,}**")
    save_json(LEVELS_FILE, levels_db)
    await message.channel.send(embed=discord.Embed(title=f"✅ {op}", description=f"<@{uid}> (`{uid}`)\n" + "\n".join(lines), color=0x57F287))

async def dm_addlevel(message, args): await _level(message, args, "add")
async def dm_removelevel(message, args): await _level(message, args, "remove")
async def dm_setlevel(message, args): await _level(message, args, "set")
async def dm_resetlevel(message, args): await _level(message, args, "reset")
async def dm_addxp(message, args): await _level(message, args, "addxp")
async def dm_removexp(message, args): await _level(message, args, "removexp")

# ---------- bans: "what do you want to ban this user from?" ----------
async def _notify_target(uid, before, full, feats, notify=False):
    """One private notice to the user - only when the owner ticked "Notify by DM" (nothing is ever sent by default)."""
    if not notify:
        return
    try:
        user = await bot.fetch_user(uid)
        if full and "all" not in before:
            e = discord.Embed(title="⛔ Bot Access Revoked", description="You have been **banned from using this bot**.", color=0xED4245, timestamp=datetime.now(timezone.utc))
        elif not full and set(feats) - before:
            e = discord.Embed(title="⚠️ Bot Access Limited", description="You can no longer use: " + ", ".join(restrict_label(f) for f in feats), color=0xFEE75C)
        elif not full and not feats and before:
            e = discord.Embed(title="✅ Bot Access Restored", description="Your restrictions were lifted.", color=0x57F287)
        else:
            return
        e.set_footer(text="This message was sent privately.")
        await send_dm(user, embed=e, notify=True)
    except Exception:
        pass

class RestrictView(_OwnerView):
    def __init__(self, owner_id, target, target_name, mode):
        super().__init__(owner_id, timeout=300)
        self.target, self.target_name, self.mode = target, target_name, mode
        cur = current_restrictions(target)
        opts = [discord.SelectOption(label="⛔ EVERYTHING - full bot ban", value="all", default="all" in cur)]
        opts += [discord.SelectOption(label=restrict_label(f)[:100], value=f, default=f in cur) for f in RESTRICTABLE]
        self.menu = discord.ui.Select(placeholder="Choose what this user may NOT use...", min_values=0 if mode == "unban" else 1, max_values=len(opts), options=opts)
        self.menu.callback = self._changed
        self.add_item(self.menu)
        self.chosen = set(cur)
        self.notify = False
        if mode != "unban":
            self.remove_item(self.lift)

    async def _changed(self, interaction: discord.Interaction):
        self.chosen = set(self.menu.values)
        await interaction.response.defer()

    async def _apply(self, interaction, chosen):
        before = current_restrictions(self.target)
        full, feats = apply_restrictions(self.target, chosen)
        for item in self.children:
            item.disabled = True
        self.stop()
        lines = (["⛔ **Full bot ban**"] if full else []) + [f"• {restrict_label(f)}" for f in feats]
        await interaction.response.edit_message(embed=discord.Embed(title="✅ Saved", color=0x57F287,
            description=f"**{self.target_name}** (`{self.target}`)\n\n" + ("\n".join(lines) or "No restrictions - everything lifted.")), view=self)
        await _notify_target(self.target, before, full, feats, notify=self.notify)

    @discord.ui.button(label="✅ Apply", style=discord.ButtonStyle.success)
    async def apply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.mode == "ban" and not self.chosen:
            await interaction.response.send_message("Pick at least one option first.", ephemeral=True)
            return
        await self._apply(interaction, self.chosen)

    @discord.ui.button(label="Lift everything", style=discord.ButtonStyle.danger)
    async def lift(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, set())

    @discord.ui.button(label="📨 Notify by DM: OFF", style=discord.ButtonStyle.secondary)
    async def notify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.notify = not self.notify
        button.label = "📨 Notify by DM: ON" if self.notify else "📨 Notify by DM: OFF"
        button.style = discord.ButtonStyle.success if self.notify else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(embed=discord.Embed(description="🚫 Cancelled - nothing changed.", color=0x808080), view=None)

async def _restrict_menu(message, args, mode):
    uid = _id_of(args[0]) if args else None
    if uid is None:
        await message.channel.send(f"❌ Usage: `{mode}user <USER_ID>`")
        return
    if uid == BOT_CREATOR_ID:
        await message.channel.send("❌ The creator cannot be banned or restricted.")
        return
    if mode == "unban" and not current_restrictions(uid):
        await message.channel.send(f"✅ `{uid}` is not banned or restricted.")
        return
    try:
        name = str(await bot.fetch_user(uid))
    except Exception:
        name = str(uid)
    head = "What should this user be banned from?" if mode == "ban" else "Current restrictions - untick what to lift"
    await message.channel.send(embed=discord.Embed(title="🚫 " + head, color=0xED4245,
        description=f"**{name}** (`{uid}`)\nTick **Everything** for a full bot ban, or only the features this user may not use.\nServer moderation (bans, mutes...) is never affected."),
        view=RestrictView(message.author.id, uid, name, mode))

async def dm_banuser(message, args): await _restrict_menu(message, args, "ban")
async def dm_unbanuser(message, args): await _restrict_menu(message, args, "unban")

async def dm_bannedusers(message, args):
    banned, restr = bot_bans_db.get("banned", []), bot_bans_db.get("restricted", {})
    lines = [f"⛔ `{u}` — everything" for u in banned] + [f"⚠️ `{u}` — " + ", ".join(restrict_label(f) for f in fs) for u, fs in restr.items() if u not in banned]
    await _send_chunks(message.channel, lines or ["✅ Nobody is banned or restricted."])

async def dm_banserver(message, args):
    sid = _id_of(args[0]) if args else None
    if sid is None:
        await message.channel.send("❌ Usage: `banserver <SERVER_ID>`")
        return
    if str(sid) not in bot_bans_db["servers"]:
        bot_bans_db["servers"].append(str(sid))
        save_bot_bans()
    g = bot.get_guild(sid)
    if g:
        try:
            if g.system_channel:
                await g.system_channel.send("⛔ This server has been banned from Versa Bot.")
        except Exception:
            pass
        await g.leave()
    await message.channel.send(embed=discord.Embed(description=f"⛔ Server `{sid}` banned" + (" and left!" if g else " (the bot was not in it)."), color=0xED4245))

async def dm_unbanserver(message, args):
    sid = _id_of(args[0]) if args else None
    if sid is None:
        await message.channel.send("❌ Usage: `unbanserver <SERVER_ID>`")
        return
    if str(sid) in bot_bans_db["servers"]:
        bot_bans_db["servers"].remove(str(sid))
        save_bot_bans()
        await message.channel.send(embed=discord.Embed(description=f"✅ Server `{sid}` unbanned!", color=0x57F287))
    else:
        await message.channel.send(f"✅ Server `{sid}` is not banned.")

async def dm_bannedservers(message, args):
    await _send_chunks(message.channel, [f"⛔ `{s}`" for s in bot_bans_db.get("servers", [])] or ["✅ No banned servers."])

async def dm_leaveserver(message, args):
    g = bot.get_guild(_id_of(args[0]) or 0) if args else None
    if not g:
        await message.channel.send("❌ Usage: `leaveserver <SERVER_ID>` (the bot must be in it)")
        return
    label = guild_label(g)
    await g.leave()
    await message.channel.send(f"👋 Left **{label}** (`{g.id}`). It is not banned - it can add the bot again.")

# ---------- messaging ----------
async def dm_saydm(message, args):
    uid = _id_of(args[0]) if args else None
    text = message.content.strip().lstrip(".").split(None, 2)
    if uid is None or len(text) < 3:
        await message.channel.send("❌ Usage: `saydm <USER_ID> <message>`")
        return
    try:
        user = await bot.fetch_user(uid)
        sent = await send_dm(user, notify=True, embed=discord.Embed(description=text[2], color=0x5865F2).set_footer(text=f"Message from the Versa team ({message.author}) · stop DMs from Versa: /dms off"))
        await message.channel.send(f"✅ DM sent to **{user}**!" if sent else f"⛔ **{user}** turned off DMs from Versa - nothing was sent.")
    except Exception as e:
        await message.channel.send(f"❌ {e}")

async def dm_sayin(message, args):
    cid = _id_of(args[0]) if args else None
    text = message.content.strip().lstrip(".").split(None, 2)
    ch = bot.get_channel(cid) if cid else None
    if ch is None or len(text) < 3:
        await message.channel.send("❌ Usage: `sayin <CHANNEL_ID> <message>`")
        return
    try:
        await ch.send(text[2], allowed_mentions=discord.AllowedMentions.none())
        await message.channel.send("✅ Sent.")
    except Exception as e:
        await message.channel.send(f"❌ {e}")

# ---------- information ----------
async def dm_supsearch(message, args):
    uid = _id_of(args[0]) if args else None
    if uid is None:
        await message.channel.send("❌ Usage: `supsearch <USER_ID>`")
        return
    try:
        user = await bot.fetch_user(uid)
    except Exception as e:
        await message.channel.send(f"❌ {e}")
        return
    e = discord.Embed(title="🔍 User Lookup", color=0x5865F2, timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="👤 Username", value=f"**{user}**", inline=True)
    e.add_field(name="🆔 ID", value=f"`{user.id}`", inline=True)
    e.add_field(name="🤖 Bot", value="Yes" if user.bot else "No", inline=True)
    e.add_field(name="📅 Created", value=dts(user.created_at, "F"), inline=True)
    e.add_field(name="⏰ Age", value=dts(user.created_at, "R"), inline=True)
    shared = [g for g in bot.guilds if g.get_member(uid)]
    if shared:
        e.add_field(name=f"🌐 Shared servers ({len(shared)})", value="\n".join(f"• {guild_label(g)}" for g in shared[:8]), inline=False)
    cur = current_restrictions(uid)
    e.add_field(name="⛔ Bot restrictions", value=("everything" if "all" in cur else ", ".join(restrict_label(f) for f in cur)) or "none", inline=False)
    await message.channel.send(embed=e)

async def dm_supstats(message, args):
    e = discord.Embed(title="📊 Bot Stats", color=0xff6b35, timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name="🌐 Servers", value=f"`{len(bot.guilds)}`", inline=True)
    e.add_field(name="👥 Members", value=f"`{sum(g.member_count for g in bot.guilds):,}`", inline=True)
    e.add_field(name="🏓 Latency", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    e.add_field(name="⛔ Banned users", value=f"`{len(bot_bans_db.get('banned', []))}`", inline=True)
    e.add_field(name="⚠️ Restricted users", value=f"`{len(bot_bans_db.get('restricted', {}))}`", inline=True)
    e.add_field(name="⛔ Banned servers", value=f"`{len(bot_bans_db.get('servers', []))}`", inline=True)
    top = sorted(bot.guilds, key=lambda g: g.member_count, reverse=True)[:8]
    e.add_field(name="🌐 Biggest servers", value="\n".join(f"• **{guild_label(g)}** ({g.member_count})" for g in top) or "-", inline=False)
    await message.channel.send(embed=e)

async def dm_servers(message, args):
    lines = [f"• **{guild_label(g)}** — `{g.id}` — {g.member_count} members" for g in sorted(bot.guilds, key=lambda g: g.member_count, reverse=True)]
    await _send_chunks(message.channel, [f"🌐 **{len(bot.guilds)} servers** (private servers are shown without a name)"] + lines)

async def dm_userdata(message, args):
    uid = _id_of(args[0]) if args else None
    if uid is None:
        await message.channel.send("❌ Usage: `userdata <USER_ID>`")
        return
    found = {c: n for c, n in dd_user_counts(uid).items() if n}
    lines = [f"• {DD_USER[c]} — **{n}**" for c, n in found.items()] or ["Nothing deletable is stored."]
    cur = current_restrictions(uid)
    lines.append("⛔ Restrictions: " + (("everything" if "all" in cur else ", ".join(restrict_label(f) for f in cur)) or "none"))
    await message.channel.send(embed=discord.Embed(title=f"🗂️ Stored data for {uid}", description="\n".join(lines), color=0x5865F2))

# ---------- misc ----------
async def dm_stealemoji(message, args):
    eid, name = (_id_of(args[0]) if args else None), (args[1] if len(args) > 1 else None)
    if eid is None or not name:
        await message.channel.send("❌ Usage: `stealemoji <EMOJI_ID> <name> [SERVER_ID]`")
        return
    uid = message.author.id
    def may(g):
        m = g.get_member(uid)
        p = m.guild_permissions if m else None
        return uid == BOT_CREATOR_ID or bool(p and (p.administrator or getattr(p, "manage_expressions", False) or getattr(p, "manage_emojis", False)))
    guilds = await pick_guilds(message, uid, args[2] if len(args) > 2 else None, only=[g for g in bot.guilds if may(g)])
    if not guilds:
        return
    g = guilds[0]
    if not may(g):
        await message.channel.send("❌ You need Manage Expressions in that server.")
        return
    import aiohttp
    async with aiohttp.ClientSession() as session:
        for ext in ("gif", "png"):
            async with session.get(f"https://cdn.discordapp.com/emojis/{eid}.{ext}") as r:
                if r.status == 200:
                    try:
                        emoji = await g.create_custom_emoji(name=name, image=await r.read())
                    except Exception as e:
                        await message.channel.send(f"❌ {e}")
                        return
                    await message.channel.send(f"✅ {emoji} added to **{guild_label(g)}**!")
                    return
    await message.channel.send("❌ Emoji not found!")

async def dm_setstatus(message, args):
    kinds = {"playing": discord.ActivityType.playing, "watching": discord.ActivityType.watching, "listening": discord.ActivityType.listening, "competing": discord.ActivityType.competing}
    if args and args[0].lower() == "clear":
        await bot.change_presence(activity=None)
        await message.channel.send("✅ Status cleared.")
    elif len(args) >= 2 and args[0].lower() in kinds:
        await bot.change_presence(activity=discord.Activity(type=kinds[args[0].lower()], name=" ".join(args[1:])[:100]))
        await message.channel.send("✅ Status updated (it resets when the bot restarts).")
    else:
        await message.channel.send("❌ Usage: `setstatus <playing|watching|listening|competing> <text>` or `setstatus clear`")

async def dm_backup(message, args):
    await send_backup()
    await message.channel.send("💾 Backup sent.")

# name -> (permission, handler, usage, description)
DM_COMMANDS = {
    "banuser": ("banuser", dm_banuser, "banuser <USER_ID>", "Ban a user from the whole bot or only from chosen features (menu)"),
    "unbanuser": ("unbanuser", dm_unbanuser, "unbanuser <USER_ID>", "Lift a bot ban or some restrictions (menu)"),
    "bannedusers": ("bannedusers", dm_bannedusers, "bannedusers", "List banned / restricted users"),
    "banserver": ("banserver", dm_banserver, "banserver <SERVER_ID>", "Ban a server and leave it"),
    "unbanserver": ("unbanserver", dm_unbanserver, "unbanserver <SERVER_ID>", "Lift a server ban"),
    "bannedservers": ("bannedservers", dm_bannedservers, "bannedservers", "List banned servers"),
    "leaveserver": ("leaveserver", dm_leaveserver, "leaveserver <SERVER_ID>", "Leave a server without banning it"),
    "addmoney": ("addmoney", dm_addmoney, "addmoney <USER_ID> <AMOUNT> [SERVER_ID]", "Add wallet money"),
    "removemoney": ("removemoney", dm_removemoney, "removemoney <USER_ID> <AMOUNT> [SERVER_ID]", "Remove wallet money"),
    "setmoney": ("setmoney", dm_setmoney, "setmoney <USER_ID> <AMOUNT> [SERVER_ID]", "Set wallet money"),
    "resetmoney": ("resetmoney", dm_resetmoney, "resetmoney <USER_ID> [SERVER_ID]", "Reset wallet and bank to 0"),
    "addlevel": ("addlevel", dm_addlevel, "addlevel <USER_ID> <N> [SERVER_ID]", "Add levels"),
    "removelevel": ("removelevel", dm_removelevel, "removelevel <USER_ID> <N> [SERVER_ID]", "Remove levels"),
    "setlevel": ("setlevel", dm_setlevel, "setlevel <USER_ID> <LEVEL> [SERVER_ID]", "Set a level"),
    "resetlevel": ("resetlevel", dm_resetlevel, "resetlevel <USER_ID> [SERVER_ID]", "Reset level and XP"),
    "addxp": ("addxp", dm_addxp, "addxp <USER_ID> <N> [SERVER_ID]", "Add XP"),
    "removexp": ("removexp", dm_removexp, "removexp <USER_ID> <N> [SERVER_ID]", "Remove XP"),
    "saydm": ("saydm", dm_saydm, "saydm <USER_ID> <message>", "Send a DM as the bot"),
    "sayin": ("sayin", dm_sayin, "sayin <CHANNEL_ID> <message>", "Send a message to a channel as the bot"),
    "supsearch": ("supsearch", dm_supsearch, "supsearch <USER_ID>", "Look up an account"),
    "supstats": ("supstats", dm_supstats, "supstats", "Bot statistics"),
    "servers": ("servers", dm_servers, "servers", "List servers (private ones without a name)"),
    "userdata": ("userdata", dm_userdata, "userdata <USER_ID>", "What the bot stores about a user"),
    "stealemoji": ("stealemoji", dm_stealemoji, "stealemoji <EMOJI_ID> <name> [SERVER_ID]", "Copy an emoji into a server you manage"),
    "setstatus": ("setstatus", dm_setstatus, "setstatus <playing|watching|listening|competing> <text>", "Change the bot's status"),
    "backup": ("backup", dm_backup, "backup", "Send a database backup now (creator only)"),
}
DM_ALIASES = {"botban": "banuser", "usearch": "supsearch", "guilds": "servers", "steal": "stealemoji", "addemoji": "stealemoji"}

def dm_help_embed(uid):
    lines = [f"`{usage}` — {desc}" for name, (perm, _h, usage, desc) in DM_COMMANDS.items() if is_whitelisted(uid, perm)]
    return discord.Embed(title="🛠️ Owner commands (DM only)", description="\n".join(lines) or "You have no commands.", color=0xff6b35)

async def handle_owner_dm(message):
    """Owner / whitelist commands, DM only. Returns True when the message was one of them."""
    uid = message.author.id
    if not is_whitelisted(uid):
        return False                                       # everybody else: the DM goes to modmail as usual
    parts = message.content.strip().lstrip(".").split()
    if not parts:
        return False
    name = DM_ALIASES.get(parts[0].lower(), parts[0].lower())
    if name in ("help", "commands", "ownerhelp"):
        await message.channel.send(embed=dm_help_embed(uid))
        return True
    entry = DM_COMMANDS.get(name)
    if entry is None:
        return False
    perm, handler = entry[0], entry[1]
    if not is_whitelisted(uid, perm):
        await message.channel.send(f"❌ You don't have permission for `{name}`.")
        return True
    try:
        await handler(message, parts[1:])
    except Exception as e:
        print(f"[DM-CMD] {name} failed: {e}")
        await message.channel.send(f"❌ {e}")
    return True


# ============================================================
# MASS LOCK - lockall/unlockall (nobody can write) and lockdown/unlockdown (every channel hidden). Needs Manage Server.
# ============================================================
_mass_busy = set()
_MASS_KEYS = {"lockall": "lock_snapshots", "lockdown": "hide_snapshots"}

def _mass_active_order(s):
    """Active mass layers, oldest first. They must be undone newest-first, otherwise the restore would not be exact."""
    return [m for m in s.get("mass_order", []) if s.get(_MASS_KEYS[m])]

def _held(channel, target, names):
    """Keep only the permissions `target` really has in this channel right now AND that the bot itself holds:
    nobody gains access they did not have, and Discord refuses to hand out permissions the bot lacks."""
    try:
        mine = channel.permissions_for(channel.guild.me)
        theirs = channel.permissions_for(target)
    except Exception:
        return list(names)
    return [p for p in names if getattr(mine, p, True) and getattr(theirs, p, False)]

async def _apply_overwrites(channel, current, new, reason):
    """Change only what differs, one target at a time: that endpoint needs just Manage Roles (editing the whole channel would also need Manage Channels)."""
    for target, ow in new.items():
        if target not in current or _pair(current[target]) != _pair(ow):
            await channel.set_permissions(target, overwrite=ow, reason=reason)
    for target in current:
        if target not in new:
            await channel.set_permissions(target, overwrite=None, reason=reason)

async def lock_channel(channel, allow_roles=(), allow_members=()):
    """@everyone can only look: no messages, reactions, threads, polls, slash commands. The chosen roles/members keep
    the write permissions they already had in this channel (they never gain new ones)."""
    guild = channel.guild
    s = get_settings(guild.id)
    snaps = s.setdefault("lock_snapshots", {})
    current = channel.overwrites
    everyone = guild.default_role
    targets = [r for r in allow_roles if not r.is_default()] + list(allow_members)
    snap = snaps.setdefault(str(channel.id), {})
    for target in [everyone] + targets:
        snap.setdefault(str(target.id), _pair(current[target]) if target in current else None)
    save_settings()
    names = _lock_perm_names()
    new = dict(current)
    ow = _ow_copy(current[everyone]) if everyone in current else discord.PermissionOverwrite()
    for p in names:
        setattr(ow, p, False)
    new[everyone] = ow
    for target in targets:
        grant = _held(channel, target, names)
        if not grant:
            continue
        ow = _ow_copy(current[target]) if target in current else discord.PermissionOverwrite()
        for p in grant:
            setattr(ow, p, True)
        new[target] = ow
    await _apply_overwrites(channel, current, new, "Channel locked")

async def unlock_channel(channel):
    """Put back exactly what the lock changed (only the permissions the lock touched). True when a snapshot was used."""
    guild = channel.guild
    s = get_settings(guild.id)
    snap = s.get("lock_snapshots", {}).pop(str(channel.id), None)
    current = channel.overwrites
    new = dict(current)
    if snap is None:                        # locked by an older version: just clear @everyone's message limits
        everyone = guild.default_role
        if everyone in current:
            ow = _ow_copy(current[everyone])
            for p in _lock_perm_names():
                setattr(ow, p, None)
            if ow.is_empty():
                new.pop(everyone, None)
            else:
                new[everyone] = ow
            await _apply_overwrites(channel, current, new, "Channel unlocked")
        return False
    for tid, pair in snap.items():
        target = guild.get_role(int(tid)) or guild.get_member(int(tid))
        if target is None:
            continue
        prev = discord.PermissionOverwrite.from_pair(discord.Permissions(pair[0]), discord.Permissions(pair[1])) if pair is not None else discord.PermissionOverwrite()
        ow = _ow_copy(new[target]) if target in new else discord.PermissionOverwrite()
        for p in _lock_perm_names():
            setattr(ow, p, getattr(prev, p))
        if ow.is_empty():
            new.pop(target, None)
        else:
            new[target] = ow
    await _apply_overwrites(channel, current, new, "Channel unlocked")
    save_settings()
    return True

async def hide_channel(channel, see_roles=(), write_roles=(), members=()):
    """Lockdown: @everyone cannot see this channel. see_roles keep reading (no writing), write_roles and members keep
    reading + the write permissions they already had. Nobody gains access they did not have; the bot always keeps viewing.
    Everything touched is saved so unhide_channel can put it back exactly."""
    guild = channel.guild
    s = get_settings(guild.id)
    snap = s.setdefault("hide_snapshots", {}).setdefault(str(channel.id), {})
    current, everyone = channel.overwrites, guild.default_role
    write_names = _lock_perm_names()
    plan = {everyone: {"view_channel": False}}
    write_ids = {r.id for r in write_roles}
    for r in see_roles:
        if r.is_default() or r.id in write_ids or not _held(channel, r, ["view_channel"]):
            continue
        plan[r] = {"view_channel": True, **{p: False for p in write_names}}
    for target in list(write_roles) + list(members):
        if getattr(target, "is_default", lambda: False)() or not _held(channel, target, ["view_channel"]):
            continue
        plan[target] = {"view_channel": True, **{p: True for p in _held(channel, target, write_names)}}
    me = guild.me
    if me is not None and me not in plan:
        plan[me] = {"view_channel": True}
    new = dict(current)
    for target, changes in plan.items():
        entry = snap.setdefault(str(target.id), {"kind": "r" if isinstance(target, discord.Role) else "m", "perms": {}})
        base = current.get(target)
        for perm in changes:
            entry["perms"].setdefault(perm, getattr(base, perm) if base is not None else None)
        ow = _ow_copy(base) if base is not None else discord.PermissionOverwrite()
        for perm, val in changes.items():
            setattr(ow, perm, val)
        new[target] = ow
    save_settings()
    await _apply_overwrites(channel, current, new, "Lockdown")

async def unhide_channel(channel):
    """Undo hide_channel: every permission it touched goes back to what it was. True when a snapshot was used."""
    guild = channel.guild
    s = get_settings(guild.id)
    snap = s.get("hide_snapshots", {}).pop(str(channel.id), None)
    if not snap:
        return False
    new = dict(channel.overwrites)
    for tid, info in snap.items():
        target = guild.get_role(int(tid)) if info["kind"] == "r" else guild.get_member(int(tid))
        if target is None:
            continue
        ow = _ow_copy(new[target]) if target in new else discord.PermissionOverwrite()
        for perm, prev in info["perms"].items():
            setattr(ow, perm, prev)
        if ow.is_empty():
            new.pop(target, None)
        else:
            new[target] = ow
    await _apply_overwrites(channel, channel.overwrites, new, "Lockdown lifted")
    save_settings()
    return True

def can_mass_lock(member):
    p = member.guild_permissions
    return bool(p.manage_guild or p.administrator)

async def _mass_guard(guild, member, say):
    """Shared checks for the four commands. `say` is an async callable that shows an error text to the person."""
    if not can_mass_lock(member):
        await say(L("❌ This needs the **Manage Server** permission!"))
        return False
    mine = guild.me.guild_permissions
    if not (mine.administrator or mine.manage_roles):
        await say(L("❌ I need the **{}** permission first.", "Manage Roles"))
        return False
    if guild.id in _mass_busy:
        await say(L("⏳ Another mass lock/unlock is already running here!"))
        return False
    return True

async def run_mass_lock(guild, mode, write_roles, see_roles, member, report):
    """mode 'lockall': every text channel locked. mode 'lockdown': every channel and category hidden."""
    _mass_busy.add(guild.id)
    try:
        if mode == "lockall":
            targets = list(guild.text_channels) + list(getattr(guild, "forums", []))
        else:
            targets = list(guild.categories) + [c for c in guild.channels if not isinstance(c, discord.CategoryChannel)]
        total, done, failed = len(targets), 0, 0
        for i, ch in enumerate(targets, 1):
            try:
                if mode == "lockall":
                    await lock_channel(ch, write_roles, [member])
                else:
                    await hide_channel(ch, see_roles, write_roles, [member])
                done += 1
            except Exception as e:
                failed += 1
                print(f"[MASS-LOCK] {mode} failed for {ch.id}: {e}")
            await asyncio.sleep(0.5)
            if i % 8 == 0 and i < total:
                try:
                    await report(L("⏳ Working... {}/{} channels", i, total))
                except Exception:
                    pass
        if mode == "lockall":
            text = L('🔒 Locked **{}** channels. Failed: **{}**.', done, failed)
            log = L('🔒 All channels locked by {}', member.mention)
        else:
            text = L("🌑 Lockdown is on: hidden **{}** channels/categories. Failed: **{}**.\nUse `unlockdown` to restore everything.", done, failed)
            log = L("🌑 Lockdown started by {}", member.mention)
        try:
            await report(text)
        except Exception:
            pass
        s = get_settings(guild.id)
        s["mass_order"] = [m for m in s.get("mass_order", []) if m != mode] + [mode]
        save_settings()
        await send_log(guild, discord.Embed(description=log, color=0xED4245, timestamp=datetime.now(timezone.utc)))
    finally:
        _mass_busy.discard(guild.id)

async def run_mass_unlock(guild, mode, report, member):
    s = get_settings(guild.id)
    key = "hide_snapshots" if mode == "lockdown" else "lock_snapshots"
    active = _mass_active_order(s)
    if mode in active and active[-1] != mode:             # undo order matters: newest layer first
        await report(L("⚠️ Lift **{}** first - it was started after this one.", active[-1]))
        return
    _mass_busy.add(guild.id)
    try:
        snaps = s.get(key, {})
        found = {cid: guild.get_channel(int(cid)) for cid in list(snaps)}
        for cid in [cid for cid, c in found.items() if c is None]:
            snaps.pop(cid, None)                                      # the channel was deleted meanwhile
        targets = [c for c in found.values() if c is not None]
        if mode == "lockall" and not targets:                         # locked by an older version: no snapshot saved
            targets = [c for c in guild.text_channels if c.overwrites_for(guild.default_role).send_messages is False]
        if not targets:
            s["mass_order"] = [m for m in s.get("mass_order", []) if m != mode]
            save_settings()
            await report(L("ℹ️ There is no active lockdown.") if mode == "lockdown" else L("ℹ️ No locked channels found."))
            return
        total, done, failed = len(targets), 0, 0
        for i, ch in enumerate(targets, 1):
            try:
                await (unhide_channel(ch) if mode == "lockdown" else unlock_channel(ch))
                done += 1
            except Exception as e:
                failed += 1
                print(f"[MASS-LOCK] {mode} undo failed for {ch.id}: {e}")
            await asyncio.sleep(0.5)
            if i % 8 == 0 and i < total:
                try:
                    await report(L("⏳ Working... {}/{} channels", i, total))
                except Exception:
                    pass
        if mode == "lockall":
            s["lock_notices"] = {}
            text = L('🔓 Unlocked **{}** channels. Failed: **{}**.', done, failed)
            log = L('🔓 All channels unlocked by {}', member.mention)
        else:
            text = L("🌤️ Lockdown lifted: restored **{}** channels/categories. Failed: **{}**.", done, failed)
            log = L("🌤️ Lockdown lifted by {}", member.mention)
        s["mass_order"] = [m for m in s.get("mass_order", []) if m != mode]
        save_settings()
        try:
            await report(text)
        except Exception:
            pass
        await send_log(guild, discord.Embed(description=log, color=0x57F287, timestamp=datetime.now(timezone.utc)))
    finally:
        _mass_busy.discard(guild.id)

def _mass_embed(mode):
    if mode == "lockall":
        return discord.Embed(title=L("🔒 Lock ALL channels"), color=0xED4245,
                             description=L("Nobody can write in any text channel.\nPick the roles that may still write (optional), then press **Start**.\nYou keep your own access. `unlockall` restores every channel exactly as it was."))
    return discord.Embed(title=L("🌑 LOCKDOWN"), color=0x23272A,
                         description=L("Every channel and category is hidden from everyone.\nPick the roles that may still **see** (read-only) and the roles that may see **and write** - both optional - then press **Start**.\nNobody gains access they did not have before. You keep your own access. `unlockdown` restores everything exactly as it was."))

class MassLockPanel(BaseView):
    def __init__(self, guild, user_id, mode):
        super().__init__(timeout=300)
        self.guild, self.user_id, self.mode = guild, user_id, mode
        self.write_roles, self.see_roles, self.started = [], [], False
        self.write_menu = discord.ui.RoleSelect(placeholder=L("Roles that can still SEE and WRITE (optional)") if mode == "lockdown" else L("Roles that can still WRITE (optional)"),
                                                min_values=0, max_values=10, row=0)
        self.write_menu.callback = self._write
        self.add_item(self.write_menu)
        if mode == "lockdown":
            self.see_menu = discord.ui.RoleSelect(placeholder=L("Roles that can still SEE (read-only, optional)"), min_values=0, max_values=10, row=1)
            self.see_menu.callback = self._see
            self.add_item(self.see_menu)
        self.go_btn.label, self.cancel_btn.label = L("✅ Start"), L("Cancel")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id or not can_mass_lock(interaction.user):
            await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
            return False
        return True

    async def _write(self, interaction: discord.Interaction):
        self.write_roles = list(self.write_menu.values)
        await interaction.response.defer()

    async def _see(self, interaction: discord.Interaction):
        self.see_roles = list(self.see_menu.values)
        await interaction.response.defer()

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger, row=2)
    async def go_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            await interaction.response.defer()
            return
        self.started = True
        self.stop()
        await interaction.response.edit_message(content=L("⏳ Working..."), embed=None, view=None)
        async def report(text):
            await interaction.edit_original_response(content=text)
        await run_mass_lock(self.guild, self.mode, self.write_roles, self.see_roles, interaction.user, report)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=L("🚫 Cancelled."), embed=None, view=None)

# ---------- prefix commands ----------
async def _prefix_mass_panel(ctx, mode):
    async def say(text):
        await ctx.send(text, delete_after=8)
    if await _mass_guard(ctx.guild, ctx.author, say):
        await ctx.send(embed=_mass_embed(mode), view=MassLockPanel(ctx.guild, ctx.author.id, mode))

async def _prefix_mass_unlock(ctx, mode):
    async def say(text):
        await ctx.send(text, delete_after=8)
    if not await _mass_guard(ctx.guild, ctx.author, say):
        return
    status = await ctx.send(L("🔓 Unlocking channels..."))
    async def report(text):
        await status.edit(content=text)
    await run_mass_unlock(ctx.guild, mode, report, ctx.author)
    await silent_delete(ctx.message)

@bot.command(name="lockall")
async def lockall_p(ctx):
    await _prefix_mass_panel(ctx, "lockall")

@bot.command(name="unlockall")
async def unlockall_p(ctx):
    await _prefix_mass_unlock(ctx, "lockall")

@bot.command(name="lockdown")
async def lockdown_p(ctx):
    await _prefix_mass_panel(ctx, "lockdown")

@bot.command(name="unlockdown")
async def unlockdown_p(ctx):
    await _prefix_mass_unlock(ctx, "lockdown")

# ---------- slash commands ----------
async def _slash_mass_panel(interaction, mode):
    async def say(text):
        await interaction.response.send_message(text, ephemeral=True)
    if await _mass_guard(interaction.guild, interaction.user, say):
        await interaction.response.send_message(embed=_mass_embed(mode), view=MassLockPanel(interaction.guild, interaction.user.id, mode), ephemeral=True)

async def _slash_mass_unlock(interaction, mode):
    async def say(text):
        await interaction.response.send_message(text, ephemeral=True)
    if not await _mass_guard(interaction.guild, interaction.user, say):
        return
    await interaction.response.send_message(L("🔓 Unlocking channels..."), ephemeral=True)
    async def report(text):
        await interaction.edit_original_response(content=text)
    await run_mass_unlock(interaction.guild, mode, report, interaction.user)

@bot.tree.command(name="lockall", description="Lock every text channel so nobody can write (needs Manage Server)")
@app_commands.guild_only()
async def lockall_s(interaction: discord.Interaction):
    await _slash_mass_panel(interaction, "lockall")

@bot.tree.command(name="unlockall", description="Unlock every channel locked by lockall (needs Manage Server)")
@app_commands.guild_only()
async def unlockall_s(interaction: discord.Interaction):
    await _slash_mass_unlock(interaction, "lockall")

@bot.tree.command(name="lockdown", description="Hide every channel and category from everyone (needs Manage Server)")
@app_commands.guild_only()
async def lockdown_s(interaction: discord.Interaction):
    await _slash_mass_panel(interaction, "lockdown")

@bot.tree.command(name="unlockdown", description="Lift the lockdown and restore every channel (needs Manage Server)")
@app_commands.guild_only()
async def unlockdown_s(interaction: discord.Interaction):
    await _slash_mass_unlock(interaction, "lockdown")



# ============================================================
# VOICE XP - XP for time spent in voice channels. The bot NEVER joins voice and never hears anything: it only reads the
# voice state Discord sends to every bot (which channel, muted / deafened). Time counts only while the person's mic AND
# headphones are on and at least two such people are together; there is a daily limit per person.
# ============================================================
VC_MIN_PEOPLE = 2
VC_TICK = 20                    # seconds between safety ticks (every state change is also handled instantly by an event)
VC_MAX_GAP = 90                 # a longer gap is never credited (bot lag / reconnect: we did not see what happened)
VC_DAILY_MINUTES = 240          # at most 4 hours of voice XP per person per day
VC_MAX_CHANNELS = 100
VC_DIFFICULTIES = {
    "easiest":   {"label": "🟢 Easiest",   "rate": 20},
    "very_easy": {"label": "🟢 Very Easy", "rate": 14},
    "easy":      {"label": "🔵 Easy",      "rate": 10},
    "normal":    {"label": "⚪ Normal",    "rate": 7},
    "hard":      {"label": "🟠 Hard",      "rate": 5},
    "very_hard": {"label": "🔴 Very Hard", "rate": 3},
    "hardest":   {"label": "💀 Hardest",   "rate": 2},
}
_vc_state = {}      # channel id -> (monotonic time of the last look, ids that were eligible since then)
_vc_credit = {}     # (guild id, user id) -> [seconds waiting to become XP, monotonic time of the last credit]

def vc_config(guild_id):
    """Voice XP speed of a server: XP per minute and the daily limit (read-only, never creates a settings row)."""
    s = settings_db.get(str(guild_id), {})
    d = VC_DIFFICULTIES.get(s.get("vcxpdiff", "normal"), VC_DIFFICULTIES["normal"])
    return {"label": d["label"], "rate": d["rate"], "cap": d["rate"] * VC_DAILY_MINUTES}

def vc_channel_ids(guild_id):
    return [int(x) for x in settings_db.get(str(guild_id), {}).get("vc_channels", [])]

def _feature_on(s, feature):
    val = s.get("features", {}).get(feature, DEFAULT_FEATURES.get(feature, "enabled"))
    return val == "enabled" if isinstance(val, str) else bool(val)

def vc_enabled_for(channel):
    """Does this voice channel give XP right now? Feature + leveling on, channel chosen, not the AFK channel."""
    g = channel.guild
    s = settings_db.get(str(g.id))
    if not s or channel.id not in vc_channel_ids(g.id):
        return False
    if not (_feature_on(s, "vcxp") and _feature_on(s, "leveling")):
        return False
    if g.afk_channel is not None and g.afk_channel.id == channel.id:
        return False
    return str(g.id) not in bot_bans_db.get("servers", [])

def vc_eligible(member):
    """May this person earn voice XP at this very moment? Only what Discord tells every bot is used: mic and headphones
    on (no self / server mute or deafen), not in the AFK channel, not a stage listener, not timed out, not set to .afk."""
    vs = member.voice
    if member.bot or vs is None or vs.channel is None:
        return False
    if vs.self_mute or vs.self_deaf or vs.mute or vs.deaf or vs.suppress or vs.afk:
        return False
    if member.is_timed_out() or member.id in afk_db:
        return False
    return not (user_restricted(member.id, "leveling") or user_restricted(member.id, "vcxp"))

def vc_settle(channel, now=None):
    """Close the time since the last look: everybody who was eligible gets those seconds - but only if at least two
    eligible people were together. Then take a fresh snapshot of who is eligible now."""
    now = _time.monotonic() if now is None else now
    if not vc_enabled_for(channel):
        _vc_state.pop(channel.id, None)
        return
    prev = _vc_state.get(channel.id)
    if prev is not None:
        t0, who = prev
        dt = now - t0
        if 0 < dt <= VC_MAX_GAP and len(who) >= VC_MIN_PEOPLE:
            for uid in who:
                c = _vc_credit.setdefault((channel.guild.id, uid), [0.0, now])
                c[0] += dt
                c[1] = now
    _vc_state[channel.id] = (now, frozenset(m.id for m in channel.members if vc_eligible(m)))

def vc_on_voice_state(member, before, after):
    """Instant reaction to a join / leave / mute / deafen, so nobody can dodge the time accounting."""
    if member.bot:
        return
    done = set()
    for ch in (before.channel, after.channel):
        if ch is not None and ch.id not in done:
            done.add(ch.id)
            vc_settle(ch)

def vc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def vc_grant(guild_id, user_id, minutes):
    """Turn credited minutes into XP within the daily limit. Returns (gain, old level, new level)."""
    cfg = vc_config(guild_id)
    row = get_user_xp(guild_id, user_id)
    today = vc_today()
    if row.get("vc_day") != today:
        row["vc_day"], row["vc_xp"] = today, 0
    gain = min(minutes * cfg["rate"], max(0, cfg["cap"] - row.get("vc_xp", 0)))
    if gain <= 0:
        return 0, None, None
    old = get_level(row["xp"], guild_id)
    row["xp"] += gain
    row["vc_xp"] = row.get("vc_xp", 0) + gain
    new = get_level(row["xp"], guild_id)
    row["level"] = new
    return gain, old, new

async def vc_level_up(guild, member, new_level):
    """The same rewards as text XP: announcement in the level-up channel and the level role."""
    s = settings_db.get(str(guild.id), {})
    if s.get("levelup"):
        ch = bot.get_channel(int(s["levelup"]))
        if ch:
            try:
                await ch.send(embed=discord.Embed(description=t(guild.id, "levelup", member.mention, new_level), color=0xff6b35))
            except Exception:
                pass
    rid = s.get("levelroles", {}).get(str(new_level))
    role = guild.get_role(int(rid)) if rid else None
    if role and role_assignable(guild, role):
        try:
            await member.add_roles(role, reason=f"Level {new_level} (voice XP)")
        except Exception:
            pass

async def vc_award_all():
    now = _time.monotonic()
    for key in list(_vc_credit):
        secs, touched = _vc_credit[key]
        if secs >= 60:
            minutes = int(secs // 60)
            _vc_credit[key][0] = secs - minutes * 60
            gid, uid = key
            guild = bot.get_guild(gid)
            member = guild.get_member(uid) if guild else None
            if member is not None:
                gain, old, new = vc_grant(gid, uid, minutes)
                if gain and new > old:
                    await vc_level_up(guild, member, new)
        elif now - touched > 3600:
            del _vc_credit[key]

async def vc_xp_tick():
    seen = set()
    for guild in bot.guilds:
        for cid in vc_channel_ids(guild.id):
            ch = guild.get_channel(cid)
            if ch is not None:
                seen.add(cid)
                vc_settle(ch)
    for cid in [c for c in _vc_state if c not in seen]:
        del _vc_state[cid]
    await vc_award_all()

async def vc_xp_loop():
    await bot.wait_until_ready()
    while True:
        try:
            await vc_xp_tick()
        except Exception as e:
            print(f"[VC-XP] tick failed: {e}")
        await asyncio.sleep(VC_TICK)

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        vc_on_voice_state(member, before, after)
    except Exception as e:
        print(f"[VC-XP] state update failed: {e}")
    if member.bot or before.channel == after.channel:
        return
    try:
        await _log_voice(member, before, after)
    except Exception as e:
        print(f"[LOG] voice log failed: {e}")

# ---------- which channels give XP ----------
def vc_valid_channel(guild, cid):
    ch = guild.get_channel(int(cid))
    return ch if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)) else None

def vc_all_voice_ids(guild):
    afk = guild.afk_channel.id if guild.afk_channel else None
    return [c.id for c in list(guild.voice_channels) + list(guild.stage_channels) if c.id != afk]

def vc_add_channels(guild, ids):
    """Add voice / stage channels to the list (unknown ids are ignored). Returns how many were new."""
    s = get_settings(guild.id)
    cur = [str(x) for x in s.get("vc_channels", [])]
    added = 0
    for cid in ids:
        if len(cur) >= VC_MAX_CHANNELS:
            break
        if str(cid) not in cur and vc_valid_channel(guild, cid) is not None:
            cur.append(str(cid))
            added += 1
    s["vc_channels"] = cur
    save_settings()
    return added

def vc_remove_channels(guild, ids):
    s = get_settings(guild.id)
    cur = [str(x) for x in s.get("vc_channels", [])]
    drop = {str(x) for x in ids}
    s["vc_channels"] = [c for c in cur if c not in drop]
    save_settings()
    return len(cur) - len(s["vc_channels"])

def vc_panel_embed(guild):
    s = settings_db.get(str(guild.id), {})
    ids = vc_channel_ids(guild.id)
    shown = "\n".join(f"• <#{c}>" for c in ids[:25])
    if len(ids) > 25:
        shown += "\n" + L("...and {} more", len(ids) - 25)
    e = discord.Embed(title=L("🎙️ Voice XP Channels"), color=0x5865F2, description=shown or L("No voice channels chosen yet - nobody earns voice XP."))
    if not (_feature_on(s, "vcxp") and _feature_on(s, "leveling")):
        e.add_field(name=L("📌 Status"), value=L("⚠️ Voice XP is not active yet: switch on **Voice XP** (and Leveling) with /setup feature."), inline=False)
    e.add_field(name=L("💡 Tip"), value=L("Set an Inactive channel in Server Settings: Discord moves idle members there and nobody earns XP in it."), inline=False)
    return e

class VCPanel(BaseView):
    def __init__(self, guild, user_id):
        super().__init__(timeout=300)
        self.guild, self.user_id = guild, user_id
        self.add_menu = discord.ui.ChannelSelect(placeholder=L("➕ Add voice channels..."), channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
                                                 min_values=1, max_values=25, row=0)
        self.add_menu.callback = self._add
        self.add_item(self.add_menu)
        ids = vc_channel_ids(guild.id)
        if ids:
            opts = [discord.SelectOption(label=(guild.get_channel(c).name if guild.get_channel(c) else f"#{c}")[:100], value=str(c), emoji="🎙️") for c in ids[:25]]
            self.rem_menu = discord.ui.Select(placeholder=L("➖ Remove channels..."), min_values=1, max_values=len(opts), options=opts, row=1)
            self.rem_menu.callback = self._remove
            self.add_item(self.rem_menu)
        self.all_btn.label, self.clear_btn.label = L("➕ All voice channels"), L("🗑️ Clear list")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id or not (interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction, note):
        self.stop()
        await interaction.response.edit_message(content=note, embed=vc_panel_embed(self.guild), view=VCPanel(self.guild, self.user_id))

    async def _add(self, interaction: discord.Interaction):
        await self._refresh(interaction, L("✅ Added {} channels.", vc_add_channels(self.guild, [c.id for c in self.add_menu.values])))

    async def _remove(self, interaction: discord.Interaction):
        await self._refresh(interaction, L("✅ Removed {} channels.", vc_remove_channels(self.guild, self.rem_menu.values)))

    @discord.ui.button(label="All", style=discord.ButtonStyle.primary, row=2)
    async def all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh(interaction, L("✅ Added {} channels.", vc_add_channels(self.guild, vc_all_voice_ids(self.guild))))

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, row=2)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh(interaction, L("✅ Removed {} channels.", vc_remove_channels(self.guild, vc_channel_ids(self.guild.id))))

@setup_group.command(name="vc", description="Choose which voice channels give XP (as many as you like)")
async def setup_vc(interaction: discord.Interaction):
    if await _deny_unless_manager(interaction):
        return
    await interaction.response.send_message(embed=vc_panel_embed(interaction.guild), view=VCPanel(interaction.guild, interaction.user.id), ephemeral=True)

@setup_group.command(name="vcxpdiff", description="Set how fast voice XP is earned")
@app_commands.describe(difficulty="Voice XP difficulty")
@app_commands.choices(difficulty=[app_commands.Choice(name=v["label"], value=k) for k, v in VC_DIFFICULTIES.items()])
async def setup_vcxpdiff(interaction: discord.Interaction, difficulty: str):
    if await _deny_unless_manager(interaction):
        return
    s = get_settings(interaction.guild.id)
    s["vcxpdiff"] = difficulty
    save_settings()
    cfg = vc_config(interaction.guild.id)
    await interaction.response.send_message(embed=discord.Embed(color=0x57F287, description=L("✅ Voice XP difficulty: **{}**\nXP per minute: **{}**, daily limit: **{}** XP ({} hours)",
                                                                                            L(cfg["label"]), cfg["rate"], f"{cfg['cap']:,}", VC_DAILY_MINUTES // 60)))

# ---------- what members see: how it works + privacy + their own progress ----------
def vc_info_embed(guild, member):
    s = settings_db.get(str(guild.id), {})
    cfg = vc_config(guild.id)
    on = _feature_on(s, "vcxp") and _feature_on(s, "leveling")
    ids = vc_channel_ids(guild.id)
    row = levels_db.get(str(guild.id), {}).get(str(member.id), {})
    used = row.get("vc_xp", 0) if row.get("vc_day") == vc_today() else 0
    e = discord.Embed(title=L("🎙️ Voice XP"), color=0x5865F2 if on else 0x808080,
                      description=L("You earn XP while you are in a chosen voice channel with your **microphone and headphones on**, and at least **2 people in total** (you included) have theirs on.\nNo XP while you are muted or deafened (by yourself or a moderator), in the AFK channel, timed out, set to `.afk`, or only listening in a stage.\nTime is counted to the second. The limit is **{}** hours of voice XP per day.", VC_DAILY_MINUTES // 60))
    e.add_field(name=L("📌 Status"), value=L("✅ On") if on else L("❌ Off"), inline=True)
    e.add_field(name=L("🎙️ Voice XP Difficulty"), value=L("{}\n{} XP per minute, up to {} XP a day", L(cfg["label"]), cfg["rate"], f"{cfg['cap']:,}"), inline=True)
    if ids:
        chans = " ".join(f"<#{c}>" for c in ids[:8])
        if len(ids) > 8:
            chans += " " + L("...and {} more", len(ids) - 8)
    else:
        chans = L("None yet - an admin must use /setup vc")
    e.add_field(name=L("🎙️ Voice XP Channels"), value=chans, inline=False)
    e.add_field(name=L("📅 Your voice XP today"), value=f"**{used:,}** / {cfg['cap']:,}", inline=False)
    e.add_field(name=L("🔒 Privacy"), value=L("Versa never joins voice channels and never hears or records anything. It only reads what Discord tells every bot: which channel you are in and whether your mic or headphones are off. The only thing it stores is your voice XP total of today (for the daily limit)."), inline=False)
    return e

@bot.command(name="vcxp")
async def vcxp_p(ctx):
    await ctx.send(embed=vc_info_embed(ctx.guild, ctx.author))

@bot.tree.command(name="vcxp", description="How voice XP works, your progress today and what the bot can see")
@app_commands.guild_only()
async def vcxp_s(interaction: discord.Interaction):
    await interaction.response.send_message(embed=vc_info_embed(interaction.guild, interaction.user))



# ============================================================
# TOP.GG / DISCORD COMPLIANCE HELPERS + MESSAGE COUNTS FOR /rank
# ============================================================
bot_bans_db.setdefault("dm_optout", [])

def dm_is_off(user_id):
    return str(user_id) in bot_bans_db.get("dm_optout", [])

def dm_optout_set(user_id, off):
    lst = bot_bans_db.setdefault("dm_optout", [])
    uid = str(user_id)
    if off and uid not in lst:
        lst.append(uid)
    elif not off and uid in lst:
        lst.remove(uid)
    save_bot_bans()
    return off

async def send_dm(user, *, embed=None, content=None, essential=False, file=None, guild=None, notify=None):
    """The bot never starts a DM on its own. A DM goes out only when the person who ran the action asked for it (notify=True),
    or the server admin switched on 'Moderation DMs' in /setup feature (guild=...). `/dms off` always wins. Returns False when nothing was sent."""
    if not essential:
        want = notify if notify is not None else bool(guild is not None and is_feature_enabled(guild.id, "dmnotices"))
        if not want or dm_is_off(user.id):
            return False
    if embed is not None and not (embed.footer and embed.footer.text):
        embed.set_footer(text=L("Sent by Versa for the server's staff (anonymous). Stop these DMs: /dms off"))
    await user.send(content=content, embed=embed, file=file)
    return True

def dms_reply(off):
    if off:
        return L("⛔ DMs from Versa are **off**. You will no longer get moderation notices or ticket updates by DM.")
    return L("✅ DMs from Versa are **on**.")

@bot.tree.command(name="dms", description="Turn DMs from Versa (moderation notices, ticket updates) on or off")
@app_commands.describe(mode="Receive DMs from Versa?")
@app_commands.choices(mode=[app_commands.Choice(name="✅ On", value="on"), app_commands.Choice(name="⛔ Off", value="off")])
async def dms_s(interaction: discord.Interaction, mode: str):
    await interaction.response.send_message(dms_reply(dm_optout_set(interaction.user.id, mode == "off")), ephemeral=True)

@bot.command(name="dms")
async def dms_p(ctx, mode: str = None):
    pfx = settings_db.get(str(ctx.guild.id), {}).get("prefix", ".")
    if mode is None or mode.lower() not in ("on", "off"):
        await ctx.send(L("📬 DMs from Versa: {}\nChange it with `/dms` or `{}dms on` / `{}dms off`.", L("❌ Off") if dm_is_off(ctx.author.id) else L("✅ On"), pfx, pfx), delete_after=15)
        return
    await ctx.send(dms_reply(dm_optout_set(ctx.author.id, mode.lower() == "off")), delete_after=15)

# ---------- the "all commands" help page is built from the live command tables, so it can never be out of date ----------
def build_all_commands_text(pfx):
    prefix_cmds = sorted((c.name for c in bot.commands if not getattr(c, "hidden", False)))
    top = list(bot.tree.get_commands())
    slash = sorted(c.name for c in top if isinstance(c, app_commands.Command))
    groups = sorted((c for c in top if isinstance(c, app_commands.Group)), key=lambda c: c.name)
    out = [L("**Prefix commands**") + f" ({pfx})", " ".join(f"`{pfx}{n}`" for n in prefix_cmds), "", L("**Slash commands**"), " ".join(f"`/{n}`" for n in slash)]
    for g in groups:
        out += ["", f"**/{g.name}**: " + " ".join(f"`{c.name}`" for c in sorted(g.commands, key=lambda c: c.name))]
    return "\n".join(out)[:4000]

# ---------- message counts: today / last 7 days / last 30 days / total (UTC days), shown by /rank ----------
MSG_KEEP_DAYS = 30

def _msg_day():
    return int(_time.time() // 86400)

def counts_as_message(message):
    """Only real chat messages count (not joins, boosts, pins or other system messages)."""
    return getattr(message, "type", None) in (discord.MessageType.default, discord.MessageType.reply)

def count_message(guild_id, user_id):
    gid, uid, today = str(guild_id), str(user_id), _msg_day()
    row = msgstats_db.setdefault(gid, {}).setdefault(uid, {"t": 0, "d": {}})
    row["t"] += 1
    days, key = row["d"], str(today)
    if key not in days:
        for k in [k for k in days if int(k) <= today - MSG_KEEP_DAYS]:
            del days[k]
    days[key] = days.get(key, 0) + 1
    touch("msgstats", gid, uid)
    s = settings_db.get(gid)
    if s is None or "msgcount_since" not in s:
        get_settings(guild_id)["msgcount_since"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_settings()

def msg_counts(guild_id, user_id):
    row = msgstats_db.get(str(guild_id), {}).get(str(user_id))
    if not row:
        return {"today": 0, "week": 0, "month": 0, "total": 0}
    today, days = _msg_day(), row.get("d", {})
    def span(n):
        return sum(c for k, c in days.items() if today - n < int(k) <= today)
    return {"today": span(1), "week": span(7), "month": span(30), "total": row.get("t", 0)}

def msg_stats_text(guild_id, user_id):
    c = msg_counts(guild_id, user_id)
    return L("📅 Today: **{}**\n🗓️ Last 7 days: **{}**\n📆 Last 30 days: **{}**\n💬 Total: **{}**", f"{c['today']:,}", f"{c['week']:,}", f"{c['month']:,}", f"{c['total']:,}")

def msg_stats_footer(guild_id):
    since = settings_db.get(str(guild_id), {}).get("msgcount_since")
    return L("Messages counted since {} · days change at 00:00 UTC", since) if since else None



# ============================================================
# V2: DM POLICY FLAGS, TICKET FIXES + /ticket add|remove, LOG PANEL (27 events)
# ============================================================
from typing import Union as _Union

# ---------- DMs: nothing is sent unless the person running the action asks for it ----------
_DM_FLAGS = {"-dm": True, "--dm": True, "+dm": True, "-nodm": False, "--nodm": False}

def strip_dm_flag(text):
    """'-dm' anywhere in a moderation command's free text = also tell the person by DM; '-nodm' = stay silent.
    Returns (text without the flag, True / False / None)."""
    if not text:
        return text, None
    flag, keep = None, []
    for w in str(text).split():
        if w.lower() in _DM_FLAGS:
            flag = _DM_FLAGS[w.lower()]
        else:
            keep.append(w)
    return " ".join(keep), flag

def mod_args(duration, reason, default=None):
    """Splits the optional -dm / -nodm flag out of a (duration, reason) pair. Returns (duration, reason, notify)."""
    d, f1 = strip_dm_flag(duration)
    r, f2 = strip_dm_flag(reason)
    if f1 is not None and not d and r:                        # '-dm 5m reason': the real duration is the first word of the reason
        first, _, rest = r.partition(" ")
        if parse_duration(first)[0]:
            d, r = first, rest
    return (d or default), (r or "No reason"), (f2 if f2 is not None else f1)

# ---------- tickets: emoji validation, repair of saved buttons, /ticket add|remove ----------
_EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|(?:[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u24C2\u25A0-\u25FF\u2600-\u27BF\u2900-\u297F\u2B00-\u2BFF\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u2122\u2139][\uFE0F\U0001F3FB-\U0001F3FF]?)"
    "(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF][\uFE0F\U0001F3FB-\U0001F3FF]?)*)")

def clean_button_emoji(raw):
    """A usable emoji for a ticket button, or None when the text is not a real emoji (that used to break the editor)."""
    raw = raw.strip() if isinstance(raw, str) else ""
    if not raw:
        return None
    m = re.fullmatch(r"<a?:\w{2,32}:(\d{15,25})>", raw)
    if m:
        return raw if bot.get_emoji(int(m.group(1))) else None
    return raw if _EMOJI_RE.fullmatch(raw) else None

def heal_ticket_pool(guild_id):
    """Buttons saved before the emoji check may hold plain text instead of an emoji: repair them once."""
    s = settings_db.get(str(guild_id))
    pool = s.get("ticket_buttons") if s else None
    if not pool:
        return
    changed = False
    for b in pool:
        if clean_button_emoji(b.get("emoji")) is None:
            old = (b.get("emoji") or "").strip()
            lab = b.get("label", "") or b.get("category", "")
            rest = lab[len(old):].lstrip() if old and lab.startswith(old) else lab
            b["emoji"], b["label"], changed = "🎫", f"🎫 {rest}".strip(), True
    if changed:
        save_settings()

def _ticket_owner_id(channel):
    topic = getattr(channel, "topic", None) or ""
    if topic.startswith("ticket:"):
        tail = topic[7:].split()
        return int(tail[0]) if tail and tail[0].isdigit() else None
    return None

def _is_ticket_staff(member, guild):
    p = member.guild_permissions
    staff_id = get_settings(guild.id).get("ticketstaff")
    return bool(p.administrator or p.manage_channels or (staff_id and any(str(r.id) == str(staff_id) for r in member.roles)))

ticket_group = app_commands.Group(name="ticket", description="Manage the ticket you are in", guild_only=True)
bot.tree.add_command(ticket_group)

async def _ticket_gate(interaction):
    """Shared checks for /ticket add and /ticket remove: a ticket channel, ticket staff, and the bot may edit permissions."""
    ch = interaction.channel
    if _ticket_owner_id(ch) is None:
        await interaction.response.send_message(L("❌ This is not a ticket channel!"), ephemeral=True)
        return None
    if not _is_ticket_staff(interaction.user, interaction.guild):
        await interaction.response.send_message(L("❌ Only ticket staff can do this!"), ephemeral=True)
        return None
    if not interaction.guild.me.guild_permissions.manage_roles:
        await interaction.response.send_message(L("❌ I need the **{}** permission first.", "Manage Roles"), ephemeral=True)
        return None
    return ch

@ticket_group.command(name="add", description="Add a person or a role to this ticket so they can see it")
@app_commands.describe(target="The member or role to add, for example a higher moderator")
async def ticket_add(interaction: discord.Interaction, target: _Union[discord.Member, discord.Role]):
    ch = await _ticket_gate(interaction)
    if ch is None:
        return
    if isinstance(target, discord.Member) and target.bot:
        await interaction.response.send_message(L("❌ You cannot add a bot!"), ephemeral=True)
        return
    if not isinstance(target, (discord.Member, discord.Role)) or (isinstance(target, discord.Role) and target.is_default()):
        await interaction.response.send_message(L("❌ Invalid argument!"), ephemeral=True)
        return
    already = ch.permissions_for(target).view_channel if isinstance(target, discord.Member) else ch.overwrites_for(target).view_channel is True
    if already:
        await interaction.response.send_message(L("ℹ️ {} can already see this ticket.", target.mention), ephemeral=True)
        return
    try:
        await ch.set_permissions(target, overwrite=discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True), reason=f"Added to the ticket by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(L("❌ I don't have permission to do that!"), ephemeral=True)
        return
    await interaction.response.send_message(embed=discord.Embed(description=L("➕ {} was added to this ticket by {}.", target.mention, interaction.user.mention), color=0x57F287),
                                            allowed_mentions=discord.AllowedMentions(users=True, roles=True))

@ticket_group.command(name="remove", description="Remove a person or role that was added to this ticket")
@app_commands.describe(target="The member or role to remove")
async def ticket_remove(interaction: discord.Interaction, target: _Union[discord.Member, discord.Role]):
    ch = await _ticket_gate(interaction)
    if ch is None:
        return
    staff_id = get_settings(interaction.guild.id).get("ticketstaff")
    if isinstance(target, discord.Member) and target.id == _ticket_owner_id(ch):
        await interaction.response.send_message(L("❌ You cannot remove the ticket owner!"), ephemeral=True)
        return
    if isinstance(target, discord.Role) and staff_id and str(target.id) == str(staff_id):
        await interaction.response.send_message(L("❌ You cannot remove the ticket staff role!"), ephemeral=True)
        return
    if target not in ch.overwrites:
        await interaction.response.send_message(L("ℹ️ {} was not added to this ticket.", target.mention), ephemeral=True)
        return
    try:
        await ch.set_permissions(target, overwrite=None, reason=f"Removed from the ticket by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(L("❌ I don't have permission to do that!"), ephemeral=True)
        return
    await interaction.response.send_message(embed=discord.Embed(description=L("➖ {} was removed from this ticket by {}.", target.mention, interaction.user.mention), color=0xFEE75C),
                                            allowed_mentions=discord.AllowedMentions.none())

# ---------- logs: 27 events in 6 categories, switched with a click ----------
LOG_DEFAULT_OFF = {"voice_join", "voice_leave", "voice_move", "invite_create", "invite_delete", "thread_create", "thread_delete"}

def log_on(guild_id, key):
    """Is this kind of log switched on? (read-only; most events default to on, the noisy ones to off)"""
    return settings_db.get(str(guild_id), {}).get("log_settings", {}).get(key, key not in LOG_DEFAULT_OFF)

def log_categories():
    """[(category key, label, [(event key, label)...])...] - labels are translated when this is called."""
    return [
        ("messages", L("💬 Messages"), [("message_delete", L("Message deleted")), ("message_edit", L("Message edited")), ("message_bulk", L("Bulk delete"))]),
        ("members", L("👥 Members"), [("member_join", L("Member joined")), ("member_leave", L("Member left")), ("member_nick", L("Nickname changed")),
                                      ("member_role", L("Roles changed")), ("member_timeout", L("Timeout")), ("member_boost", L("Server boost"))]),
        ("moderation", L("🔨 Moderation"), [("member_ban", L("Member banned")), ("member_unban", L("Member unbanned")), ("mod_cases", L("Mod cases (warn, kick, mute...)"))]),
        ("structure", L("🧩 Roles & channels"), [("role_create", L("Role created")), ("role_update", L("Role edited")), ("role_delete", L("Role deleted")),
                                                 ("channel_create", L("Channel created")), ("channel_update", L("Channel edited")), ("channel_delete", L("Channel deleted")),
                                                 ("thread_create", L("Thread created")), ("thread_delete", L("Thread deleted"))]),
        ("voice", L("🔊 Voice"), [("voice_join", L("Joined voice")), ("voice_leave", L("Left voice")), ("voice_move", L("Moved voice"))]),
        ("server", L("🏠 Server"), [("server_update", L("Server edited")), ("emoji_update", L("Emoji changes")), ("invite_create", L("Invite created")), ("invite_delete", L("Invite deleted"))]),
    ]

class LogPanel(BaseView):
    def __init__(self, guild, user_id, cat="messages"):
        super().__init__(timeout=300)
        self.guild, self.user_id, self.cat = guild, user_id, cat
        cats = log_categories()
        self.menu = discord.ui.Select(placeholder=L("Choose a category"), row=0, options=[discord.SelectOption(label=lab[:100], value=k, default=(k == cat)) for k, lab, _ in cats])
        self.menu.callback = self._pick
        self.add_item(self.menu)
        events = next((evs for k, _l, evs in cats if k == cat), cats[0][2])
        for i, (key, label) in enumerate(events[:15]):
            on = log_on(guild.id, key)
            btn = discord.ui.Button(label=f"{'✓' if on else '✕'} {label}"[:80], style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary, row=1 + i // 5)
            btn.callback = self._toggle_cb(key)
            self.add_item(btn)
        self.cat_on.label, self.cat_off.label = L("✓ All in category"), L("✕ None in category")
        self.all_on.label, self.all_off.label, self.close_btn.label = L("✓ Everything"), L("✕ Nothing"), L("Close")

    def _cat_keys(self):
        return [key for k, _l, evs in log_categories() if k == self.cat for key, _lab in evs]

    def _all_keys(self):
        return [key for _k, _l, evs in log_categories() for key, _lab in evs]

    def _set(self, keys, value):
        cfg = get_settings(self.guild.id).setdefault("log_settings", {})
        for key in keys:
            cfg[key] = value
        save_settings()

    def make_embed(self):
        s = settings_db.get(str(self.guild.id), {})
        ch = self.guild.get_channel(int(s["log"])) if s.get("log") else None
        cats = log_categories()
        enabled = sum(1 for _k, _l, evs in cats for key, _lab in evs if log_on(self.guild.id, key))
        total = sum(len(evs) for _k, _l, evs in cats)
        head = L("Log channel: {}", ch.mention) if ch else L("⚠️ No log channel yet. Set one with `/setup log`.")
        e = discord.Embed(title=L("📜 Log settings"), color=0x5865F2, description=f"{head}\n" + L("Enabled: **{}** / **{}**", enabled, total) + "\n" + L("Click a button to turn that log on or off."))
        for k, lab, evs in cats:
            e.add_field(name=lab + (" ◀" if k == self.cat else ""), value=" · ".join(f"{'✓' if log_on(self.guild.id, key) else '✕'} {l}" for key, l in evs)[:1000], inline=False)
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(L("❌ No permission!"), ephemeral=True)
            return False
        return True

    async def _redraw(self, interaction):
        self.stop()
        new = LogPanel(self.guild, self.user_id, self.cat)
        await interaction.response.edit_message(embed=new.make_embed(), view=new)

    async def _pick(self, interaction: discord.Interaction):
        self.cat = self.menu.values[0]
        await self._redraw(interaction)

    def _toggle_cb(self, key):
        async def cb(interaction: discord.Interaction):
            self._set([key], not log_on(self.guild.id, key))
            await self._redraw(interaction)
        return cb

    @discord.ui.button(label="All in category", style=discord.ButtonStyle.primary, row=4)
    async def cat_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set(self._cat_keys(), True)
        await self._redraw(interaction)

    @discord.ui.button(label="None in category", style=discord.ButtonStyle.secondary, row=4)
    async def cat_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set(self._cat_keys(), False)
        await self._redraw(interaction)

    @discord.ui.button(label="Everything", style=discord.ButtonStyle.primary, row=4)
    async def all_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set(self._all_keys(), True)
        await self._redraw(interaction)

    @discord.ui.button(label="Nothing", style=discord.ButtonStyle.secondary, row=4)
    async def all_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set(self._all_keys(), False)
        await self._redraw(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, row=4)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=L("✅ Log settings saved."), embed=None, view=None)

@setup_group.command(name="logsettings", description="Open the log panel: switch each kind of log on or off with a click")
async def setup_logsettings(interaction: discord.Interaction):
    if await _deny_unless_manager(interaction):
        return
    panel = LogPanel(interaction.guild, interaction.user.id)
    await interaction.response.send_message(embed=panel.make_embed(), view=panel, ephemeral=True)

# ---- listeners for the new events ----
async def _log_voice(member, before, after):
    g = member.guild
    set_lang(g.id)
    if before.channel is None:
        key, text, color = "voice_join", L("{} joined {}", member.mention, after.channel.mention), 0x57F287
    elif after.channel is None:
        key, text, color = "voice_leave", L("{} left {}", member.mention, before.channel.mention), 0x808080
    else:
        key, text, color = "voice_move", L("{} moved from {} to {}", member.mention, before.channel.mention, after.channel.mention), 0x5865F2
    if not log_on(g.id, key):
        return
    e = discord.Embed(title=L("🔊 Voice Activity"), description=text, color=color, timestamp=datetime.now(timezone.utc))
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    await send_log(g, e)

async def _log_member_extra(before, after):
    g = after.guild
    bt, at = getattr(before, "timed_out_until", None), getattr(after, "timed_out_until", None)
    if bt != at and log_on(g.id, "member_timeout"):
        set_lang(g.id)
        actor = await _audit_actor(g, discord.AuditLogAction.member_update)
        if not (actor and actor.id == bot.user.id):                 # the bot's own timeouts are already logged as cases
            if at and at > datetime.now(timezone.utc):
                e = discord.Embed(title=L("⏱️ Member Timed Out"), color=0xFEE75C, timestamp=datetime.now(timezone.utc))
                e.add_field(name=L("Until"), value=dts(at, "R"), inline=True)
            else:
                e = discord.Embed(title=L("✅ Timeout Removed"), color=0x57F287, timestamp=datetime.now(timezone.utc))
            e.set_author(name=str(after), icon_url=after.display_avatar.url)
            e.add_field(name=L("User"), value=f"{after.mention} (`{after.id}`)", inline=True)
            if actor:
                e.add_field(name=L("By"), value=actor.mention, inline=True)
            await send_log(g, e)
    if before.premium_since != after.premium_since and log_on(g.id, "member_boost"):
        set_lang(g.id)
        text = L("{} started boosting the server", after.mention) if after.premium_since else L("{} stopped boosting the server", after.mention)
        await send_log(g, discord.Embed(title=L("💜 Server Boost"), description=text, color=0xF47FFF, timestamp=datetime.now(timezone.utc)))

@bot.event
async def on_guild_channel_update(before, after):
    g = after.guild
    if not log_on(g.id, "channel_update"):
        return
    set_lang(g.id)
    changes = []
    if before.name != after.name:
        changes.append(L("**Name:** {} → {}", before.name, after.name))
    if getattr(before, "topic", None) != getattr(after, "topic", None):
        changes.append(L("**Topic changed**"))
    if getattr(before, "slowmode_delay", 0) != getattr(after, "slowmode_delay", 0):
        changes.append(L("**Slowmode:** {}s → {}s", getattr(before, "slowmode_delay", 0), getattr(after, "slowmode_delay", 0)))
    if getattr(before, "nsfw", False) != getattr(after, "nsfw", False):
        changes.append(L("**NSFW:** {} → {}", getattr(before, "nsfw", False), getattr(after, "nsfw", False)))
    if before.overwrites != after.overwrites and g.id not in _mass_busy:        # mass lock / lockdown would flood the log
        changes.append(L("**Permissions changed**"))
    if changes:
        await send_log(g, discord.Embed(title=L("✏️ Channel Edited"), description=f"{after.mention}\n" + "\n".join(changes), color=0xFEE75C, timestamp=datetime.now(timezone.utc)))

@bot.event
async def on_guild_role_update(before, after):
    g = after.guild
    if not log_on(g.id, "role_update"):
        return
    set_lang(g.id)
    changes = []
    if before.name != after.name:
        changes.append(L("**Name:** {} → {}", before.name, after.name))
    if before.color != after.color:
        changes.append(L("**Color changed**"))
    if before.permissions != after.permissions:
        changes.append(L("**Permissions changed**"))
    if before.hoist != after.hoist:
        changes.append(L("**Hoisted:** {} → {}", before.hoist, after.hoist))
    if before.mentionable != after.mentionable:
        changes.append(L("**Mentionable:** {} → {}", before.mentionable, after.mentionable))
    if changes:
        await send_log(g, discord.Embed(title=L("🎭 Role Edited"), description=f"{after.mention}\n" + "\n".join(changes), color=0xFEE75C, timestamp=datetime.now(timezone.utc)))

@bot.event
async def on_guild_emojis_update(guild, before, after):
    if not log_on(guild.id, "emoji_update"):
        return
    set_lang(guild.id)
    b, a = {e.id: e for e in before}, {e.id: e for e in after}
    added, removed = [e for i, e in a.items() if i not in b], [e for i, e in b.items() if i not in a]
    renamed = [(b[i], e) for i, e in a.items() if i in b and b[i].name != e.name]
    if not (added or removed or renamed):
        return
    e = discord.Embed(title=L("🖼️ Emoji Changes"), color=0xFEE75C, timestamp=datetime.now(timezone.utc))
    if added:
        e.add_field(name=L("Added"), value=" ".join(str(x) for x in added)[:1000], inline=False)
    if removed:
        e.add_field(name=L("Removed"), value=", ".join(f"`{x.name}`" for x in removed)[:1000], inline=False)
    if renamed:
        e.add_field(name=L("Renamed"), value="\n".join(f"`{o.name}` → `{n.name}`" for o, n in renamed)[:1000], inline=False)
    await send_log(guild, e)

def _invite_guild(invite):
    g = invite.guild
    return g if isinstance(g, discord.Guild) else bot.get_guild(getattr(g, "id", 0))

@bot.event
async def on_invite_create(invite):
    g = _invite_guild(invite)
    if g is None or not log_on(g.id, "invite_create"):
        return
    set_lang(g.id)
    e = discord.Embed(title=L("🔗 Invite Created"), color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name=L("Code"), value=f"`{invite.code}`", inline=True)
    if invite.channel:
        e.add_field(name=L("Channel"), value=getattr(invite.channel, "mention", f"`{invite.channel}`"), inline=True)
    if invite.inviter:
        e.add_field(name=L("By"), value=invite.inviter.mention, inline=True)
    e.add_field(name=L("Max uses"), value=str(invite.max_uses or "∞"), inline=True)
    e.add_field(name=L("Expires"), value=dts(invite.expires_at, "R") if invite.expires_at else "∞", inline=True)
    await send_log(g, e)

@bot.event
async def on_invite_delete(invite):
    g = _invite_guild(invite)
    if g is None or not log_on(g.id, "invite_delete"):
        return
    set_lang(g.id)
    e = discord.Embed(title=L("🔗 Invite Deleted"), color=0xED4245, timestamp=datetime.now(timezone.utc))
    e.add_field(name=L("Code"), value=f"`{invite.code}`", inline=True)
    if invite.channel:
        e.add_field(name=L("Channel"), value=getattr(invite.channel, "mention", f"`{invite.channel}`"), inline=True)
    await send_log(g, e)

@bot.event
async def on_thread_create(thread):
    g = thread.guild
    if not log_on(g.id, "thread_create"):
        return
    set_lang(g.id)
    e = discord.Embed(title=L("🧵 Thread Created"), description=f"{thread.mention} (`{thread.id}`)", color=0x57F287, timestamp=datetime.now(timezone.utc))
    if thread.parent:
        e.add_field(name=L("Parent"), value=thread.parent.mention, inline=True)
    if thread.owner_id:
        e.add_field(name=L("By"), value=f"<@{thread.owner_id}>", inline=True)
    await send_log(g, e)

@bot.event
async def on_thread_delete(thread):
    g = thread.guild
    if not log_on(g.id, "thread_delete"):
        return
    set_lang(g.id)
    e = discord.Embed(title=L("🧵 Thread Deleted"), description=f"`{thread.name}` (`{thread.id}`)", color=0xED4245, timestamp=datetime.now(timezone.utc))
    if thread.parent:
        e.add_field(name=L("Parent"), value=thread.parent.mention, inline=True)
    await send_log(g, e)



# ============================================================
# VISUAL SUITE - animated slots / coin, moderation banners, rank / level-up / leaderboard cards.
# Pillow is OPTIONAL: when it is missing (or anything fails) every command falls back to its plain embed.
# ============================================================
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
_SLOT_SYMBOLS = [s[0] for s in SLOT_SYMBOLS]          # same symbols and weights as the real paytable
_SLOT_WEIGHTS = [s[1] for s in SLOT_SYMBOLS]
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

# ---------------- playing cards (own drawing: suits are polygons and circles, no font glyphs) ----------------
CARD_SUITS = ["♠️", "♥️", "♦️", "♣️"]
_SUIT_KEY = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
_CARD_RED, _CARD_INK = (204, 30, 52), (26, 26, 36)
_CARD_BRAND, _CARD_GOLD = (63, 50, 150), (236, 186, 64)

def _suit_shape(d, suit, cx, cy, size, col):
    """Draw one suit symbol with its centre at (cx, cy); size is the full height in pixels."""
    r = size / 2
    if suit == "d":
        d.polygon([(cx, cy - r), (cx + r * 0.74, cy), (cx, cy + r), (cx - r * 0.74, cy)], fill=col)
    elif suit == "h":
        q = r * 0.52
        for sx in (-1, 1):
            d.ellipse((cx + sx * r * 0.47 - q, cy - r * 0.38 - q, cx + sx * r * 0.47 + q, cy - r * 0.38 + q), fill=col)
        d.polygon([(cx - r * 0.97, cy - r * 0.22), (cx + r * 0.97, cy - r * 0.22), (cx, cy + r * 0.98)], fill=col)
    elif suit == "s":
        q = r * 0.5
        for sx in (-1, 1):
            d.ellipse((cx + sx * r * 0.45 - q, cy + r * 0.12 - q, cx + sx * r * 0.45 + q, cy + r * 0.12 + q), fill=col)
        d.polygon([(cx - r * 0.95, cy + r * 0.02), (cx + r * 0.95, cy + r * 0.02), (cx, cy - r * 0.98)], fill=col)
        d.polygon([(cx, cy + r * 0.15), (cx - r * 0.34, cy + r), (cx + r * 0.34, cy + r)], fill=col)
    else:
        q = r * 0.31
        for ox, oy in ((0, -0.42), (-0.44, 0.1), (0.44, 0.1)):
            d.ellipse((cx + ox * r - q, cy + oy * r - q, cx + ox * r + q, cy + oy * r + q), fill=col)
        d.ellipse((cx - q * 0.7, cy - q * 0.6, cx + q * 0.7, cy + q * 0.8), fill=col)
        d.polygon([(cx, cy), (cx - r * 0.3, cy + r), (cx + r * 0.3, cy + r)], fill=col)

def _draw_card(cv, x, y, w, h, card=None, dim=False):
    """One card on a _Cv canvas. card=None draws the Versa card back."""
    k = cv.k
    cv.rr((x + 2, y + 3, x + w + 2, y + h + 3), w * 0.09, fill=(0, 0, 0, 90))
    if card is None:
        cv.rr((x, y, x + w, y + h), w * 0.09, fill=_CARD_BRAND + (255,), outline=(240, 236, 255, 255), width=max(1.5, w / 40))
        ix0, iy0, ix1, iy1 = x + w * 0.1, y + h * 0.08, x + w * 0.9, y + h * 0.92
        cv.rr((ix0, iy0, ix1, iy1), w * 0.05, outline=_CARD_GOLD + (255,), width=max(1, w / 60))
        lw, lh = max(1, int((ix1 - ix0) * k)), max(1, int((iy1 - iy0) * k))
        tile = PI.new("RGB", (lw, lh), _CARD_BRAND)
        td, step = PD.Draw(tile), w / 6 * k
        for i in range(-14, 14):
            x0 = i * step
            td.line([(x0, 0), (x0 + lh, lh)], fill=(92, 78, 186), width=max(1, int(k)))
            td.line([(x0 + lh, 0), (x0, lh)], fill=(92, 78, 186), width=max(1, int(k)))
        cv.im.paste(tile, (int(ix0 * k), int(iy0 * k)))
        cv.rr((x, y, x + w, y + h), w * 0.09, outline=(240, 236, 255, 255), width=max(1.5, w / 40))
        cv.rr((ix0, iy0, ix1, iy1), w * 0.05, outline=_CARD_GOLD + (255,), width=max(1, w / 60))
        cv.ell((x + w / 2 - w * 0.2, y + h / 2 - w * 0.2, x + w / 2 + w * 0.2, y + h / 2 + w * 0.2), fill=_CARD_BRAND + (255,), outline=_CARD_GOLD + (255,), width=max(1, w / 60))
        cv.text((x + w / 2, y + h / 2 + 1), "V", w * 0.26, _CARD_GOLD, anchor="mm")
        return
    v, s = card[0], _SUIT_KEY.get(str(card[1])[:1], "s")
    col = _CARD_RED if s in "hd" else _CARD_INK
    cv.rr((x, y, x + w, y + h), w * 0.09, fill=(250, 248, 242, 255), outline=(196, 192, 182, 255), width=max(1, w / 60))
    fs = h * (0.16 if len(v) == 1 else 0.145)
    cv.text((x + w * 0.17, y + h * 0.13), v, fs, col, anchor="mm")
    _suit_shape(cv.d, s, (x + w * 0.17) * k, (y + h * 0.27) * k, h * 0.1 * k, col)
    cv.text((x + w * 0.83, y + h * 0.87), v, fs, col, anchor="mm")
    _suit_shape(cv.d, s, (x + w * 0.83) * k, (y + h * 0.73) * k, h * 0.1 * k, col)
    if v in ("J", "Q", "K"):
        tint = (252, 228, 230) if s in "hd" else (226, 230, 246)
        cv.rr((x + w * 0.28, y + h * 0.2, x + w * 0.72, y + h * 0.8), w * 0.05, fill=tint + (255,), outline=col + (255,), width=max(1, w / 70))
        cv.text((x + w / 2, y + h * 0.42), v, h * 0.24, col, anchor="mm")
        _suit_shape(cv.d, s, (x + w / 2) * k, (y + h * 0.64) * k, h * 0.14 * k, col)
    else:
        _suit_shape(cv.d, s, (x + w / 2) * k, (y + h / 2) * k, h * (0.44 if v == "A" else 0.34) * k, col)
    if dim:
        cv.rr((x, y, x + w, y + h), w * 0.09, fill=(0, 0, 0, 110))

def _felt(cv, W, H):
    cv.grad((0, 0, W, H), (22, 104, 70), (10, 58, 40), vertical=True, radius=22)
    cv.rr((3, 3, W - 3, H - 3), 20, outline=_CARD_GOLD + (255,), width=3)

def _cards_row(cv, cards, x, y, w, h, max_w, hidden_from=None):
    """Cards left to right, overlapping when they do not fit into max_w."""
    n = len(cards)
    step = w + 8 if n <= 1 else min(w + 8, (max_w - w) / (n - 1))
    for i, c in enumerate(cards):
        _draw_card(cv, x + i * step, y, w, h, None if (hidden_from is not None and i >= hidden_from) else c)

def render_bj_table(dealer, hide_hole, seats, labels):
    """seats: [{'name', 'hand', 'value', 'tag', 'turn', 'tone'}]; labels: {'dealer'}; tone: 'win'|'lose'|'push'|None. PNG bytes."""
    n = max(1, len(seats))
    cols = 1 if n == 1 else 2
    rows = (n + cols - 1) // cols
    W = 720
    CW, CH = (78, 109) if n == 1 else (62, 87)
    PH = CH + 64
    top = 34 + 109 + 26
    H = top + rows * (PH + 12) + 6
    cv = _Cv(W, H, k=2)
    _felt(cv, W, H)
    dv = "?" if hide_hole else str(hand_value(dealer))
    cv.text((W / 2, 22), f"{labels.get('dealer', 'Dealer')} · {dv}".upper(), 17, (255, 236, 170), anchor="mm")
    dw = min(78 + (len(dealer) - 1) * 86, W - 80)
    _cards_row(cv, dealer, (W - dw) / 2, 34, 78, 109, dw, hidden_from=1 if hide_hole else None)
    pw = (W - 16 * (cols + 1)) / cols
    for i, s in enumerate(seats):
        cx0 = 16 + (i % cols) * (pw + 16)
        cy0 = top + (i // cols) * (PH + 12)
        tone = s.get("tone")
        edge = (255, 214, 90) if s.get("turn") else (87, 242, 135) if tone == "win" else (237, 66, 69) if tone == "lose" else (160, 200, 180)
        cv.rr((cx0, cy0, cx0 + pw, cy0 + PH), 14, fill=(0, 0, 0, 70), outline=edge + (255,), width=3 if s.get("turn") or tone else 1.5)
        name = cv.safe(s.get("name", "?"), 16, pw - 110)
        cv.text((cx0 + 14, cy0 + 18), name, 16, (255, 255, 255), anchor="lm")
        badge = str(s.get("value", ""))
        bw = cv.width(badge, 15) + 18
        cv.rr((cx0 + pw - bw - 10, cy0 + 7, cx0 + pw - 10, cy0 + 29), 11, fill=edge + (255,))
        cv.text((cx0 + pw - bw / 2 - 10, cy0 + 18), badge, 15, (20, 20, 28), anchor="mm")
        _cards_row(cv, s.get("hand", []), cx0 + 14, cy0 + 36, CW, CH, pw - 28)
        tag = s.get("tag") or ""
        if tag:
            cv.text((cx0 + pw / 2, cy0 + PH - 12), cv.safe(tag, 14, pw - 20), 14, edge, anchor="mm")
    return _fx_png(cv.out())

def render_hl(current, nxt, history, mult, amount_text, banner=None, tone=None, title="HIGHER · LOWER"):
    """Higher-Lower table: current card, the next card (face down while waiting), history strip, multiplier. PNG bytes."""
    W, H = 640, 270
    cv = _Cv(W, H, k=2)
    _felt(cv, W, H)
    _draw_card(cv, 34, 44, 136, 190, current)
    _draw_card(cv, 196, 44, 136, 190, nxt, dim=(tone == "lose"))
    cv.text((183, 139), "›", 34, (255, 236, 170), anchor="mm")
    col = (87, 242, 135) if tone == "win" else (237, 66, 69) if tone == "lose" else (255, 226, 90)
    cv.text((488, 40), cv.safe(title, 15, 250), 15, (255, 236, 170), anchor="mm")
    cv.text((488, 86), f"×{mult:,.2f}", 40, col, anchor="mm")
    cv.text((488, 126), cv.safe(amount_text, 22, 250), 22, (255, 255, 255), anchor="mm")
    hist = history[-6:]
    for i, c in enumerate(hist):
        _draw_card(cv, 370 + i * 40, 160, 36, 50, c, dim=True)
    if banner:
        cv.rr((60, 112, 306, 168), 12, fill=(16, 14, 30, 225), outline=col + (255,), width=2.5)
        cv.text((183, 140), cv.safe(banner, 24, 230), 24, col, anchor="mm")
    return _fx_png(cv.out())

# ============================================================
# V3 - store / inventory buttons, Higher-Lower, multiplayer blackjack, forceban, per-language .work, animated slots + coin
# ============================================================
def _can_attach(channel):
    """The bot may upload pictures here (a server can deny Attach Files / Embed Links per channel)."""
    try:
        p = channel.permissions_for(channel.guild.me)
        return bool(p.attach_files and p.embed_links)
    except Exception:
        return True

async def _fx_attach(embed, name, fn, *args, timeout=6.0, channel=None):
    """Render a picture in a worker thread and put it into the embed. [] when Pillow is missing, the channel does not
    allow uploads or rendering failed - the caller then shows the text version."""
    if channel is not None and not _can_attach(channel):
        return []
    try:
        data = await fx_run(fn, *args, timeout=timeout)
    except Exception:
        return []
    embed.set_image(url=f"attachment://{name}")
    return [discord.File(io.BytesIO(data), filename=name)]

def _quiet():
    return discord.AllowedMentions.none()

class BaseLayout(discord.ui.LayoutView):
    """Components-v2 twin of BaseView: same bot-ban / server-ban / language checks."""
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await BaseView.interaction_check(self, interaction)

    def disable_all(self):
        for item in self.walk_children():
            if hasattr(item, "disabled"):
                item.disabled = True

# ---------- store: a Buy button under every item; inventory: a Use button under every owned item ----------
STORE_PAGE = 6

def _item_text(guild, item, count=None):
    role = guild.get_role(int(item["role"])) if item.get("role") else None
    head = f"### {item['name']}" + (f"  ×{count}" if count else "")
    line = L("💰 **${:,}**", item["price"]) if count is None else ""
    if role:
        line = (line + " · " if line else "") + L("🎭 Role: {}", role.mention)
    desc = (item.get("description") or "").strip()
    if desc and desc != "No description":
        line = (line + "\n" if line else "") + desc
    return head + ("\n" + line if line else "")

def _store_item_by_name(gid, name):
    return next((it for it in estore_db.get(str(gid), {}).values() if it["name"].lower() == (name or "").lower()), None)

def buy_store_item(gid, uid, key):
    """(ok, message). Takes the price from the wallet and puts the item into the inventory."""
    item = estore_db.get(str(gid), {}).get(key)
    if not item:
        return False, L("❌ This item is no longer in the store.")
    econ = get_econ(gid, uid)
    if econ["wallet"] < item["price"]:
        return False, L('❌ You need **${:,}** but only have **${:,}**!', item["price"], econ["wallet"])
    econ["wallet"] -= item["price"]
    econ["inventory"].append(item["name"])          # the role is only given when the item is USED
    save_econ()
    return True, L("✅ You bought **{}** for **${:,}**. Wallet: **${:,}**", item["name"], item["price"], econ["wallet"])

async def use_store_item(guild, member, name):
    """(ok, message). Gives the item's role (if it has one) and removes one piece from the inventory."""
    inventory = get_econ(guild.id, member.id)["inventory"]
    found = next((i for i in inventory if i.lower() == (name or "").lower()), None)
    if not found:
        return False, L("❌ You don't have `{}`! Check your inventory.", name)
    data = _store_item_by_name(guild.id, found)
    role = guild.get_role(int(data["role"])) if data and data.get("role") else None
    if role:
        if not role_assignable(guild, role):
            return False, L("❌ This item's role can no longer be given (permissions or hierarchy changed). Ask an admin.")
        try:
            await member.add_roles(role, reason=f"Store item used: {found}")
        except Exception as e:
            return False, f"❌ {e}"
    inventory.remove(found)
    save_econ()
    if role:
        return True, L("✅ Used **{}** - you got {}!", found, role.mention)
    return True, L("✅ Used **{}**.", found)

async def _store_gate(interaction):
    """Feature switch + per-user restriction for store buttons (True = go on)."""
    return await slash_check_feature(interaction, "estore")

class _PagedLayout(BaseLayout):
    def __init__(self, guild, timeout=300):
        super().__init__(timeout=timeout)
        self.guild, self.page, self.message = guild, 0, None

    def _nav(self, box, pages):
        if pages <= 1:
            return
        prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.grey, disabled=self.page == 0)
        info = discord.ui.Button(label=f"{self.page + 1}/{pages}", style=discord.ButtonStyle.grey, disabled=True)
        nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.grey, disabled=self.page >= pages - 1)

        async def go(interaction, delta):
            self.page += delta
            self.build()
            await interaction.response.edit_message(view=self, allowed_mentions=_quiet())
        prev.callback = lambda i: go(i, -1)
        nxt.callback = lambda i: go(i, 1)
        box.add_item(discord.ui.ActionRow(prev, info, nxt))

    async def on_timeout(self):
        if self.message:
            self.disable_all()
            try:
                await self.message.edit(view=self, allowed_mentions=_quiet())
            except Exception:
                pass

class StoreLayout(_PagedLayout):
    def __init__(self, guild):
        super().__init__(guild)
        self.build()

    def build(self):
        self.clear_items()
        guild = self.guild
        items = list(estore_db.get(str(guild.id), {}).items())
        pages = max(1, -(-len(items) // STORE_PAGE))
        self.page = max(0, min(self.page, pages - 1))
        pfx = get_settings(guild.id).get("prefix", ".")
        box = discord.ui.Container(accent_colour=0xff6b35)
        box.add_item(discord.ui.TextDisplay(L("## 🛒 {} Store", guild.name) + "\n" + L("Press **Buy** under an item. Your items are in `{}inv`.", pfx)))
        if not items:
            box.add_item(discord.ui.TextDisplay(L('🛒 The store is empty!')))
        for key, item in items[self.page * STORE_PAGE:(self.page + 1) * STORE_PAGE]:
            box.add_item(discord.ui.Separator())
            box.add_item(discord.ui.TextDisplay(_item_text(guild, item)))
            btn = discord.ui.Button(label=L("Buy"), emoji="🛒", style=discord.ButtonStyle.green)
            btn.callback = self._buyer(key)
            box.add_item(discord.ui.ActionRow(btn))
        self._nav(box, pages)
        self.add_item(box)

    def _buyer(self, key):
        async def cb(interaction: discord.Interaction):
            if not await _store_gate(interaction):
                return
            ok, msg = buy_store_item(interaction.guild.id, interaction.user.id, key)
            await interaction.response.send_message(msg, ephemeral=True)
        return cb

class InventoryLayout(_PagedLayout):
    def __init__(self, guild, member, viewer_id):
        super().__init__(guild)
        self.member, self.owner = member, viewer_id == member.id
        self.build()

    def build(self):
        self.clear_items()
        guild, member = self.guild, self.member
        counts = list(collections.Counter(get_econ(guild.id, member.id).get("inventory", [])).items())
        pages = max(1, -(-len(counts) // STORE_PAGE))
        self.page = max(0, min(self.page, pages - 1))
        box = discord.ui.Container(accent_colour=0xff6b35)
        box.add_item(discord.ui.TextDisplay(L("## 🎒 {}'s Inventory", member.display_name)))
        if not counts:
            box.add_item(discord.ui.TextDisplay(L("*No items yet!*")))
        for name, n in counts[self.page * STORE_PAGE:(self.page + 1) * STORE_PAGE]:
            item = _store_item_by_name(guild.id, name) or {"name": name, "price": 0}
            box.add_item(discord.ui.Separator())
            box.add_item(discord.ui.TextDisplay(_item_text(guild, dict(item, name=name), count=n)))
            if self.owner:
                btn = discord.ui.Button(label=L("Use"), emoji="✨", style=discord.ButtonStyle.blurple)
                btn.callback = self._user(name)
                box.add_item(discord.ui.ActionRow(btn))
        self._nav(box, pages)
        self.add_item(box)

    def _user(self, name):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.member.id:
                await interaction.response.send_message(L("❌ This is not your inventory!"), ephemeral=True)
                return
            if not await _store_gate(interaction):
                return
            ok, msg = await use_store_item(interaction.guild, interaction.user, name)
            self.build()
            await interaction.response.edit_message(view=self, allowed_mentions=_quiet())
            await interaction.followup.send(msg, ephemeral=True)
        return cb

@bot.command(name="estore", aliases=["store", "shop"])
@feature_required("estore")
async def estore_p(ctx):
    view = StoreLayout(ctx.guild)
    view.message = await ctx.send(view=view, allowed_mentions=_quiet())

@bot.tree.command(name="estore", description="Show the economy store")
@app_commands.guild_only()
async def estore_s(interaction: discord.Interaction):
    if not await slash_check_feature(interaction, "estore"):
        return
    view = StoreLayout(interaction.guild)
    await interaction.response.send_message(view=view, allowed_mentions=_quiet())
    try:
        view.message = await interaction.original_response()
    except Exception:
        pass

@bot.command(name="buy")
@feature_required("estore")
async def buy_p(ctx, *, item_name: str = None):
    name = _clean_name(item_name)
    if not name:
        await ctx.send(L('❌ Usage: `{}`', '.buy <item name>'), delete_after=5)
        return
    key = next((k for k, it in estore_db.get(str(ctx.guild.id), {}).items() if it["name"].lower() == name.lower()), None)
    if key is None:
        await ctx.send(L('❌ Item `{}` was not found! Use the store command to see all items.', name), delete_after=8)
        return
    ok, msg = buy_store_item(ctx.guild.id, ctx.author.id, key)
    pfx = get_settings(ctx.guild.id).get("prefix", ".")
    embed = discord.Embed(description=msg, color=0x57F287 if ok else 0xED4245)
    if ok:
        embed.set_footer(text=L("Open {}inv and press Use to use it.", pfx))
    await ctx.send(embed=embed)

@bot.command(name="inv", aliases=["inventory"])
@feature_required("estore")
async def inv_p(ctx, member: discord.Member = None):
    view = InventoryLayout(ctx.guild, member or ctx.author, ctx.author.id)
    view.message = await ctx.send(view=view, allowed_mentions=_quiet())

# ---------- .work: own joke set per language (not translations - different lines for each audience) ----------
WORK_LINES = {
    "en": [
        "You held the boss's coffee through a 2-hour meeting that could have been an email.",
        "You fixed the office printer by turning it off and on again. Legend.",
        "You walked a dog. Honestly, the dog walked you.",
        "You said \"please pull forward to the window\" 214 times at a drive-thru.",
        "You stood in line for a sneaker drop for someone else.",
        "You tested mattresses for six hours. Tough job, someone had to do it.",
        "You taught your grandma how to unmute herself on a video call.",
        "You carried a couch up three floors shouting PIVOT.",
        "You approved 30 pull requests with \"LGTM\" without reading them.",
        "You were paid in exposure... and, luckily, in coins too.",
        "You built flat-pack furniture and only four screws were left over.",
        "You delivered a pizza to the wrong house and they paid anyway.",
        "You were the person who says \"you're on mute\" in every meeting.",
        "You guarded a parking spot for your friend for 40 minutes.",
        "You restarted the Wi-Fi router for the whole family. Hero.",
        "You were an extra in a movie: \"man walking past, slightly confused\".",
        "You read the terms and conditions for a client. All of them.",
        "You babysat a houseplant while its owner was on holiday.",
    ],
    "tr": [
        "İnşaatta ustanın su şişesini tuttun.",
        "Çay ocağında 47 çay demledin, 3'ü bardağa ulaştı.",
        "Düğünde takı merasimini anons ettin: \"Damadın dayısından bir çeyrek altın!\"",
        "Minibüste \"Uzatır mısın?\" zincirinin en önemli halkası oldun.",
        "Bakkal amcanın yerine 5 dakika dükkana baktın, 3 ekmek sattın.",
        "Halı sahada kimse istemediği için kaleye geçtin.",
        "Teyzenin telefonundaki 400 \"Günaydın\" mesajını sildin.",
        "Simitçinin tablasını Taksim'den Kadıköy'e taşıdın.",
        "Pazarda \"Gel abla gel, domates bunlar!\" diye bağırdın.",
        "Kahvehanede okey masasının dördüncüsü oldun.",
        "Annenin \"gelirken şunu da al\" listesini eksiksiz tamamladın.",
        "Kombinin başında usta gibi \"Bu kartı değişecek\" dedin.",
        "Kuzeninin asker uğurlama videosunu kurguladın.",
        "Komşunun arabasına park ederken \"Gel gel gel, dur!\" dedin.",
        "Kapıcı Ahmet abiye ekmekleri dağıtırken yardım ettin.",
        "Babana kumandanın pillerini değiştirdin, aile seni alkışladı.",
        "Dolmuşta şoförün yanında oturup bozuk para dağıttın.",
        "Mangalda közü yelpazeledin, eti başkası yedi.",
    ],
    "ru": [
        "Подержал бутылку воды бригадира на стройке.",
        "Простоял полдня в очереди в МФЦ за соседа.",
        "Починил бабушке интернет, выключив и включив роутер.",
        "Разгрузил «Газель» с картошкой на даче у тёщи.",
        "Подежурил на лавочке у подъезда вместо бабушек.",
        "Отработал смену охранником в «Пятёрочке».",
        "Объяснил деду, как зайти на «Госуслуги». Дважды.",
        "Продавал семечки у метро.",
        "Сварил пельмени на всю общагу.",
        "Собрал шкаф без инструкции. Лишних шурупов осталось семь.",
        "Покрасил забор в стиле «и так сойдёт».",
        "Перевёз диван на «девятке». Диван цел, «девятка» - не очень.",
        "Поработал курьером под дождём, принёс суп ещё горячим.",
        "Был тамадой на свадьбе двоюродного брата.",
        "Помог соседу сверху «немного» передвинуть мебель в 2 часа ночи.",
        "Записался «на минуточку» помочь с ремонтом и остался на три дня.",
        "Посчитал всю мелочь из копилки для младшего брата.",
        "Поменял лампочку в подъезде. Весь дом благодарен.",
    ],
}

def work_line():
    lang = _LANG.get()
    return _RNG.choice(WORK_LINES.get(lang) or WORK_LINES["en"])

@bot.command(name="work")
@feature_required("economy")
async def work_p(ctx):
    gid = ctx.guild.id; econ = get_econ(gid, ctx.author.id)
    now = datetime.now(timezone.utc); last = econ.get("last_work")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < 3600:
        remaining = 3600 - (now - datetime.fromisoformat(last)).total_seconds()
        await ctx.send(embed=discord.Embed(description=t(gid, "work_wait", f"{int(remaining // 60)}m"), color=0xED4245), delete_after=10)
        return
    amount = _RNG.randint(50, 200)
    econ["wallet"] += amount; econ["last_work"] = now.isoformat(); save_econ()
    desc = f"💼 {work_line()}\n" + L("💵 **+${:,}** · Wallet: **${:,}**", amount, econ["wallet"])
    await ctx.send(embed=discord.Embed(description=desc, color=0x57F287))

# ---------- forceban: ban by ID, also people who are not in the server ----------
@bot.command(name="forceban", aliases=["hackban"])
@commands.bot_has_permissions(ban_members=True)
async def forceban_p(ctx, target: str = None, duration: str = None, *, reason: str = "No reason"):
    gid = ctx.guild.id
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send(t(gid, "no_perm"), delete_after=5)
        return
    m = re.fullmatch(r"<@!?(\d{15,21})>|(\d{15,21})", (target or "").strip())
    if not m:
        await ctx.send(L('❌ Usage: `{}`', '.forceban <user ID> [1d/2h/30m] [reason]'), delete_after=8)
        return
    uid = int(m.group(1) or m.group(2))
    duration, reason, _notify = mod_args(duration, reason, None)        # no DM: we may share no server with them
    if uid in (ctx.author.id, bot.user.id, ctx.guild.owner_id):
        await ctx.send(t(gid, "cannot_act"), delete_after=5)
        return
    member = ctx.guild.get_member(uid)
    if member is not None and (not can_act_on(ctx.author, member, ctx.guild) or member.top_role >= ctx.guild.me.top_role):
        await ctx.send(t(gid, "cannot_act"), delete_after=5)
        return
    try:
        user = await bot.fetch_user(uid)
    except discord.NotFound:
        await ctx.send(L("❌ No Discord account has the ID `{}`.", uid), delete_after=8)
        return
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=6)
        return
    try:
        await ctx.guild.fetch_ban(user)
        await ctx.send(L("❌ **{}** is already banned here.", user), delete_after=8)
        return
    except discord.NotFound:
        pass
    except Exception:
        pass
    ban_secs, label = None, L("Permanent")
    if duration:
        secs, lbl = parse_duration(duration)
        if secs:
            ban_secs, label = secs, lbl
        else:
            reason = f"{duration} {reason}".strip()
    try:
        await ctx.guild.ban(user, reason=f"{reason} (forceban by {ctx.author})", delete_message_seconds=0)
    except Exception as e:
        await ctx.send(f"❌ {e}", delete_after=6)
        return
    case_id = next_case_s(get_settings(gid))
    embed = discord.Embed(color=0xED4245)
    embed.set_author(name=L('🔨 Banned — {}', user), icon_url=user.display_avatar.url)
    embed.add_field(name=L('Duration'), value=f"`{label}`", inline=True)
    embed.add_field(name=L('Reason'), value=reason, inline=False)
    if member is None:
        embed.description = L("Banned by ID - this account was not in the server.")
    embed.set_footer(text=L('Case #{}', case_id))
    await ctx.send(embed=embed, delete_after=15)
    try:
        await ctx.message.add_reaction("✅")
    except Exception:
        pass
    await post_case_log(ctx.guild, case_id, "ban", user, ctx.author, f"[{label}] {reason} (forceban)")
    if ban_secs:
        schedule_task("unban", gid, user.id, _time.time() + ban_secs)

# ---------- Higher-Lower: payout from the real chance, ties lose, 3% house edge per guess ----------
HL_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]      # ace is high
HL_EDGE = 0.03
HL_MAX_MULT = 1000.0          # the game cashes out by itself at x1000

def hl_value(card):
    return HL_RANKS.index(card[0]) + 2

def hl_odds(card):
    """{'higher': (chance, multiplier), 'lower': (...)}. Every rank is equally likely on every draw (endless shoe);
    a tie loses, so the chance already contains it and RTP = chance x multiplier <= 1 - HL_EDGE."""
    v, out = hl_value(card), {}
    for side, wins in (("higher", 14 - v), ("lower", v - 2)):
        p = wins / 13
        out[side] = (p, math.floor((1 - HL_EDGE) / p * 100) / 100 if p else 0.0)
    return out

def hl_draw():
    return (_RNG.choice(HL_RANKS), _RNG.choice(CARD_SUITS))

class HigherLowerView(BaseView):
    def __init__(self, uid, gid, bet, name, channel=None):
        super().__init__(timeout=120)
        self.uid, self.gid, self.bet, self.name, self.channel = uid, gid, bet, name, channel
        self.card, self.history, self.mult, self.wins = hl_draw(), [], 1.0, 0
        self.message, self.done, self.lock = None, False, asyncio.Lock()
        self.refresh_buttons()

    def amount(self):
        return int(self.bet * self.mult)

    def refresh_buttons(self):
        odds = hl_odds(self.card)
        for btn, side, word in ((self.higher, "higher", L("Higher")), (self.lower, "lower", L("Lower"))):
            p, m = odds[side]
            btn.label = f"{word} ×{m:.2f}" if p else word
            btn.disabled = not p
        self.cashout.label = L("Cash out ${:,}", self.amount())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.uid:
            await interaction.response.send_message(L('❌ This is not your game!'), ephemeral=True)
            return False
        return True

    async def screen(self, nxt=None, banner=None, tone=None, note=""):
        """(embed, files) for the current state."""
        odds = hl_odds(self.card)
        if self.done:
            color = 0x57F287 if tone == "win" else 0xED4245
        else:
            color = 0xffd700
        embed = discord.Embed(title=L("🃏 Higher or Lower"), color=color)
        lines = [note] if note else []
        if not self.done:
            lines.append(L("Will the next card be higher or lower? A tie loses."))
            lines.append(L("Higher: **{}** chance · Lower: **{}** chance", f"{odds['higher'][0]:.0%}", f"{odds['lower'][0]:.0%}"))
        embed.description = "\n".join(lines)
        embed.set_footer(text=L("Bet: ${:,}", self.bet) + f" · ×{self.mult:,.2f} · " + L("Correct guesses: {}", self.wins))
        files = await _fx_attach(embed, "hl.png", render_hl, self.card, nxt, list(self.history), self.mult, f"${self.amount():,}", banner, tone, L("Higher or Lower").upper(), channel=self.channel)
        if not files:
            embed.add_field(name=L("Card"), value=card_emoji(self.card) + (f" → {card_emoji(nxt)}" if nxt else ""), inline=True)
            embed.add_field(name=L("Win"), value=f"${self.amount():,} (×{self.mult:,.2f})", inline=True)
        return embed, files

    async def finish(self, cashed):
        self.done = True
        self.stop()
        if active_bj.get(self.uid) is self:
            active_bj.pop(self.uid, None)
        if cashed:
            econ = get_econ(self.gid, self.uid)
            econ["wallet"] += self.amount()
            save_econ()

    async def guess(self, interaction, side):
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                return
            p, m = hl_odds(self.card)[side]
            if not p:
                return
            nxt = hl_draw()
            won = hl_value(nxt) > hl_value(self.card) if side == "higher" else hl_value(nxt) < hl_value(self.card)
            word = L("Higher") if side == "higher" else L("Lower")
            if not won:
                await self.finish(cashed=False)
                embed, files = await self.screen(nxt, banner=L("LOST"), tone="lose",
                                                 note=L("❌ **{}** was wrong - the card was {}. You lost **${:,}**.", word, card_emoji(nxt), self.bet))
                await interaction.edit_original_response(embed=embed, attachments=files, view=None)
                return
            self.history.append(self.card)
            self.card, self.mult, self.wins = nxt, self.mult * m, self.wins + 1
            if self.mult >= HL_MAX_MULT:
                await self.finish(cashed=True)
                embed, files = await self.screen(None, banner=L("MAX WIN"), tone="win", note=L("🏆 Maximum reached - auto cash out: **+${:,}**", self.amount()))
                await interaction.edit_original_response(embed=embed, attachments=files, view=None)
                return
            self.refresh_buttons()
            embed, files = await self.screen(note=L("✅ **{}** - correct! Cash out or keep going.", word))
            await interaction.edit_original_response(embed=embed, attachments=files, view=self)

    @discord.ui.button(label="Higher", emoji="⬆️", style=discord.ButtonStyle.green)
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.guess(interaction, "higher")

    @discord.ui.button(label="Lower", emoji="⬇️", style=discord.ButtonStyle.red)
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.guess(interaction, "lower")

    @discord.ui.button(label="Cash out", emoji="💰", style=discord.ButtonStyle.blurple)
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                return
            await self.finish(cashed=True)
            embed, files = await self.screen(banner=L("CASHED OUT"), tone="win", note=L("💰 Cashed out **${:,}** (×{:,.2f}).", self.amount(), self.mult))
            await interaction.edit_original_response(embed=embed, attachments=files, view=None)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            await self.finish(cashed=True)              # idle: the current amount is paid out, nothing is lost
            if self.message:
                try:
                    embed, files = await self.screen(banner=L("CASHED OUT"), tone="win", note=L("⏰ Time is up - auto cash out: **${:,}**.", self.amount()))
                    await self.message.edit(embed=embed, attachments=files, view=None)
                except Exception:
                    pass

@bot.command(name="higherlower", aliases=["hl"])
@feature_required("casino")
async def hl_p(ctx, bet: str = None):
    gid = ctx.guild.id
    if not await check_casino(ctx, is_slash=False):
        return
    econ = get_econ(gid, ctx.author.id)
    amount = parse_amount(bet, econ["wallet"])
    if amount is None or amount <= 0:
        await ctx.send(t(gid, "invalid_bet", f"{econ['wallet']:,}"), delete_after=8)
        return
    if ctx.author.id in active_bj:
        await ctx.send(L("❌ You already have a card game running!"), delete_after=5)
        return
    if amount > econ["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{econ['wallet']:,}"), color=0xED4245))
        return
    econ["wallet"] -= amount
    save_econ()
    view = HigherLowerView(ctx.author.id, gid, amount, ctx.author.display_name, channel=ctx.channel)
    active_bj[ctx.author.id] = view
    embed, files = await view.screen()
    view.message = await ctx.send(embed=embed, files=files, view=view)

# ---------- blackjack: 1 to 4 players at one table, own drawn cards ----------
BJ_MAX_PLAYERS = 4
BJ_TURN_SECONDS = 45
BJ_INVITE_SECONDS = 60

def bj_dealer_play(dealer, draw):
    while hand_value(dealer) < 17:
        dealer.append(draw())
    return dealer

def bj_credit(state, pv, dv, bet):
    """Coins that go back to the wallet (stake included). state: 'bust' | 'bj' (natural) | 'stand'."""
    if state == "bust" or pv > 21:
        return 0
    if state == "bj":
        return int(bet * 2.5)
    if dv > 21 or pv > dv:
        return bet * 2
    if pv == dv:
        return bet
    return 0

def bj_shoe(players):
    deck = [(v, s) for s in CARD_SUITS for v in HL_RANKS] * (1 if players <= 1 else 2)
    _RNG.shuffle(deck)
    return deck

class BlackjackTable(BaseView):
    def __init__(self, gid, members, bet):
        super().__init__(timeout=900)
        self.gid, self.message, self.lock, self.finished, self.moves, self._timer, self.channel = gid, None, asyncio.Lock(), False, 0, None, None
        self.deck = bj_shoe(len(members))
        self.seats = [{"id": m.id, "name": m.display_name, "hand": [], "bet": bet, "state": "play", "credit": 0, "afk": False} for m in members]
        self.dealer = []
        for s in self.seats:
            s["hand"] = [self.draw(), self.draw()]
            if hand_value(s["hand"]) == 21:
                s["state"] = "bj"
        self.dealer = [self.draw(), self.draw()]
        self.turn = -1
        self.advance()

    def draw(self):
        if not self.deck:
            self.deck = bj_shoe(len(self.seats))
        return self.deck.pop()

    def current(self):
        return self.seats[self.turn] if 0 <= self.turn < len(self.seats) else None

    def advance(self):
        self.turn = next((i for i in range(self.turn + 1, len(self.seats)) if self.seats[i]["state"] == "play"), len(self.seats))
        self.moves += 1
        cur = self.current()
        if cur:
            self.double.disabled = len(cur["hand"]) != 2 or get_econ(self.gid, cur["id"])["wallet"] < cur["bet"]

    def settle(self):
        if any(s["state"] != "bust" for s in self.seats):
            bj_dealer_play(self.dealer, self.draw)
        dv = hand_value(self.dealer)
        for s in self.seats:
            s["credit"] = bj_credit(s["state"], hand_value(s["hand"]), dv, s["bet"])
            if s["credit"]:
                get_econ(self.gid, s["id"])["wallet"] += s["credit"]
        save_econ()
        self.finished = True
        self.stop()
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        for s in self.seats:
            if active_bj.get(s["id"]) is self:
                active_bj.pop(s["id"], None)

    def _seat_line(self, s):
        pv, cur = hand_value(s["hand"]), self.current()
        if self.finished:
            delta = s["credit"] - s["bet"]
            if s["state"] == "bust":
                return L("❌ **{}** busted: **-${:,}**", s["name"], s["bet"]), "lose"
            if delta > 0:
                return (L("🎉 **{}** - Blackjack! **+${:,}**", s["name"], delta) if s["state"] == "bj" else L("✅ **{}** wins **+${:,}**", s["name"], delta)), "win"
            if delta == 0:
                return L("🤝 **{}** - push, bet returned", s["name"]), "push"
            return L("❌ **{}** loses **-${:,}**", s["name"], s["bet"]), "lose"
        if s is cur:
            return L("👉 **{}** is playing ({}s)", s["name"], BJ_TURN_SECONDS), None
        tags = {"bj": L("Blackjack!"), "bust": L("Bust"), "stand": L("Stand"), "play": L("Waiting")}
        return f"**{s['name']}** - {tags.get(s['state'], '')}" + (" ⏰" if s["afk"] else ""), None

    async def screen(self):
        cur = self.current()
        reveal = self.finished
        color = 0x1a1a1a if not reveal else 0x57F287 if any(s["credit"] > s["bet"] for s in self.seats) else 0xED4245
        title = L("🃏 Blackjack") + (" · " + L("{} players", len(self.seats)) if len(self.seats) > 1 else "")
        embed = discord.Embed(title=title, color=color)
        lines, seats = [], []
        for s in self.seats:
            line, tone = self._seat_line(s)
            lines.append(line)
            if reveal:
                delta = s["credit"] - s["bet"]
                tag = L("Bust") if s["state"] == "bust" else f"+${delta:,}" if delta > 0 else L("Push") if delta == 0 else f"-${s['bet']:,}"
                if s["state"] == "bj":
                    tag = L("Blackjack!") + " " + tag
            else:
                tag = {"bj": L("Blackjack!"), "bust": L("Bust"), "stand": L("Stand")}.get(s["state"], "")
            tag = tag.upper()
            seats.append({"name": s["name"], "hand": s["hand"], "value": hand_value(s["hand"]), "tag": tag, "turn": s is cur and not reveal, "tone": tone})
        if reveal:
            lines.append(L("Dealer: **{}**", hand_value(self.dealer)) + (" - " + L("Bust") if hand_value(self.dealer) > 21 else ""))
        embed.description = "\n".join(lines)
        embed.set_footer(text=L('Bet: ${:,}', self.seats[0]["bet"]) if len(self.seats) == 1 else L("Bet per player: ${:,}", self.seats[0]["bet"]))
        files = await _fx_attach(embed, "bj.png", render_bj_table, list(self.dealer), not reveal, seats, {"dealer": L("Dealer")}, channel=self.channel)
        if not files:
            dealer = " ".join(card_emoji(c) for c in self.dealer) if reveal else card_emoji(self.dealer[0]) + " 🂠"
            embed.add_field(name=L('Dealer hand ({})', hand_value(self.dealer)) if reveal else L('Dealer hand (?)'), value=dealer, inline=False)
            for s in self.seats:
                embed.add_field(name=f"{s['name']} ({hand_value(s['hand'])})", value=" ".join(card_emoji(c) for c in s["hand"]), inline=True)
        return embed, files

    def _arm_timer(self):
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        if not self.finished and self.current():
            self._timer = asyncio.create_task(self._turn_timeout(self.moves))

    async def _turn_timeout(self, moves):
        try:
            await asyncio.sleep(BJ_TURN_SECONDS)
        except asyncio.CancelledError:
            return
        async with self.lock:
            if self.finished or self.moves != moves or not self.current():
                return
            seat = self.current()
            seat["state"], seat["afk"] = "stand", True            # an idle player stands; the others keep playing
            self.advance()
            if not self.current():
                self.settle()
            await self.publish()

    async def publish(self, interaction=None):
        embed, files = await self.screen()
        view = None if self.finished else self
        try:
            if interaction is not None:
                await interaction.edit_original_response(embed=embed, attachments=files, view=view)
            elif self.message:
                await self.message.edit(embed=embed, attachments=files, view=view)
        except Exception:
            pass
        self._arm_timer()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        cur = self.current()
        if cur is None or interaction.user.id != cur["id"]:
            mine = any(s["id"] == interaction.user.id for s in self.seats)
            await interaction.response.send_message(L("⏳ It is not your turn!") if mine else L('❌ This is not your game!'), ephemeral=True)
            return False
        return True

    async def act(self, interaction, action):
        await interaction.response.defer()
        async with self.lock:
            seat = self.current()
            if self.finished or seat is None or seat["id"] != interaction.user.id:
                return
            if action == "double":
                econ = get_econ(self.gid, seat["id"])
                if len(seat["hand"]) != 2 or econ["wallet"] < seat["bet"]:
                    await interaction.followup.send(L('❌ You can only double on your first move and with enough money!'), ephemeral=True)
                    return
                econ["wallet"] -= seat["bet"]
                seat["bet"] *= 2
                save_econ()
            if action in ("hit", "double"):
                seat["hand"].append(self.draw())
            pv = hand_value(seat["hand"])
            if pv > 21:
                seat["state"] = "bust"
            elif action in ("stand", "double") or pv == 21:
                seat["state"] = "stand"
            if seat["state"] != "play":
                self.advance()
            else:
                self.moves += 1
                self.double.disabled = True
            if not self.current():
                self.settle()
            await self.publish(interaction)

    @discord.ui.button(label="Hit", emoji="👆", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.act(interaction, "hit")

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.act(interaction, "stand")

    @discord.ui.button(label="Double", emoji="✌️", style=discord.ButtonStyle.blurple)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.act(interaction, "double")

    async def on_timeout(self):
        async with self.lock:
            if self.finished:
                return
            for s in self.seats:
                if s["state"] == "play":
                    s["state"], s["afk"] = "stand", True
            self.turn = len(self.seats)
            self.settle()
            await self.publish()

async def start_bj_table(gid, members, bet, send=None, message=None, channel=None):
    """Seats are paid already. Deals, then sends (or edits the invite message into) the table."""
    table = BlackjackTable(gid, members, bet)
    table.channel = channel or getattr(message, "channel", None)
    for m in members:
        active_bj[m.id] = table
    if not table.current():
        table.settle()
    embed, files = await table.screen()
    view = None if table.finished else table
    if message is not None:
        await message.edit(content=None, embed=embed, attachments=files, view=view)
        table.message = message
    else:
        table.message = await send(embed=embed, files=files, view=view)
    table._arm_timer()
    return table

class BlackjackInvite(BaseView):
    def __init__(self, gid, host, invited, bet):
        super().__init__(timeout=BJ_INVITE_SECONDS)
        self.gid, self.host, self.invited, self.bet = gid, host, invited, bet
        self.accepted, self.declined, self.message, self.closed, self.lock = [], [], None, False, asyncio.Lock()

    def embed(self):
        ids = {m.id for m in self.accepted}
        nope = {m.id for m in self.declined}
        rows = [f"{'✅' if m.id in ids else '❌' if m.id in nope else '⏳'} {m.mention}" for m in self.invited]
        e = discord.Embed(title=L("🃏 Blackjack table"), color=0xffd700,
                          description=L("{} invites you to blackjack. Bet: **${:,}** each.\nPress **Accept** within {} seconds.", self.host.mention, self.bet, BJ_INVITE_SECONDS) + "\n\n" + "\n".join(rows))
        e.set_footer(text=L("Players take turns - only the player whose turn it is can press the buttons."))
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.host.id and interaction.user.id not in {m.id for m in self.invited}:
            await interaction.response.send_message(L("❌ This invitation is not for you."), ephemeral=True)
            return False
        return True

    def _refund_all(self):
        for m in [self.host] + self.accepted:
            get_econ(self.gid, m.id)["wallet"] += self.bet
            if isinstance(active_bj.get(m.id), BlackjackInvite):
                active_bj.pop(m.id, None)
        save_econ()

    async def _maybe_start(self, interaction=None):
        if len(self.accepted) + len(self.declined) < len(self.invited):
            if interaction is not None:
                await interaction.response.edit_message(embed=self.embed(), view=self)
            return
        await self._close(interaction)

    async def _close(self, interaction=None):
        """Everyone answered or time is up: start with whoever accepted, otherwise cancel and refund."""
        self.closed = True
        self.stop()
        if interaction is not None:
            await interaction.response.defer()
        if not self.accepted:
            self._refund_all()
            await self.message.edit(content=None, embed=discord.Embed(description=L("🃏 Nobody accepted - the table is closed and the bet was returned."), color=0x808080), view=None)
            return
        members = [self.host] + [m for m in self.invited if m in self.accepted]
        await start_bj_table(self.gid, members, self.bet, message=self.message)

    @discord.ui.button(label="Accept", emoji="✅", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            user = interaction.user
            if self.closed or user.id == self.host.id or user in self.accepted or user in self.declined:
                await interaction.response.send_message(L("❌ You already answered."), ephemeral=True)
                return
            if user_restricted(user.id, "casino"):
                await interaction.response.send_message(restricted_text("casino"), ephemeral=True)
                return
            if user.id in active_bj:
                await interaction.response.send_message(L("❌ You already have a card game running!"), ephemeral=True)
                return
            econ = get_econ(self.gid, user.id)
            if econ["wallet"] < self.bet:
                await interaction.response.send_message(t(self.gid, "not_enough_wallet", f"{econ['wallet']:,}"), ephemeral=True)
                return
            econ["wallet"] -= self.bet
            save_econ()
            active_bj[user.id] = self
            self.accepted.append(next(m for m in self.invited if m.id == user.id))
            await self._maybe_start(interaction)

    @discord.ui.button(label="Decline", emoji="✖️", style=discord.ButtonStyle.grey)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            user = interaction.user
            if self.closed or user.id == self.host.id or user in self.accepted or user in self.declined:
                await interaction.response.send_message(L("❌ You already answered."), ephemeral=True)
                return
            self.declined.append(next(m for m in self.invited if m.id == user.id))
            await self._maybe_start(interaction)

    @discord.ui.button(label="Start now", emoji="▶️", style=discord.ButtonStyle.blurple)
    async def start_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if interaction.user.id != self.host.id:
                await interaction.response.send_message(L("❌ Only {} can do this.", self.host.display_name), ephemeral=True)
                return
            if self.closed:
                return
            if not self.accepted:
                self._refund_all()
                self.closed = True
                self.stop()
                await interaction.response.edit_message(content=None, embed=discord.Embed(description=L("🃏 The table was cancelled and the bet was returned."), color=0x808080), view=None)
                return
            await self._close(interaction)

    async def on_timeout(self):
        async with self.lock:
            if not self.closed:
                try:
                    await self._close()
                except Exception:
                    pass

@bot.command(name="blackjack", aliases=["bj"])
@feature_required("casino")
async def bj_p(ctx, *, bet: str = None):
    """.bj <bet>  or  .bj @a @b @c <bet>  (up to 4 players including you)."""
    gid = ctx.guild.id
    if not await check_casino(ctx, is_slash=False):
        return
    ids, rest = [], []
    for tok in (bet or "").split():
        m = re.fullmatch(r"<@!?(\d+)>", tok)
        if m:
            if int(m.group(1)) not in ids:
                ids.append(int(m.group(1)))
        else:
            rest.append(tok)
    econ = get_econ(gid, ctx.author.id)
    amount = parse_amount(rest[0] if len(rest) == 1 else None, econ["wallet"])
    if amount is None or amount <= 0:
        await ctx.send(t(gid, "invalid_bet", f"{econ['wallet']:,}") + "\n" + L("Usage: `{}`", ".bj <bet>  ·  .bj @user1 @user2 <bet>"), delete_after=10)
        return
    invited = [ctx.guild.get_member(i) for i in ids if i != ctx.author.id]
    if any(m is None or m.bot for m in invited) or len(invited) > BJ_MAX_PLAYERS - 1:
        await ctx.send(L("❌ You can invite up to {} members (no bots).", BJ_MAX_PLAYERS - 1), delete_after=8)
        return
    if ctx.author.id in active_bj:
        await ctx.send(L("❌ You already have a card game running!"), delete_after=5)
        return
    busy = [m.display_name for m in invited if m.id in active_bj]
    if busy:
        await ctx.send(L("❌ Already in a card game: {}", ", ".join(busy)), delete_after=8)
        return
    if amount > econ["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{econ['wallet']:,}"), color=0xED4245))
        return
    econ["wallet"] -= amount
    save_econ()
    if not invited:
        await start_bj_table(gid, [ctx.author], amount, send=ctx.send, channel=ctx.channel)
        return
    invite = BlackjackInvite(gid, ctx.author, invited, amount)
    active_bj[ctx.author.id] = invite
    invite.message = await ctx.send(content=" ".join(m.mention for m in invited), embed=invite.embed(), view=invite,
                                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

# ---------- animated slots + coin flip (falls back to the plain embed without Pillow) ----------
@bot.command(name="slots")
@feature_required("casino")
async def slots_p(ctx, bet: str = None):
    gid = ctx.guild.id
    if not await check_casino(ctx, is_slash=False):
        return
    econ = get_econ(gid, ctx.author.id)
    if bet is None:
        embed = discord.Embed(title=L("🎰 Slots Paytable"), color=0xffd700,
                              description=slots_paytable() + "\n\n" + L("Three of a kind pays the big number, two of a kind the small one. 🍀 pays nothing."))
        embed.set_footer(text=L("Play: .slots <bet> · Wallet: ${:,}", econ["wallet"]))
        await ctx.send(embed=embed)
        return
    amount = parse_amount(bet, econ["wallet"])
    if amount is None or amount <= 0:
        await ctx.send(t(gid, "invalid_bet", f"{econ['wallet']:,}"), delete_after=8)
        return
    bet = amount
    if bet > econ["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{econ['wallet']:,}"), color=0xED4245))
        return
    econ["wallet"] -= bet
    reels, mult, kind = slot_spin()
    payout = int(bet * mult)
    econ["wallet"] += payout
    save_econ()
    display = " | ".join(reels)
    sym = next((e for e in reels if reels.count(e) >= 2), "")
    if kind == "jackpot":
        desc, color = L("🎰 {}\n\n💥 **JACKPOT!** x{:g} → **${:,}**!", display, mult, payout), 0xffd700
    elif kind == "triple":
        desc, color = L("🎰 {}\n\n🎉 **Three {}!** x{:g} → **${:,}**", display, sym, mult, payout), 0x57F287
    elif kind == "pair" and mult > 1:
        desc, color = L("🎰 {}\n\n✅ Two {}! x{:g} → **${:,}**", display, sym, mult, payout), 0x57F287
    elif kind == "pair":
        desc, color = L("🎰 {}\n\n🤝 Two {}! Your bet is returned.", display, sym), 0xFEE75C
    else:
        desc, color = L("🎰 {}\n\n❌ No match. -${:,}", display, bet), 0xED4245
    try:
        if not _can_attach(ctx.channel):
            raise RuntimeError("no Attach Files permission here")
        gif, png, secs = await fx_run(render_slots, reels, mult, kind, timeout=8.0)
    except Exception:
        await ctx.send(embed=discord.Embed(description=desc, color=color))
        return
    spin = discord.Embed(title=L("🎰 Slots"), description=L("Spinning... bet **${:,}**", bet), color=0x2b2d31)
    spin.set_image(url="attachment://slots.gif")
    msg = await ctx.send(embed=spin, file=discord.File(io.BytesIO(gif), filename="slots.gif"))
    await asyncio.sleep(secs + 0.2)
    final = discord.Embed(title=L("🎰 Slots"), description=desc.split("\n\n", 1)[-1], color=color)
    final.set_image(url="attachment://slots.png")
    try:
        await msg.edit(embed=final, attachments=[discord.File(io.BytesIO(png), filename="slots.png")])
    except Exception:
        pass

@bot.command(name="coinflip", aliases=["cf"])
@feature_required("casino")
async def cf_p(ctx, bet: str = None, choice: str = None):
    gid = ctx.guild.id
    if not await check_casino(ctx, is_slash=False):
        return
    picks = {"heads": "heads", "head": "heads", "h": "heads", "tails": "tails", "tail": "tails", "t": "tails"}
    if bet and bet.lower() in picks and choice and choice.lower() not in picks:      # "cf heads 30%" works too
        bet, choice = choice, bet
    pick = picks.get((choice or "").lower())
    if bet is None or not pick:
        await ctx.send(L("❌ Usage: `{}`", ".cf <bet|all|half|25%> heads/tails"), delete_after=6)
        return
    econ = get_econ(gid, ctx.author.id)
    amount = parse_amount(bet, econ["wallet"])
    if amount is None or amount <= 0:
        await ctx.send(t(gid, "invalid_bet", f"{econ['wallet']:,}"), delete_after=8)
        return
    bet = amount
    if bet > econ["wallet"]:
        await ctx.send(embed=discord.Embed(description=t(gid, "not_enough_wallet", f"{econ['wallet']:,}"), color=0xED4245))
        return
    result = "heads" if _RNG.getrandbits(1) == 0 else "tails"
    won = result == pick
    econ["wallet"] += bet if won else -bet
    save_econ()
    face = L("Heads") if result == "heads" else L("Tails")
    if won:
        desc = L("🪙 **{}**!\n✅ You won **+${:,}**!", face, bet)
    else:
        desc = L("🪙 **{}**!\n❌ You lost **-${:,}**!", face, bet)
    try:
        if not _can_attach(ctx.channel):
            raise RuntimeError("no Attach Files permission here")
        gif, png, secs = await fx_run(render_coin, result, won, face, timeout=6.0)
    except Exception:
        await ctx.send(embed=discord.Embed(description=desc, color=0x57F287 if won else 0xED4245))
        return
    toss = discord.Embed(title=L("🪙 Coinflip"), description=L("Flipping... **{}** for **${:,}**", L("Heads") if pick == "heads" else L("Tails"), bet), color=0x2b2d31)
    toss.set_image(url="attachment://coin.gif")
    msg = await ctx.send(embed=toss, file=discord.File(io.BytesIO(gif), filename="coin.gif"))
    await asyncio.sleep(secs + 0.2)
    final = discord.Embed(title=L("🪙 Coinflip"), description=desc, color=0x57F287 if won else 0xED4245)
    final.set_image(url="attachment://coin.png")
    try:
        await msg.edit(embed=final, attachments=[discord.File(io.BytesIO(png), filename="coin.png")])
    except Exception:
        pass

# ============================================================
# EVENTS
# ============================================================
_started = False

@bot.event
async def on_ready():
    global _started
    print(f"[READY] {bot.user} is online! {len(bot.guilds)} servers")
    if _started:
        return
    _started = True
    for make in (GiveawayView, CloseTicketView, ModmailOwnerView, PollView):
        try:
            bot.add_view(make())
        except Exception as e:
            print(f"[READY] could not register {make.__name__}: {e}")
    for guild in bot.guilds:
        try:
            bot.add_view(DynamicTicketView(guild.id, include_all=True))
        except Exception as e:
            print(f"[READY] ticket view for {guild.id}: {e}")
    try:
        synced = await bot.tree.sync()
        print(f"[READY] Synced {len(synced)} slash commands!")
    except Exception as e:
        print(f"[READY] Sync error: {e}")
    pending = {(x["guild"], x["target"]) for x in schedule_db["tasks"] if x["type"] == "giveaway"}
    for gid, gas in giveaways_db.items():          # giveaways made before persistent timers existed
        for ga_id, ga in gas.items():
            if not ga.get("ended") and (gid, ga_id) not in pending:
                try:
                    schedule_task("giveaway", gid, ga_id, datetime.fromisoformat(ga["ends_at"]).timestamp())
                except Exception:
                    pass
    try:
        prune_role_persist()
    except Exception:
        pass
    prune_giveaways()
    for loop_fn in (backup_loop, scheduler_loop, flush_loop, vc_xp_loop):
        keep_task(loop_fn())
    print("[READY] background tasks started (backup, timers, XP flush)")

@bot.before_invoke
async def _language_hook(ctx):
    set_lang(ctx.guild.id if ctx.guild else None)

@bot.check
async def global_check(ctx):
    if not ctx.guild:
        return False
    if str(ctx.guild.id) in bot_bans_db.get("servers", []):
        return False
    if ctx.author.id != BOT_CREATOR_ID and str(ctx.author.id) in bot_bans_db.get("banned", []):
        return False
    if rate_limited(ctx.author.id):
        return False
    return True

_ban_notice = {}

async def notify_bot_banned(message):
    """A bot-banned user tried a text command. Text commands cannot get a private reply (only slash commands and buttons can), so:
    no DM - a short SILENT reply (no notification) that deletes itself, at most once a minute per user."""
    now = _time.time()
    if now - _ban_notice.get(message.author.id, 0) < 60:
        return
    _ban_notice[message.author.id] = now
    text = L("⛔ You are banned from using this bot.")
    try:
        await message.reply(text, mention_author=False, silent=True, delete_after=10)
    except Exception:
        try:
            await message.channel.send(text, silent=True, delete_after=10)
        except Exception:
            pass

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not message.guild:                                   # ---- DMs to the bot
        if await handle_whitelist_dm(message) or await handle_deletedata_dm(message) or await handle_owner_dm(message):
            return
        uid = message.author.id
        if uid == BOT_CREATOR_ID or user_restricted(uid, "modmail"):
            return
        now = _time.time()
        recent = [x for x in _dm_rate.get(uid, []) if now - x < 60]
        if len(recent) >= 6:
            return
        recent.append(now)
        _dm_rate[uid] = recent
        await forward_to_owner(message.author, message.content, message.attachments)
        return
    guild, uid = message.guild, message.author.id
    if str(guild.id) in bot_bans_db.get("servers", []):
        return
    is_banned = uid != BOT_CREATOR_ID and str(uid) in bot_bans_db.get("banned", [])
    set_lang(guild.id)
    s = get_settings(guild.id)
    if await handle_honeypot(message):                      # server protection still applies to everyone
        return
    if await handle_counting(message):
        return
    ctx = await bot.get_context(message)
    if is_banned:
        # normal chat is left completely alone; only an attempt to use the bot gets a short silent notice (no commands, no XP)
        if ctx.valid and ctx.command:
            await notify_bot_banned(message)
        return
    if message.content.strip() in (f"<@{bot.user.id}>", f"<@!{bot.user.id}>"):      # "@Versa" alone: say hi and point to the help
        pfx = s.get("prefix", ".")
        try:
            await message.reply(L('👋 I am **Versa**! My prefix here is `{}` - type `{}help` or `/help` to see everything I can do.\nSupport: {}', pfx, pfx, SUPPORT_LINK), mention_author=False)
        except Exception:
            pass
        return
    botcom = s.get("botcom")
    if (ctx.valid and ctx.command and botcom and str(message.channel.id) != str(botcom)
            and ctx.command.name in GENERAL_CMDS and not is_owner(uid)):
        await silent_delete(message)
        ch = guild.get_channel(int(botcom))
        if ch:
            await message.channel.send(L('❌ Use bot commands in {}!', ch.mention), delete_after=5)
        return
    if uid in afk_db:
        del afk_db[uid]
        try:
            await message.channel.send(t(guild.id, "afk_back", message.author.mention), delete_after=5)
        except Exception:
            pass
    for mention in message.mentions:
        if mention.id in afk_db and mention.id != uid:
            try:
                await message.channel.send(t(guild.id, "afk_user", mention.display_name, afk_db[mention.id]["reason"]), delete_after=10)
            except Exception:
                pass
    if is_feature_enabled(guild.id, "leveling") and not user_restricted(uid, "leveling"):
        if counts_as_message(message):
            count_message(guild.id, uid)
        key, now_ts = f"{guild.id}_{uid}", _time.time()
        if now_ts - xp_cooldown.get(key, 0) > 30:
            xp_cooldown[key] = now_ts
            cfg = get_level_config(guild.id)
            udata = get_user_xp(guild.id, uid)
            old_lvl = get_level(udata["xp"], guild.id)
            udata["xp"] += random.randint(cfg["xp_min"], cfg["xp_max"])
            new_lvl = get_level(udata["xp"], guild.id)
            udata["level"] = new_lvl
            if new_lvl > old_lvl:
                if s.get("levelup"):
                    ch = bot.get_channel(int(s["levelup"]))
                    if ch:
                        try:
                            await ch.send(embed=discord.Embed(description=t(guild.id, "levelup", message.author.mention, new_lvl), color=0xff6b35))
                        except Exception:
                            pass
                rid = s.get("levelroles", {}).get(str(new_lvl))
                role = guild.get_role(int(rid)) if rid else None
                if role and role_assignable(guild, role):
                    try:
                        await message.author.add_roles(role, reason=f"Level {new_lvl}")
                    except Exception:
                        pass
    await bot.invoke(ctx)

@bot.event
async def on_member_join(member):
    if str(member.guild.id) in bot_bans_db.get("servers", []):
        return
    set_lang(member.guild.id)
    s = get_settings(member.guild.id)
    if s.get("log_settings", {}).get("member_join", True):
        embed = discord.Embed(title=L('📥 Member Joined'), color=0x57F287, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name=L('User'), value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name=L('Account Age'), value=dts(member.created_at, "R"), inline=True)
        embed.add_field(name=L('Member Count'), value=f"`{member.guild.member_count}`", inline=True)
        await send_log(member.guild, embed)
    if s.get("welcome"):
        ch = member.guild.get_channel(int(s["welcome"]))
        if ch:
            try:
                await ch.send(embed=discord.Embed(description=t(member.guild.id, "welcome", member.guild.name, member.mention, member.guild.member_count), color=0xff6b35))
            except Exception:
                pass
    if s.get("welrole"):
        role = member.guild.get_role(int(s["welrole"]))
        if role and role_assignable(member.guild, role):
            try:
                await member.add_roles(role, reason="Welcome role")
            except Exception:
                pass
    await restore_member_roles(member)

@bot.event
async def on_member_remove(member):
    set_lang(member.guild.id)
    save_member_roles(member)
    if not get_settings(member.guild.id).get("log_settings", {}).get("member_leave", True):
        return
    embed = discord.Embed(title=L('📤 Member Left'), color=0x808080, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    embed.add_field(name=L('User'), value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name=L('Member Count'), value=f"`{member.guild.member_count}`", inline=True)
    embed.add_field(name=L('Roles'), value=(" ".join(r.mention for r in member.roles[1:]) or "-")[:1000], inline=False)
    await send_log(member.guild, embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    if await handle_counting_edit(before, after):
        return
    set_lang(before.guild.id)
    if not get_settings(before.guild.id).get("log_settings", {}).get("message_edit", True):
        return
    embed = discord.Embed(title=L('✏️ Message Edited'), color=0xFEE75C, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    embed.add_field(name=L('Channel'), value=before.channel.mention, inline=True)
    embed.add_field(name=L('Author'), value=f"{before.author.mention} (`{before.author.id}`)", inline=True)
    embed.add_field(name=L('Before'), value=(before.content or "*Empty*")[:400], inline=False)
    embed.add_field(name=L('After'), value=(after.content or "*Empty*")[:400], inline=False)
    embed.add_field(name=L('Jump'), value=L('[Go to message]({})', after.jump_url), inline=False)
    await send_log(before.guild, embed)

@bot.event
async def on_message_delete(message):
    if message.id in _silent_deletes:
        _silent_deletes.discard(message.id)
        return
    if not message.guild or message.author.bot:
        return
    first = (message.content or "").lstrip().split(" ")[0].lower()
    if re.sub(r"^\W+", "", first) in OWNER_ONLY_CMDS:       # never leak owner commands into server logs
        return
    set_lang(message.guild.id)
    if not get_settings(message.guild.id).get("log_settings", {}).get("message_delete", True):
        return
    embed = discord.Embed(title=L('🗑️ Message Deleted'), color=0xED4245, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
    embed.add_field(name=L('Channel'), value=message.channel.mention, inline=True)
    embed.add_field(name=L('Author'), value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
    embed.add_field(name=L('Content'), value=(message.content or "*No text*")[:900], inline=False)
    if message.attachments:
        embed.add_field(name=L('Attachments'), value="\n".join(a.filename for a in message.attachments)[:900], inline=False)
    await send_log(message.guild, embed)

@bot.event
async def on_bulk_message_delete(messages):
    if not messages or not messages[0].guild:
        return
    guild = messages[0].guild
    set_lang(guild.id)
    if not get_settings(guild.id).get("log_settings", {}).get("message_bulk", True):
        return
    await send_log(guild, discord.Embed(title=L('🗑️ Messages Purged'), color=0xED4245, timestamp=datetime.now(timezone.utc),
                                        description=L('**{}** messages were deleted in {}.', len(messages), messages[0].channel.mention)))

@bot.event
async def on_member_update(before, after):
    set_lang(after.guild.id)
    await _log_member_extra(before, after)
    log_cfg = get_settings(after.guild.id).get("log_settings", {})
    if before.nick != after.nick and log_cfg.get("member_nick", True):
        embed = discord.Embed(title=L('✏️ Nickname Changed'), color=0xFEE75C, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        embed.add_field(name=L('Before'), value=before.nick or "*None*", inline=True)
        embed.add_field(name=L('After'), value=after.nick or "*None*", inline=True)
        embed.add_field(name=L('User'), value=f"{after.mention} (`{after.id}`)", inline=False)
        await send_log(after.guild, embed)
    if before.roles != after.roles and log_cfg.get("member_role", True):
        added = [r for r in after.roles if r not in before.roles and not r.is_default()]
        removed = [r for r in before.roles if r not in after.roles and not r.is_default()]
        if added or removed:
            embed = discord.Embed(title=L('🎭 Roles Updated'), color=0x5865F2, timestamp=datetime.now(timezone.utc))
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name=L('Member'), value=f"{after.mention} (`{after.id}`)", inline=False)
            if added:
                embed.add_field(name=L('✅ Added'), value=" ".join(r.mention for r in added)[:1000], inline=True)
            if removed:
                embed.add_field(name=L('❌ Removed'), value=" ".join(r.mention for r in removed)[:1000], inline=True)
            await send_log(after.guild, embed)

async def _audit_actor(guild, action):
    try:
        async for entry in guild.audit_logs(action=action, limit=1):
            return entry.user
    except Exception:
        pass
    return None

@bot.event
async def on_guild_channel_create(channel):
    set_lang(channel.guild.id)
    if not get_settings(channel.guild.id).get("log_settings", {}).get("channel_create", True):
        return
    embed = discord.Embed(title=L('➕ Channel Created'), description=f"{channel.mention} (`{channel.id}`)", color=0x57F287, timestamp=datetime.now(timezone.utc))
    actor = await _audit_actor(channel.guild, discord.AuditLogAction.channel_create)
    if actor:
        embed.add_field(name=L('By'), value=actor.mention)
    await send_log(channel.guild, embed)

@bot.event
async def on_guild_channel_delete(channel):
    set_lang(channel.guild.id)
    if not get_settings(channel.guild.id).get("log_settings", {}).get("channel_delete", True):
        return
    embed = discord.Embed(title=L('➖ Channel Deleted'), description=f"**#{channel.name}** (`{channel.id}`)", color=0xED4245, timestamp=datetime.now(timezone.utc))
    actor = await _audit_actor(channel.guild, discord.AuditLogAction.channel_delete)
    if actor:
        embed.add_field(name=L('By'), value=actor.mention)
    await send_log(channel.guild, embed)

@bot.event
async def on_guild_role_create(role):
    set_lang(role.guild.id)
    if not get_settings(role.guild.id).get("log_settings", {}).get("role_create", True):
        return
    embed = discord.Embed(title=L('🎭 Role Created'), description=f"{role.mention} (`{role.id}`)", color=role.color, timestamp=datetime.now(timezone.utc))
    actor = await _audit_actor(role.guild, discord.AuditLogAction.role_create)
    if actor:
        embed.add_field(name=L('By'), value=actor.mention)
    await send_log(role.guild, embed)

@bot.event
async def on_guild_role_delete(role):
    set_lang(role.guild.id)
    if not get_settings(role.guild.id).get("log_settings", {}).get("role_delete", True):
        return
    embed = discord.Embed(title=L('🗑️ Role Deleted'), description=f"**@{role.name}** (`{role.id}`)", color=0xED4245, timestamp=datetime.now(timezone.utc))
    actor = await _audit_actor(role.guild, discord.AuditLogAction.role_delete)
    if actor:
        embed.add_field(name=L('By'), value=actor.mention)
    await send_log(role.guild, embed)

@bot.event
async def on_guild_update(before, after):
    set_lang(after.id)
    if not get_settings(after.id).get("log_settings", {}).get("server_update", True):
        return
    changes = []
    if before.name != after.name:
        changes.append(f"**Name:** {before.name} → {after.name}")
    if before.icon != after.icon:
        changes.append("**Icon:** changed")
    if not changes:
        return
    await send_log(after, discord.Embed(title=L('🏠 Server Updated'), description="\n".join(changes), color=0xFEE75C, timestamp=datetime.now(timezone.utc)))

@bot.event
async def on_member_ban(guild, user):
    set_lang(guild.id)
    if not get_settings(guild.id).get("log_settings", {}).get("member_ban", True):
        return
    await asyncio.sleep(0.5)
    actor = await _audit_actor(guild, discord.AuditLogAction.ban)
    if actor and actor.id == bot.user.id:                    # bot bans are already logged as cases
        return
    embed = discord.Embed(title=L('🔨 Member Banned'), color=0xED4245, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
    embed.add_field(name=L('User'), value=f"{user.mention} (`{user.id}`)", inline=True)
    if actor:
        embed.add_field(name=L('By'), value=actor.mention, inline=True)
    await send_log(guild, embed)

@bot.event
async def on_member_unban(guild, user):
    set_lang(guild.id)
    if not get_settings(guild.id).get("log_settings", {}).get("member_unban", True):
        return
    embed = discord.Embed(title=L('🔓 Member Unbanned'), color=0x57F287, timestamp=datetime.now(timezone.utc))
    embed.add_field(name=L('User'), value=f"{user.mention} (`{user.id}`)", inline=True)
    await send_log(guild, embed)

def _reaction_role(payload):
    if not is_feature_enabled(payload.guild_id, "reaction_roles"):
        return None
    return reaction_roles_db.get(str(payload.guild_id), {}).get(str(payload.message_id), {}).get(emoji_key(payload.emoji))

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id or not payload.guild_id or user_restricted(payload.user_id, "reaction_roles"):
        return
    rid = _reaction_role(payload)
    guild = bot.get_guild(payload.guild_id)
    if not rid or not guild:
        return
    member = payload.member or guild.get_member(payload.user_id)
    role = guild.get_role(int(rid))
    if member and role and role_assignable(guild, role):
        try:
            await member.add_roles(role, reason="Reaction role")
        except Exception:
            pass

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id or not payload.guild_id:
        return
    rid = _reaction_role(payload)
    guild = bot.get_guild(payload.guild_id)
    if not rid or not guild:
        return
    member, role = guild.get_member(payload.user_id), guild.get_role(int(rid))
    if member and role and role_assignable(guild, role):
        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except Exception:
            pass


async def _report_error(where, user, guild, error):
    """Unexpected errors go to the bot owner's DMs only - never into a public channel."""
    try:
        import traceback
        owner = await bot.fetch_user(BOT_CREATOR_ID)
        embed = discord.Embed(title="⚠️ Bot error", color=0xED4245, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Where", value=f"`{where}`", inline=True)
        embed.add_field(name="Server", value=f"{guild.name} (`{guild.id}`)" if guild else "DM", inline=True)
        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        embed.add_field(name="Error", value=f"```py\n{trace[-900:]}\n```", inline=False)
        await owner.send(embed=embed)
    except Exception:
        pass

@bot.event
async def on_command_error(ctx, error):
    perm_names = lambda e: ", ".join(p.replace("_", " ").title() for p in e.missing_permissions)
    reply = None
    if isinstance(error, commands.MissingPermissions): reply = (L('❌ You need the **{}** permission to use this command.', perm_names(error)), 8)
    elif isinstance(error, commands.BotMissingPermissions): reply = (L('❌ I need the **{}** permission first.', perm_names(error)), 8)
    elif isinstance(error, commands.NoPrivateMessage): reply = (L('❌ This command only works in servers.'), 5)
    elif isinstance(error, commands.CommandOnCooldown): reply = (L('⏳ Slow down! Try again in {}s.', int(error.retry_after) + 1), 5)
    elif isinstance(error, (commands.CommandNotFound, commands.CheckFailure)): return
    if reply:
        try:
            await ctx.send(reply[0], delete_after=reply[1])
        except Exception:
            pass
        return
    try:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(L('❌ Missing argument: `{}`', error.param.name), delete_after=5)
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(L('❌ Invalid argument!'), delete_after=5)
            return
        if isinstance(getattr(error, "original", None), discord.Forbidden):
            await ctx.send(L("❌ I don't have permission to do that!"), delete_after=6)
            return
        await ctx.send(L('❌ Something went wrong. The bot owner has been notified.'), delete_after=6)
    except Exception:
        pass
    await _report_error(f"{ctx.prefix}{ctx.command}", ctx.author, ctx.guild, getattr(error, "original", error))

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    perm_names = lambda e: ", ".join(p.replace("_", " ").title() for p in e.missing_permissions)
    text = None
    if isinstance(error, app_commands.MissingPermissions): text = L('❌ You need the **{}** permission to use this command.', perm_names(error))
    elif isinstance(error, app_commands.BotMissingPermissions): text = L('❌ I need the **{}** permission first.', perm_names(error))
    elif isinstance(error, app_commands.CommandOnCooldown): text = L('⏳ Slow down! Try again in {}s.', int(error.retry_after) + 1)
    elif isinstance(error, app_commands.NoPrivateMessage): text = L('❌ This command only works in servers.')
    elif isinstance(error, app_commands.CheckFailure): return                    # the check itself already answered
    elif isinstance(original, discord.Forbidden): text = L("❌ I don't have permission to do that!")
    try:
        msg = text or L('❌ Something went wrong. The bot owner has been notified.')
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass
    if text is None:
        await _report_error(f"/{interaction.command.qualified_name if interaction.command else '?'}", interaction.user, interaction.guild, original)

# ============================================================
# REGISTER GROUPS & RUN
# ============================================================
bot.tree.add_command(setup_group)
bot.tree.add_command(rroles_group)

if "--check" in sys.argv:       # `python3 bot.py --check` registers everything without connecting to Discord
    print(f"CHECK OK - prefix commands: {len(bot.commands)}, slash commands: {len(bot.tree.get_commands())}")
    sys.exit(0)

signal.signal(signal.SIGTERM, _on_sigterm)
try:
    bot.run(BOT_TOKEN)
finally:
    flush_now()


