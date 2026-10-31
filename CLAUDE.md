# CLAUDE.md — Versa Discord Bot

> Handoff from a long claude.ai chat (July → 31 Oct 2026). Read this fully before touching code.
> **Security:** this repo is PUBLIC. The VPS address is replaced by `<VPS_IP>` below. Never write the token, keys or the real server address into any file here. `handoff.md` / `memory.md` (older notes that name the VPS) stay out of git (`.gitignore`).

---

## 1. Who you are working with

- **Brad** — GitHub `Takizawa747`, Discord `takizawa_747`, bot creator ID `1365571735222747280` (`BOT_CREATOR_ID`).
- Hobbyist developer, Discord server owner/admin. Builds Discord bots in Python.
- **Works from an Android phone with Termux.** Edits with nano (cannot reliably do partial edits). No desktop.
- **Speaks Azerbaijani.** Reply in Azerbaijani. Code, comments, commit messages and bot strings stay in English (bot text is translated via the phrase table, see §5).
- Often writes just **"Davam et" / "Dəvam et"** = "continue": resume the open task from where you stopped, don't restart or re-explain.

### How Brad wants you to work
- **Deliver the whole `bot.py`**, never diffs or "replace line X" instructions — partial edits on mobile break things.
- Big files as a downloadable file, not pasted into chat.
- **Few steps per reply (≈3–5 tool calls).** He complained when one reply took 152 steps. Batch work, don't narrate every step.
- Test before handing over (see §9). Never hand over code that was not compiled + tested.
- Be honest about limits (e.g. what Discord allows), then offer the closest working solution.
- He trusts you to make design decisions ("sənə güvənirəm") — decide, then say in one line what you decided.
- Commands he runs are typed on a phone: give short, copy-pasteable blocks.

---

## 2. The project

**Versa** — all-in-one public Discord bot, Python, discord.py 2.x, one file `bot.py` (~7,300 lines).
Repo: `Takizawa747/versa-bot`. Support server: `https://discord.gg/hxYWsFVWp8`. Application/client ID: `1521047598918533201`.
Bot name stays **Versa** (rename rejected; Orbis/Omnix/Kivo taken). A separate private bot **"Wersa"** for owner/whitelist is planned later.

Features: moderation (ban/kick/softban/mute/timeout/warn/purge/nick/slowmode/lock/lockall/lockdown/resetchannel/massrole, cases, history), leveling (text XP + **voice XP**), virtual economy + store + casino (blackjack, slots, coinflip), tickets, giveaways, polls, reaction roles, counting, flag game, honeypot, modmail, role persist, AFK, welcome, logs, 3 languages (EN/TR/RU), owner DM tools.

**Removed permanently** (don't bring back): music / YTDL / Spotify / playlists (old errors: `YTDLSource has no attribute from_url`, `playlist_group not defined`), Buckshot game, ticket transcripts to owner, `SPECIAL_USERS`, the "moderation" feature switch.

---

## 3. Current state (31 Oct 2026, after V3)

- Code lives in GitHub now (`bot.py`, `dev-tools/`, `fx/`); work branch `claude/new-session-k2c61b`.
- `bot.py` ≈ **8,650 lines**, all **10 test suites green** (new: `test_v3`), static check 0 errors, all 495 `L()` templates translated TR/RU, `--check` OK.
- **Needs discord.py ≥ 2.6** (store/inventory use Components V2 `LayoutView`); older versions stop with a clear "pip install -U discord.py" message.
- **Not yet tested on live Discord**: V2 round (ticket editor fix, `/ticket add`, log panel, DM policy, exact permissions) and the whole V3 round (below). First live run is the real test.
- Token was removed from code. Bot refuses to start without `token.txt` (or env `VERSA_TOKEN`). `--check` works without a token.

---

## 4. Hosting / deploy

- **Oracle Cloud Free Tier VPS**, Frankfurt, ARM, 6 GB RAM: `ubuntu@<VPS_IP>`, folder `~/mybot/`.
- Brad downloads `bot.py` to `~/storage/downloads/` on the phone and sends it from Termux:
```bash
scp -i ~/mybot/oracle.key ~/storage/downloads/bot.py ubuntu@<VPS_IP>:~/mybot/bot.py
ssh -i ~/mybot/oracle.key ubuntu@<VPS_IP>
cd ~/mybot && python3 bot.py --check        # prints prefix/slash counts, no Discord connection
```
- Working SSH key was recovered as `~/storage/shared/ssh-key-2026-09-05.key` (the same-named file in Downloads is a DIFFERENT key).
- Runs in `screen` today. `versa.service` (systemd, `Restart=always`) is prepared — recommend switching; before that `pkill -f "python3 bot.py"; screen -wipe` or two bots run (this happened once: duplicate replies).
- Token: `read -s T && printf '%s' "$T" > token.txt && chmod 600 token.txt; unset T` (never `echo` it). The old token leaked into chats → must be **reset** in the Developer Portal if not done yet.
- Deps: `pip install -U discord.py Pillow --break-system-packages` (discord.py must be ≥ 2.6; Pillow is optional - without it games fall back to text). (PyNaCl on Termux ARM needed `SODIUM_INSTALL=system`; not needed now — no voice playback.)
- GitHub blocks pushes containing tokens — never put the token in any file.

---

## 5. Architecture (know this before editing)

- **Storage:** SQLite (WAL) with in-memory write-behind cache. `load_json()/save_json()` are the cache API; getters (`get_settings/get_econ/get_warns/get_user_xp`) call `touch()`; `flush_loop` writes touched rows every 3 s; SIGTERM handler flushes. `load_json()` is idempotent (returns the live dict) and `reload_bans()` is a no-op — **never swap a live dict for a re-read copy** (that was the `banuser` bug).
- Stores include: settings, economy, levels, msgstats (message counts: today/7d/30d/total), warns, cases, bot_bans (`banned`, `restricted`, `servers`, `dm_optout`), schedule, polls, flag scores, role persist…
- **Language:** `set_lang(guild_id)` sets a ContextVar; `L("English text", *args)` looks up `_PHRASE_TABLE` (`EN ||| TR ||| RU` per line). Every new user-facing string → add TR+RU lines. `check.py` warns about untranslated `L()` templates.
- **BaseView / VersaTree:** block bot-banned users/servers, set language, rate-limit (6 cmd / 5 s).
- **Timers:** `schedule_task("unban"|"unmute"|"giveaway"|"poll", …)` persisted, run by `scheduler_loop` — survive restarts.
- **Features:** `/setup feature` toggles (`FEATURE_LABELS`, `DEFAULT_FEATURES`). Off by default: counting, vcxp, dmnotices.
- **`/setup` group is at 25/25 subcommands (Discord max).** Anything new under setup must merge/move something or start a new group.
- **Lock system:** snapshot-based (`lock_snapshots`, `hide_snapshots`), exact restore. Overwrites changed **per target via `set_permissions`** (needs only Manage Roles), never `channel.edit(overwrites=…)`. Lockall/lockdown must be undone newest-first (`mass_order`), enforced. Nobody gains access they didn't have (`_held`).
- **Voice XP:** bot NEVER joins voice. Uses voice state only: mic+headphones on, ≥2 eligible people, not AFK channel/timeout/.afk/stage listener, daily cap 4 h, `/setup vc` (multi-channel panel), `/setup vcxpdiff` (7 presets), `/vcxp` shows rules + privacy statement.
- **Owner tools are DM-only** (`handle_owner_dm`, `DM_COMMANDS`): banuser (menu: full ban or per-feature restriction), unbanuser, bannedusers, banserver/unbanserver/bannedservers/leaveserver/servers, add/remove/set/resetmoney, add/remove/set/resetlevel, addxp/removexp, saydm, sayin, supsearch, supstats, userdata, stealemoji, setstatus, backup, whitelist. Whitelist groups: bans, money, levels, messaging, info, all. Moderation is never whitelistable.
- **deletedata** (DM, anyone): 14 categories of a user's own data; moderation records never deletable.
- **Help:** dropdown categories + "📋 All commands" page built live from the command tables (can't go stale).
- **FX engine (in bot.py, from `fx/blk_fx1.py`):** `FX_OK` (Pillow optional), `fx_run()` (worker thread, max 2 at once, timeout), `_Cv` canvas. Renderers: `render_slots` (GIF), `render_coin` (GIF), `render_bj_table` / `render_hl` (PNG, own drawn cards: suits are polygons, Versa card back). `_fx_attach()` returns `[]` when Pillow is missing, the channel denies Attach Files (`_can_attach`) or rendering fails → callers show the text version.
- **Card games:** `active_bj[user_id]` holds ANY running card game (blackjack table, blackjack invite, higher-lower) → one at a time per user; deletedata "games" clears it.
- **Store/inventory UI:** `StoreLayout` / `InventoryLayout` (`BaseLayout` = LayoutView with BaseView's checks), 6 items per page (Discord max 40 components/message), `buy_store_item()` / `use_store_item()` shared by buttons and `.buy`.

### Policies decided with Brad
- **No DMs unless asked.** `send_dm()` sends only if the moderator adds `-dm` to the command, the server enabled "📨 Moderation DMs" feature, or the owner ticks "Notify by DM" in the banuser menu. `/dms off` always wins.
- **No appeal / support-server link** in ban or restriction messages (Brad: don't show our server as appeal server).
- **Nothing is sent to the owner when the bot joins a server, and no invite is ever created** (top.gg declined-risk + Brad's wish). Banned servers are just left.
- **No owner permission bypass** in server commands — Brad must hold real permissions like everyone else.
- **Exact permissions:** each command checks the user's specific permission and the bot's (`bot_has_permissions`), e.g. lock = Manage Roles, purge = Manage Messages, timeout = Moderate Members. Never Administrator.
- Bot-banned users: chat untouched; a bot command gets one silent self-deleting reply (≤1/min); no DM.
- Private servers are shown only as "Private server …1234" in owner tools.

---

## 6. top.gg / Discord verification

- Bot is in the **top.gg review queue**. Checklist in `TOPGG_CHECKLIST.md`. Already fixed: invite creation removed, broken `https://https://` link, unused cigarette/beer emoji table, `Intents.all()` → only members + message_content, DM attribution + opt-out, clear permission errors, `@Versa` mention reply, status `.help | /help`.
- **Invite link (no Administrator):**
  `https://discord.com/oauth2/authorize?client_id=1521047598918533201&permissions=1374792576214&scope=bot%20applications.commands`
  Put it in: Developer Portal → **Installation** → Install Link = "Custom URL" (or Guild Install scopes `bot`+`applications.commands` with those permissions), and in the top.gg bot page invite field. Recalculate the integer if a command needs a new permission.
- Developer Portal: Public Bot ON, OAuth2 Code Grant OFF, Message Content ON, Server Members ON, Presence OFF.
- **Discord app verification is missing 3 criteria:** app must belong to a **Team**, needs a **Terms of Service URL** and a **Privacy Policy URL**. ToS/Privacy drafts + static site exist (`privacy_policy.md`, `terms_of_service.md`, `site/` via `dev-tools/make_site.py`) → host on GitHub Pages and paste the URLs. Privacy policy still lacks: message counters, daily voice-XP count, `/dms` opt-out, voice-state reading.

---

## 7. OPEN WORK — do these next (Brad's latest requests, in his words summarised)

Status after V3: **done** = 3 (store/inv buttons), 4 (.work per language), 6 (forceban); 2 partly (Higher-Lower + multiplayer blackjack done, one more game left); 1 partly (cards, slots GIF, coin GIF are in; banners/rank/level-up/leaderboard cards and the application-emoji set are not).

1. **Custom visuals everywhere, no stock emoji/GIFs.** *(V3: blackjack + higher-lower use own drawn cards (PNG per action), `.slots` / `.cf` send the approved GIF then edit to the final frame. Still to do: integrate `fx/blk_fx2.py` (mod banners, rank, level-up, leaderboard cards), draw the sprite set + application emojis + `EMO` map. Buttons keep their emoji in the `emoji=` argument so they can be swapped to `EMO[...]` later.)* Brad finds default Unicode emojis unprofessional. Wants Versa's own emoji set (wallet, bank, coin, money, cards, slots symbols, mod actions, tickets, etc.) and animations:
   - Prototypes exist in `fx/` (`blk_fx1.py`: optional-Pillow engine, `fx_run` thread pool, animated **slot machine GIF** with own drawn symbols, **coin flip GIF**; `blk_fx2.py`: animated **moderation banners** (ban/kick/timeout/mute/warn/pardon), **rank card**, **level-up card**, **leaderboard card**). Previews were approved in chat. **Not yet integrated into bot.py.** Slot symbol "777 machine" was drawn by us, but Brad wants every symbol fully ours (no emoji-like look).
   - Plan: draw a sprite set (PNG 128 px) → upload as **application emojis** (Developer Portal → Emojis, up to 2,000, usable in any server without Use External Emojis) → central `EMO = {...}` map → replace Unicode emojis in embeds/buttons. Keep a Unicode fallback if an emoji ID is missing.
   - **Blackjack: own drawn cards** (render the table as an image per action) instead of the card emojis.
2. **Casino additions:** *(V3 done: `.hl` and `.bj @a @b <bet>`. Left: one more game.)*
   - **Higher-Lower** `.hl <bet>`: show a card, buttons Higher / Lower (and cash-out between rounds). Payout from real probability with house edge: e.g. card 3 → "lower" is unlikely → big multiplier; "higher" is likely → tiny multiplier (well under 2x). Formula: `mult = (1 - edge) / P(win)`, ties lose or push (decide, document).
   - **Multiplayer blackjack:** `.bj @u1 @u2 @u3 <bet>` (up to 4 players incl. host; 1-player still works). Invite embed with Accept/Decline buttons, starts when all invited accept (timeout → start with those who accepted or cancel), everyone pays the bet, turns go player by player — only the current player can press Hit/Stand/Double; then dealer plays.
   - At least one more game (ideas: roulette, crash, mines, dice). All with own visuals.
   - **As built:** Higher-Lower: every rank equally likely on each draw (endless shoe), A high, **ties lose**, `mult = floor((1 - 0.03) / P(win), 2 decimals)` → 97% per guess, impossible side disabled, cash out any time, idle 120 s = auto cash out, auto cash out at ×1000. Blackjack table: 1–4 players, 2-deck shoe for groups, invite Accept/Decline (60 s; host's "Start now"; nobody → refund), bets taken on accept, turn order = invite order, 45 s per turn then auto-stand, natural pays 2.5× immediately (same as before), dealer hits to 17.
3. ~~**Store/inventory buttons:**~~ *(V3 done)* `.estore` shows items with a **Buy button under each item**. **Delete `useitem` command**; `.inv` shows items with quantity and a **Use button** under each owned item. Update help, tests, translations.
4. ~~**`.work` creative per language:**~~ *(V3 done: `WORK_LINES` en/tr/ru, 18 own lines each)* random funny jobs, different joke sets per language (TR memes for Turkish servers, EN memes for English, RU for Russian — e.g. "held the master's water bottle at the construction site" style). Not just translations — culturally different lines.
5. **Tickets → select menu + modal:** replace panel buttons with a **Select menu**; choosing an option opens a **modal (title + description)**; admins can fully customise options (label, description, **any emoji incl. custom**), allow **attachments** (after opening, user can upload files in the ticket channel; or modal file upload if supported by the library version — check). Keep `/ticket add` / `/ticket remove` (done) for adding higher mods.
6. ~~**`forceban <user_id> [reason]`**~~ *(V3 done: `.forceban <id|@> [1d] [reason]`, alias `hackban`; refuses members above you/the bot, already-banned users; never DMs)* — ban by ID even if the user isn't in the server (`guild.ban(discord.Object(id))`), Ban Members, case log, optional `-dm` not possible if not shared (skip).
7. **Language audit:** find any user-facing text not going through `L()` / untranslated, and any mixed-language responses; fix all.
8. **Docs:** update `COMMANDS.md`, README, SETUP, GUIDE (stale: still mention music, Spotify, botperm, old invites), privacy policy additions (§6), the "Versa — bütün əmrlər" doc.
9. Choose avatar (cube variants in `avatars/final/`, recommended `cube_indigo.png`) and upload.
10. Later: test bot (separate Discord app + separate folder in Termux), Wersa private bot, maybe web dashboard. Make `/setup warnpunish` defaults match the published warn system (3→timeout 24h, 5→ban 3d, 7→ban 1m, 10→perm).

---

## 8. Done in the chat (chronological, short)

- Security patches (role hierarchy, self-ban, negative amounts, ticket spam limit); interactive `.lock` with role choice + exact unlock.
- 3-language system (EN/TR/RU); SQLite migration; AutoSharded; rate limits; scheduler.
- Ticket panel editor; Polls v2; slots paytable (RTP 94.45%, jackpot x300); fair coinflip (SystemRandom); rob (30 min cd, caught = −70% wallet); flag game (197 built-in countries); counting v2; `parse_amount` (all/half/quarter/%, 1.5k/2m, TR/RU words).
- deletedata panel; honeypot; banuser fix + test; static site; 30+ avatar drafts.
- Owner commands moved to DM; per-feature restrictions; lockall/unlockall/lockdown/unlockdown (Manage Server, panels, exact restore).
- Voice XP; message counts in `/rank`; top.gg compliance; `/dms`; help "All commands".
- V2 (latest): ticket editor 400 error fixed (invalid emoji in select → validated + saved buttons auto-repaired, fallback without emojis; 3rd-button "failed" fixed), `/ticket add|remove` (member or role), no appeal links, no join DM/invite, DM opt-in policy (`-dm`/`-nodm`, "Moderation DMs" feature, banuser "Notify by DM" toggle), exact per-command permissions, no owner bypass, **`/setup logsettings` panel** (27 events in 6 categories, click to toggle, category/all buttons) + new listeners (voice join/leave/move, timeout, boost, channel/role edit, emoji, invites, threads, mod cases).

---

- **V3 (31 Oct, Claude Code):** project imported to GitHub; store/inventory with Buy/Use buttons under every item (`useitem` deleted); `.hl` Higher-Lower; multiplayer `.bj`; `.forceban`; `.work` per-language jokes; FX engine + own drawn cards in bot.py; animated `.slots` / `.cf`; text fallback when Pillow/Attach Files is missing; `test_v3.py`; dev-tools default to `../bot.py`.

## 9. Testing workflow (mandatory)

```bash
python3 dev-tools/check.py bot.py          # syntax, undefined names, duplicates, slash limits, untranslated L()
for t in selftest selftest2 test_db test_dd test_bans test_dm_commands test_topgg test_vcxp test_v2 test_v3; do python3 dev-tools/$t.py || echo FAIL $t; done
```
- Tests load functions from `bot.py` via AST (`seg("name", …)`) with fake Discord objects; they default to `bot.py` next to `dev-tools/`, `BOT_SRC=path` env picks another file. `test_v3` also builds the real views with discord.py and renders the pictures with Pillow (skips those parts if missing). When behaviour changes intentionally, update the test in the same change.
- Patch with AST helpers (`dev-tools/astpatch.py`: `func_text`, `replace_top`, `patch_in_func`, `delete_command`, `delete_top`) or exact-string replacements that assert match count == 1. Insert new blocks above the `# EVENTS` banner.
- Work on a copy, run everything, copy to the delivery path only when all green.

## 10. Mistakes made before — do not repeat

- `str.replace` patches with `\n` inside strings broke code; a regex "clean-up" silently deleted 740 lines (on_ready then crashed → slash commands never synced).
- Substring search was mistaken for "definition exists" checks.
- `load_json` re-read swapped the live dict → bans lost.
- Old builds crashed on start with `NameError: BOT_CREATOR_ID` (definition order) and `playlist_group` — always run `--check` and import-order checks.
- Emojis in SelectOption must be real emojis (Discord 400 `Invalid emoji`).
- Discord limits: 25 options/select, 25 fields/embed, 5 buttons/row, 5 rows, 100 chars option label, 25 subcommands/group, 2000 chars message, 4096 embed description.
- Forgot to send files as cards once — always deliver the finished file.

## 11. Files

`bot.py`, `CLAUDE.md`, `handoff.md` + `memory.md` (older notes, Azerbaijani ledger - git-ignored, not in the repo), `TOPGG_CHECKLIST.md`, `versa.service`, `privacy_policy.md`, `terms_of_service.md/.txt`, `server_rules.txt`, `site/`, `dev-tools/` (check, tests, astpatch, make_site), `fx/` (visual prototypes + preview GIFs/PNGs), `avatars/`.
Stale docs: `README.md`, `README.txt`, `SETUP.md`, `COMMANDS.md`, `VERSA_BOT_COMPLETE_GUIDE.md`.
