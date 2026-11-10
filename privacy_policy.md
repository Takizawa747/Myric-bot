# Privacy Policy

**Last Updated:** November 10, 2026

## 1. Introduction

This Privacy Policy explains what **Myric** ("the Bot", "we", "us") stores, why, and what you can do about it when you use the Bot on Discord and its web dashboard (the website where server admins change the Bot's settings). By using the Bot you agree to the practices described here. This policy applies to the Bot only, not to any Discord server that uses it.

## 2. Information We Collect

### 2.1 Identifiers
- **Discord User IDs** — to attach economy, level, game and moderation data to the right person
- **Server (Guild), Channel, Role, Message and Emoji IDs** — for server settings, giveaways, reaction roles, tickets and logs

We do **not** collect e-mail addresses, passwords, payment details or voice audio, and we do not store IP addresses (see 2.6).

### 2.2 Data stored when you use Bot features
- **Economy** — virtual wallet and bank balance, the store items in your inventory, and the times you last used the daily, work and rob commands, and how many mini-game wins paid coins today (a daily limit). The coins are virtual: they have no real-world value and cannot be bought, sold or cashed out
- **XP and level** — experience earned from messages (only on servers where leveling is enabled) and, on servers that turned on *Voice XP*, from time spent talking in voice channels; for this the Bot keeps how many voice XP you earned today (reset every day, at most 4 hours a day count)
- **Message counts** — on servers where leveling is enabled, the number of messages you sent per day for the last 30 days and a running total, shown in `/rank`. Only the numbers are kept, never what you wrote
- **Flag game score** — number of correct answers
- **Giveaway entries** — your user ID in the list of participants
- **Poll votes** — your user ID and the option you chose, while the poll exists
- **DM preference** — if you turn off DMs from the Bot with `/dms` or `.dms`, your user ID is kept on the opt-out list so the Bot never DMs you
- **Saved roles** — only if a server turned on *Role Persist*: the role IDs of a member who left, kept up to 60 days so they can be restored if the member returns
- **Moderation records** — warnings, bans, kicks, mutes, timeouts and softbans, each with the reason, the moderator's ID, the time, and the Discord username of the member and of the moderator *at that time*. If a message is sent in a server's *honeypot* channel, the first 150 characters of that message are saved in the reason
- **Scheduled actions** — timers for temporary bans, timed mutes and giveaways (user ID, server ID, due time) until they run
- **Server configuration** — chosen channels, roles, prefix, language, feature switches, store items, reaction roles and the counting channel's current number
- **Bot restrictions** — users and servers that are banned from the Bot or limited in some features, with the reason, who set it, when, and when it ends (temporary bans end by themselves), and the Bot's list of trusted staff (ID, username and their permissions)
- **Deletion requests** — when you ask us to delete your data: your user ID and the date of the request, so it is handled within 30 days (see section 6)
- **Tickets** — the ticket owner's ID is written into the ticket channel's topic inside the server. The title, description and files you enter in the ticket form are posted into that ticket channel, inside Discord; the Bot does not keep a copy

### 2.3 Temporary data (memory only, erased on restart)
AFK status and message, command cooldowns, rate-limit counters, running games and dashboard login sessions (see 2.6).

### 2.4 Messages
The Bot reads messages in servers only to detect commands, award XP, count messages and run the counting and honeypot channels. **Ordinary message content is not stored by the Bot.** The exceptions are:
- **Log channels** — if a server enables logging, the Bot posts edited and deleted message content and files (taken from Discord's short-lived cache), and who deleted them when Discord's audit log shows it, into that server's own staff log channel. It stays inside Discord under the server's control; the Bot does not keep a copy.
- **Direct messages and /modmail** — messages you send to the Bot in DMs or with `/modmail` reach the Myric team so you can be answered. They are stored for **30 days** in the Bot's database (your user ID, the text, the names and links of attached files, where you wrote from — "DM" or the server, private servers without their name — and the team's answers), so the team can read and answer them on the admin panel. After 30 days they are deleted automatically; you can ask for earlier deletion (section 6). Answers come by DM, signed "Myric team", and follow your `/dms off` setting.
- **Tickets** — ticket conversations stay inside Discord. The Bot does not create or keep transcripts.

### 2.5 Voice and pictures
- **Voice:** the Bot never joins voice channels and never hears or records audio. For Voice XP it only reads the voice state Discord shares with bots (which voice channel you are in and whether you are muted or deafened), and only on servers that turned Voice XP on.
- **Pictures:** rank, level-up and leaderboard cards are drawn from your current display name and avatar when they are shown. The pictures and avatars are not stored.

### 2.6 Web dashboard (login with Discord)
Server admins can change the Bot's settings on the dashboard (for example `dash.myricbot.com`). You log in with Discord ("Login with Discord", OAuth2). The dashboard asks Discord only for two things:
- **identify** — your user ID, username, display name, avatar and language setting
- **guilds** — the list of servers you are in, with your permissions there. It is used **only** to show you the servers where you have the *Manage Server* permission. It is not stored in the database, and nobody else (not the owner, not staff) can see it.

What happens with it:
- The access key Discord gives the dashboard is used once during the login and then thrown away. We never get your password or e-mail.
- Your login is kept as a **session in the Bot's memory only** (user ID, name, avatar, the list of servers you can manage and a security token). It ends when you log out, after 7 days, or when the Bot restarts. It is never written to the database or into backups.
- **One cookie:** `myric_sid`, a random session number. It is HttpOnly (scripts cannot read it), Secure (only over HTTPS) and SameSite=Lax, and lasts at most 7 days. There are no advertising or tracking cookies, and no analytics.
- Every change is checked against your **real, current permissions** in that server (Manage Server; Manage Roles for reaction roles), with the same rules as the Bot's commands. Each change is posted in that server's own log channel (who changed which part), if the server uses logs.
- The dashboard server sees your IP address while you use it, like every website. It is used only in memory to limit too many requests and is not logged or stored.
- You can remove the dashboard's access any time in Discord: *User Settings -> Authorized Apps*.

### 2.7 Anonymous usage counts
To see which features are used and keep the Bot healthy, the Bot counts per day **how often each command was used (only the command's name)**, how many commands failed, how many servers and members it has in total, and how many servers added or removed it. It also counts how many servers switched each feature on and which language they use. These numbers contain **no user IDs and no server IDs**, cannot be linked to a person, and are kept for 90 days.

### 2.8 Admin audit log
When the Bot owner or a trusted staff member uses an owner tool (for example a Bot ban, a balance change or an answer to a modmail), the action is recorded: who did it (ID and name), what was done, the target (for example a user ID or a server) and when. This keeps the team accountable. The log is kept for **180 days** and, like moderation records, is not removed on a deletion request.

## 3. How We Use Your Information

Only to provide Bot features: economy, leveling, games, moderation, tickets, giveaways, polls, reaction roles, counting, honeypot protection, role persist and server settings (in Discord and on the dashboard).

**We do not:**
- sell, rent or share your data with third parties
- use your data for advertising or profiling
- read private conversations

## 4. Where Data Is Stored and Who Can Access It

- Data is stored in a SQLite database on a private virtual server hosted by **Oracle Cloud in Frankfurt, Germany (EU)**.
- A backup of the database is sent once a day as a zip file to the Bot owner's private Discord DMs. **Backups older than 7 days are deleted automatically.**
- Access: the Bot owner. A few trusted staff members may use limited owner tools, each only with the permission the owner gave them (for example looking up a Discord account's public details — name, ID, account age and Bot restrictions — adjusting a balance or level, or reading and answering modmail). Staff never act on themselves or on other staff, every staff action is in the audit log (2.8), and they cannot access the database file. **We do not look up or list which servers a person is in, and we do not build profiles of users.** (The dashboard shows a logged-in person their own servers only, see 2.6.)
- **Test copy:** the developers run a private test copy of the Bot on a private test server before changes reach Myric. It keeps its own, separate test data on the owner's device and is only used by the developers.
- The server is protected with key-based SSH access, and the Bot's login token and the dashboard's client secret are kept outside the public code.

## 5. Data Retention

- Economy, level, game and giveaway data: kept while the Bot is in use, until you ask us to delete it.
- Finished giveaways: removed after 7 days. Closed polls: removed after 30 days.
- Message counts: daily counts older than 30 days are removed automatically; the total is kept until you ask for deletion.
- Voice XP day counter: reset every day.
- Saved roles (Role Persist): removed after 60 days.
- Backups: removed after 7 days.
- Modmail messages (DMs and `/modmail`): removed after 30 days.
- Anonymous usage counts: removed after 90 days.
- Admin audit log: removed after 180 days.
- Bot bans and restrictions: a temporary one ends at its end time and its reason is removed with it; a permanent one is kept like a moderation record.
- Deletion requests: removed 90 days after they were handled.
- Dashboard sessions: end on logout, after 7 days or when the Bot restarts (memory only).
- **Moderation records** (warnings, bans, mutes, timeouts, kicks, case history, Bot bans): kept for the safety of servers. Deleting them on request would let anyone erase their own record, so they are not removed on request. If you think a record is wrong, contact the server's staff or us.
- If the Bot is removed from a server its data is not deleted automatically (it is kept in case the Bot is added again). Server administrators can reset the Bot's configuration on the dashboard (*Reset*) or with `/setup reset`, and can ask us to remove other server data.

## 6. Your Rights

- **Access** — ask us what the Bot stores about you.
- **Deletion** — ask us on the support server or write to the Bot in a direct message (it reaches the Myric team). We delete the data the Bot stores about you — economy (wallet, bank, inventory, cooldown times), XP and level, message counts, flag game score, saved roles, giveaway entries, poll votes, AFK status, a running game, stored modmail messages and temporary rate-limit data — within 30 days. Only the Bot owner can delete data, so nobody can delete someone else's data. We cannot delete moderation records (see section 5).
- **Correction** — ask us to correct data that is wrong.

If you are in the EU or UK you also have the rights granted by the GDPR. Our legal basis is our legitimate interest in running and securing the Bot, and the legitimate interest of server communities in keeping moderation records.

To use these rights, contact us on the support server.

## 7. Children's Privacy

You must be old enough to use Discord (at least 13, or higher where your country requires it). We do not knowingly collect data from anyone younger. If you believe a child has given us data, contact us and we will remove it.

## 8. Third-Party Services

- **Discord API** — subject to [Discord's Privacy Policy](https://discord.com/privacy)
- **flagcdn.com** — the flag game shows flag pictures hosted there (Discord loads the picture); no user data is sent
- **Oracle Cloud** — hosts the server the Bot and the dashboard run on
- **Caddy** with a free **Let's Encrypt** certificate — makes the dashboard connection encrypted (HTTPS); no user data is shared
- **GitHub Pages** — hosts the static website `myricbot.com` (no cookies, no trackers, no analytics)

## 9. Security

We take reasonable measures to protect stored data: encrypted HTTPS for the dashboard, a random `state` check in the Discord login, a security token on every change (CSRF protection), strict content rules for the dashboard pages, and permission checks on every request. No system is completely secure, so we cannot guarantee absolute security.

## 10. Server Administrators

Administrators who add the Bot to a server are responsible for informing their members about the data the Bot handles, for example by linking this policy. Only members with the *Manage Server* permission in a server can change its settings on the dashboard; the Bot owner has no special access there.

## 11. Changes to This Policy

We may update this policy. Significant changes will be announced on the support server. The date at the top shows the latest version.

## 12. Contact Us

- **Support Server:** https://discord.gg/hxYWsFVWp8
- **GitHub:** github.com/Takizawa747/Myric-bot

---

*This Privacy Policy applies to the Myric Discord Bot.*
