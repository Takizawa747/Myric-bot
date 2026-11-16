# Privacy Policy

**Last Updated:** November 15, 2026

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
- **Server stats** — on servers where *Server Stats* is on (it is on by default; a server's admins can switch it off on the dashboard, and then nothing is counted), the Bot keeps numbers per server and per day (UTC) for the last 30 days, shown with `/stats`: how many messages you sent and in which channels, how long you were in which voice channel, and, if the Bot has the *Manage Server* permission there, which invite code you joined with and who created it (so `/stats` can show the top invites and inviters). Only numbers, channel IDs and invite codes are kept - never what you wrote or said. Bots and the server's AFK channel are never counted. Older builds kept a per-member message count for `/rank`; it is no longer collected and the old numbers are removed automatically after 30 days
- **Flag game score** — number of correct answers
- **Giveaway entries** — your user ID in the list of participants
- **Poll votes** — your user ID and the option you chose, while the poll exists
- **Suggestions** — on servers that turned on *Suggestions*: the text you send with `/suggest` or `.suggest` (it is also posted in the server's suggestion channel), your user ID, the user IDs of the people who voted for or against it, and the staff decision (status, reason and the ID of the staff member who decided). Kept until 180 days after the last vote or decision. The message itself stays in the server's channel, like any message.
- **Starboard** — on servers that turned on the *Starboard*: when a message gets enough of the chosen reaction, the Bot reposts it (author name and picture, text, first picture, links to other files, a link to the original) in the server's starboard channel and remembers which original belongs to which repost and how many reactions it had - no user IDs. The repost is removed when the original is deleted or falls below the threshold; the record is kept for 180 days. A message from an age-restricted (NSFW) channel is never reposted into a channel without that mark, and a message from a channel @everyone cannot see is never reposted into a channel @everyone can see.
- **Role panels** (buttons / select menus that give roles) — the Bot stores the panel (channel, message, roles, texts) and the ID of the person who made it; it stores nothing about the members who press the buttons, it only gives or takes the roles.
- **top.gg votes** — when you vote for Myric on top.gg, top.gg sends your Discord user ID to the Bot (or, when you press *Claim my reward*, the Bot asks top.gg whether that ID voted). The Bot keeps the time of your last vote, how many times you voted and your vote streak, whether you asked for vote reminders and when the next one is due, up to 3 rewards that wait to be claimed, and the server where you last used `/vote` (the coins go into your wallet there). Reminders are DMs only for people who pressed *Remind me every 12 hours*; after three unanswered reminders they pause, and they stop with *Stop reminders*, with `/dms off` or when your DMs are closed
- **DM preference** — if you turn off DMs from the Bot with `/dms` or `.dms`, your user ID is kept on the opt-out list so the Bot never DMs you
- **Saved roles** — only if a server turned on *Role Persist*: the role IDs of a member who left, kept up to 60 days so they can be restored if the member returns
- **Moderation records** — warnings, bans, kicks, mutes, timeouts and softbans, each with the reason, the moderator's ID, the time, and the Discord username of the member and of the moderator *at that time*. If a message is sent in a server's *honeypot* channel, the first 150 characters of that message are saved in the reason
- **Scheduled actions** — timers for temporary bans, timed mutes and giveaways (user ID, server ID, due time) until they run
- **Server configuration** — chosen channels, roles, prefix, language, feature switches, store items, reaction roles and the counting channel's current number, and the protection settings a server chose on the dashboard (automod rules and word lists, triggers, anti-nuke rules with the IDs of the people the owner trusts, anti-raid and verification) A trigger also keeps the user ID of the person who made it, so it only answers where that person may write. The texts a server writes for its welcome, leave and level-up messages and for its announcements are stored with the settings; a scheduled announcement also keeps the user ID of the person who scheduled it, so it is only posted while that person may still write in its channel. Announcements are deleted when they are removed on the dashboard, and one-time announcements right after they were posted. A server can also choose its own log channel for each kind of log. Giveaways and polls can also be started from the dashboard; they store the same data as when they are started in Discord, plus the ID of the person who started them. On the dashboard's *Cases* page, the people who can open that server's dashboard (the owner, members with *Manage Server*, and anyone the owner gave team access to the Cases page) can see the server's moderation records; members with *Moderate Members* can correct a reason (the old reason and who changed it are kept with the case, at most the last 5) and remove a single warning. Ban, kick, mute and timeout history is never deleted there, and every such change is written to the server's log channel (when the server has one), even when its case or dashboard logs are switched off. Myric Support never opens this page.
- **Anti-nuke (only on servers that turned it on)** — when anti-nuke takes the roles away from someone who went over one of the server's limits (for example deleting many channels in a short time), it keeps that member's role IDs, their Discord username at that time, the reason and the time, so the server's owner can give the roles back with one click. This note is removed as soon as the roles are given back or the owner removes it on the dashboard; a server keeps at most 50 of them
- **Anti-raid (only on servers that turned it on)** — while raid mode is on, a short note about it: when it started and ends, how many people joined and were handled, what the Bot changed (for example locked channels or paused invites, so exactly that can be undone) and where its alert message is. It holds no user IDs and is removed when raid mode ends
- **Verification** — the Bot stores nothing about the person who verifies: it only gives the chosen roles
- **Bot restrictions** — users and servers that are banned from the Bot or limited in some features, with the reason, who set it, when, and when it ends (temporary bans end by themselves), and the Bot's list of trusted staff (ID, username and their permissions)
- **Deletion requests** — when you ask us to delete your data: your user ID and the date of the request, so it is handled within 30 days (see section 6)
- **Tickets** — the ticket owner's ID is written into the ticket channel's topic inside the server. The title, description and files you enter in the ticket form are posted into that ticket channel, inside Discord; the Bot does not keep a copy

### 2.3 Temporary data (memory only, erased on restart)
AFK status and message (per server), the voice channel you are in and since when (for the server stats, while you are in voice), the invite codes of a server and how often each was used (to see which invite a new member used; only where the Bot has *Manage Server*), command cooldowns, rate-limit counters, running games and dashboard login sessions (see 2.6). On servers that use the protection features also: automod's short memory of each member's last messages (only the time, the channel, the number of files and a scrambled fingerprint of the text to spot repeated messages - never the text itself; at most 30 messages, forgotten about 5 minutes after the member's last message), anti-nuke's counters of recent actions (who did what and when), anti-raid's list of the newest joins (user ID and time) and how often someone picked the wrong icon in the verification.

### 2.4 Messages
The Bot reads messages in servers only to detect commands, award XP, count messages for the server stats, run the counting and honeypot channels and, on servers that turned them on, to check messages against the server's automod rules and triggers (automatic answers). This check happens in memory, at the moment the message arrives. **Ordinary message content is not stored by the Bot.** The exceptions are:
- **Automod** — when automod acts on a message, the server's own log channel gets the rule that matched and a short excerpt of the message (at most 300 characters). An automod warning is saved like any other warning, with the rule's name as the reason - not the message.
- **Log channels** — if a server enables logging, the Bot posts edited and deleted message content and files (taken from Discord's short-lived cache), and who deleted them when Discord's audit log shows it, into that server's own staff log channel. It stays inside Discord under the server's control; the Bot does not keep a copy.
- **Direct messages and /modmail** — messages you send to the Bot in DMs or with `/modmail` reach the Myric team so you can be answered. They are stored for **30 days** in the Bot's database (your user ID, the text, the names and links of attached files, where you wrote from — "DM" or the server, private servers without their name — and the team's answers), so the team can read and answer them on the admin panel. After 30 days they are deleted automatically; you can ask for earlier deletion (section 6). Answers come by DM, signed "Myric team", and follow your `/dms off` setting.
- **Tickets** — ticket conversations stay inside Discord. The Bot does not create or keep transcripts.

### 2.5 Voice and pictures
- **Voice:** the Bot never joins voice channels and never hears or records audio. For Voice XP it only reads the voice state Discord shares with bots (which voice channel you are in and whether you are muted or deafened), and only on servers that turned Voice XP on.
- **Voice time for stats:** on servers where *Server Stats* is on, the same voice state is used to count how long members are in each voice channel (bots and the AFK channel never count, at most 24 hours per visit). Only the time is kept (see 2.2).
- **Pictures:** rank, level-up, leaderboard and stats cards are drawn from your current display name and avatar when they are shown. The pictures and avatars are not stored.

### 2.6 Web dashboard (login with Discord)
Server admins can change the Bot's settings on the dashboard (for example `dash.myricbot.com`). You log in with Discord ("Login with Discord", OAuth2). The dashboard asks Discord only for two things:
- **identify** — your user ID, username, display name, avatar and language setting
- **guilds** — the list of servers you are in, with your permissions there. It is used **only** to show you the servers where you have the *Manage Server* permission, or where the server gave you team access (see 10). It is not stored in the database, and nobody else (not the owner, not staff) can see it.

What happens with it:
- The access key Discord gives the dashboard is used once during the login and then thrown away. We never get your password or e-mail.
- Your login is kept as a **session in the Bot's memory only** (user ID, name, avatar, the list of servers you can manage, the IDs of other servers you share with the Bot, a security token and the kind of browser you use, for example "Chrome" - no version, no device details). It ends when you log out, after 7 days, when the Bot restarts, or when the same cookie shows up in another kind of browser. Staff logins also end after 12 hours without use. It is never written to the database or into backups.
- **One cookie:** `myric_sid`, a random session number. It is HttpOnly (scripts cannot read it), Secure (only over HTTPS) and SameSite=Lax, and lasts at most 7 days. There are no advertising or tracking cookies, and no analytics.
- Every change is checked against your **real, current permissions** in that server (Manage Server, or the team access the server gave you; Manage Roles for reaction roles), with the same rules as the Bot's commands. Each change is posted in that server's own log channel (who changed which part), if the server uses logs.
- The dashboard server sees your IP address while you use it, like every website. It is used only in memory to limit too many requests (and to pause an address for 15 minutes after many refused requests) and is not logged or stored.
- You can remove the dashboard's access any time in Discord: *User Settings -> Authorized Apps*.

### 2.7 Anonymous usage counts
To see which features are used and keep the Bot healthy, the Bot counts per day **how often each command was used (only the command's name)**, how many commands failed, how many servers and members it has in total, and how many servers added or removed it. It also counts how many servers switched each feature on and which language they use. These numbers contain **no user IDs and no server IDs**, cannot be linked to a person, and are kept for 90 days.

### 2.8 Admin audit log
Myric Support visits of a server's dashboard (at most one entry per hour) and every change the support team makes there are recorded the same way (see 10). When the Bot owner or a trusted staff member uses an owner tool (for example a Bot ban, a balance change or an answer to a modmail), the action is recorded: who did it (ID and name), what was done, the target (for example a user ID or a server) and when. This keeps the team accountable. The log is kept for **180 days** and, like moderation records, is not removed on a deletion request.

## 3. How We Use Your Information

Only to provide Bot features: economy, leveling, games, moderation, server protection (automod, anti-nuke, anti-raid, verification), triggers, welcome and leave messages, announcements, tickets, giveaways, polls, suggestions, starboard, role panels, reaction roles, counting, honeypot protection, role persist and server settings (in Discord and on the dashboard).

**We do not:**
- sell, rent or share your data with third parties
- use your data for advertising or profiling
- read private conversations

## 4. Where Data Is Stored and Who Can Access It

- Data is stored in a database on a dedicated, private cloud server in the **European Union (Germany)**. Only the Myric team can access it, over encrypted connections.
- The database is backed up automatically once a day to a private, access-restricted location, so no data is lost if the server fails. **Backups older than 7 days are deleted automatically.**
- Access: the Bot owner. A few trusted staff members may use limited owner tools, each only with the permission the owner gave them (for example looking up a Discord account's public details — name, ID, account age and Bot restrictions — adjusting a balance or level, or reading and answering modmail). Staff never act on themselves or on other staff, every staff action is in the audit log (2.8), and they cannot access the database file. **We do not look up or list which servers a person is in, and we do not build profiles of users.** (The dashboard shows a logged-in person their own servers only, see 2.6.)
- **Test copy:** the developers run a private test copy of the Bot on a private test server before changes reach Myric. It keeps its own, separate test data in a private test environment and is only used by the developers.
- The server is protected with key-based SSH access, and the Bot's login token and the dashboard's client secret are kept outside the public code.

## 5. Data Retention

- Economy, level, game and giveaway data: kept while the Bot is in use, until you ask us to delete it.
- Finished giveaways: removed after 7 days. Closed polls: removed after 30 days.
- Suggestions: removed 180 days after the last vote or decision. Starboard records: removed after 180 days (the reposts stay in the channel unless the original is deleted or loses its reactions).
- Server stats (messages, voice time, invites): each day's numbers are removed automatically after 30 days.
- Message counts of older builds: removed automatically 30 days after the last counted message.
- Voice XP day counter: reset every day.
- Saved roles (Role Persist): removed after 60 days.
- Roles kept by anti-nuke: removed when they are given back or the server's owner removes them (at most 50 per server).
- Anti-raid note: removed when raid mode ends.
- top.gg vote data: kept while the Bot is in use, until you ask us to delete it.
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
- **Deletion** — ask us on the support server or write to the Bot in a direct message (it reaches the Myric team). We delete the data the Bot stores about you — economy (wallet, bank, inventory, cooldown times), XP and level, message counts, server stats (your messages, voice time and the invites you used or created), flag game score, saved roles, giveaway entries, poll votes, your votes on suggestions (your own suggestions stay because they were posted publicly, but your user ID is removed from them), AFK status, top.gg vote data, a running game, stored modmail messages and temporary rate-limit data — within 30 days. Only the Bot owner can delete data, so nobody can delete someone else's data. We cannot delete moderation records (see section 5).
- **Correction** — ask us to correct data that is wrong.

If you are in the EU or UK you also have the rights granted by the GDPR. Our legal basis is our legitimate interest in running and securing the Bot, and the legitimate interest of server communities in keeping moderation records.

To use these rights, contact us on the support server.

## 7. Children's Privacy

You must be old enough to use Discord (at least 13, or higher where your country requires it). We do not knowingly collect data from anyone younger. If you believe a child has given us data, contact us and we will remove it.

## 8. Third-Party Services

- **Discord API** — subject to [Discord's Privacy Policy](https://discord.com/privacy)
- **flagcdn.com** — the flag game shows flag pictures hosted there (Discord loads the picture); no user data is sent
- **top.gg** — the bot list where you can vote for Myric. When you vote, top.gg sends your Discord user ID (and whether its weekend bonus is on) to the Bot; when you press *Claim my reward*, the Bot sends your Discord user ID to top.gg to ask whether you voted. What you do on top.gg itself is covered by top.gg's privacy policy
- **Our cloud hosting provider (EU)** — runs the server the Bot and the dashboard run on; it only stores the data for us and does not use it for anything else
- **Cloudflare** — the dashboard is reached through a Cloudflare Tunnel (encrypted HTTPS; the server's own address stays hidden), and the static website `myricbot.com` is hosted by Cloudflare (no cookies, no trackers, no analytics). Cloudflare passes the requests on and does not get any data from the Bot's database

## 9. Security

We take reasonable measures to protect stored data: encrypted HTTPS for the dashboard, a random `state` check in the Discord login, a security token on every change (CSRF protection), strict content and security rules for the dashboard pages, sessions tied to your kind of browser, a pause for addresses that send many refused requests, the admin panel's code sent only to the Myric team, two-factor authentication for the team's sensitive tools, and permission checks on every request. No system is completely secure, so we cannot guarantee absolute security.

## 10. Server Administrators

Administrators who add the Bot to a server are responsible for informing their members about the data the Bot handles, for example by linking this policy.

Who can open a server's Myric settings on the dashboard:
- The server owner and members with the *Manage Server* permission.
- **Team access:** roles or people the owner (or a member with Manage Server) chose, only for the dashboard pages they were given. Anti-nuke and the access settings can never be handed out this way. Their changes appear in the server's log channel with their name.
- **Myric Support:** Need help? The Myric support team can open your Myric settings to fix things for you. They only see and change Myric's own settings — never your messages, members, roles or channels. Every change is written to your log channel. You can switch this off at any time.
  - The switch is called **Myric Support access** (dashboard, General page). It is on by default. While it is on, a support team member with the matching permission (and two-factor authentication on their Discord account) can change Myric's settings for your server. Anti-nuke, the access settings and a full reset are never changed by support.
  - Viewing the settings (read only) stays possible for the support team even when the switch is off, so we can answer your questions and check reports of misuse of the Bot. Nothing is changed while the switch is off.
  - In your log channel a support change appears as "Myric Support" with the settings that changed. Inside the Myric team, every visit (at most one entry per hour) and every change is recorded in the admin audit log with the team member's ID (see 2.8).

## 11. Changes to This Policy

We may update this policy. Significant changes will be announced on the support server. The date at the top shows the latest version.

## 12. Contact Us

- **Support Server:** https://discord.gg/hxYWsFVWp8
- **GitHub:** github.com/Takizawa747/Myric-bot

---

*This Privacy Policy applies to the Myric Discord Bot.*
