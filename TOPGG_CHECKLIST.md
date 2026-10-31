# Versa - top.gg qəbul yoxlama siyahısı

Mənbə: top.gg-nin rəsmi **Discord Bot Guidelines** səhifəsi (5 sentyabr 2026-da yenilənib) və **How the Project Reviewal Process Works** səhifəsi.
Qaydalar dəyişə bilər, göndərməzdən əvvəl bir də bax: https://support.top.gg/hc/en-us/articles/23146912808988-Discord-Bot-Guidelines

## 1. Reviewer botu necə yoxlayır
- Bot **onlayn, public və invite edilə bilən** olmalıdır; əsas funksiya və əmrlərin əksəriyyəti işləməlidir.
- Bot top.gg-nin test serverinə **icazə = 0** ilə girir. `@everyone` rolunda yalnız bunlar var: View Channels, Change Nickname, Send Messages, Threads, Embed Links, Attach Files, Add Reactions, Use External Emojis, Read Message History, Use Application Commands, səs icazələri.
  **Manage Messages / Channels / Roles, Kick, Ban, Moderate Members, Audit Log yoxdur.** Bunlar lazım olan əmrlər aydın xəta mesajı verməlidir (verir) və səhifədə qeyd olunmalıdır.
- Reviewer ilk pozuntunu görən kimi yoxlamanı dayandırıb **decline** edə bilər. Eyni səbəblə 3 dəfə decline olsan, top.gg-dən qadağa var ("three strikes").
- Növbə 1 həftə və ya daha çox çəkə bilər. Nəticə e-poçtla və top.gg Discord serverində (#mod-logs) bildirilir.

## 2. Bu versiyada koddan düzəldilənlər
1. **Join zamanı daimi, limitsiz invite yaradılırdı** (`create_invite`). Tam silindi. Owner bildirişi artıq invite, server sahibi və private serverin adını göstərmir.
   Dürüst qeyd: bu konkret maddə top.gg-nin dərc olunmuş siyahısında ayrıca yazılmayıb; Discord ToS/Developer qaydalarına riayət tələbi və "siyahıda olmayan səbəblərə görə də decline hüququ" altına düşür. Hər halda risklidir, ona görə silindi.
2. **Qırıq dəstək linki**: `https://https://discord.gg/...` help, appeal və ban mesajlarında göstərilirdi. Düzəldildi.
3. **`ITEM_EMOJIS` (cigarette, beer, saw, handcuffs)**: heç yerdə işlənməyən ölü kod idi. Qayda: narkotik, dərman və aksesuarları "heç bir formada" təsvir etmək olmaz; içki/tütün də riskli sayıla bilər. Silindi. Avtomatik test bütün mənbə kodunda belə sözləri axtarır.
4. **`Intents.all()`** əvəzinə yalnız lazım olanlar (members, message content). Presence intent lazım deyildi, söndürüldü.
5. **Moderasiya DM-ləri** (kick, warn, ban, mute, timeout, ticket, honeypot): "server heyəti adından Versa göndərdi (anonim)" qeydi + **`/dms off`** opt-out. Qayda: bir istifadəçini digərinə DM etdirən əmrlər müəllifi və ya anonimliyi bildirməli və block/opt-out təklif etməlidir.
6. `@Versa` yazanda cavab verir, `@Versa help` işləyir, status `.help | /help`.
7. **Xəta mesajları**: icazə çatmayanda səssiz qalmaq və ya "bir şey səhv getdi + owner-a hesabat" əvəzinə aydın mesaj (prefix və slash).
8. **Help**: "📋 All commands" səhifəsi canlı əmr cədvəlindən qurulur (heç vaxt köhnəlməz). `/setup` siyahısı dəqiqləşdi (artıq olmayan `features` silindi, `vc` və `vcxpdiff` əlavə olundu). `{p}help`, `{p}vcxp`, `{p}dms` əlavə olundu.
9. Yoxlama: `dev-tools/test_topgg.py` bunların hamısını hər dəyişiklikdən sonra yoxlayır.

## 3. Qaydalar və bizim vəziyyət
| Qayda | Vəziyyət |
|---|---|
| Administrator tələb olunmamalıdır | Uyğundur. Kodda heç bir yerdə tələb olunmur, invite-də Administrator yoxdur. |
| Əmr yalnız özünə lazım olan icazəni tələb etsin | Uyğundur. Hər əmr özünü yoxlayır, çatmayanda aydın mesaj verir. |
| Aydın giriş nöqtəsi (işləyən help) | Uyğundur: `.help`, `/help`, "All commands", `@Versa`. |
| Owner əmrləri developerlərə kilidli | Uyğundur. Hamısı yalnız DM-də və yalnız whitelist-dəkilər üçün. Kodda `eval/exec` yoxdur. |
| DM göndərən əmrlər: müəllif/anonimlik + block/opt-out | Düzəldildi (bənd 5). |
| NSFW | Uyğundur. NSFW əmr və ya şəkil yoxdur. |
| Narkotik, dərman, içki/tütün | Düzəldildi (bənd 3). |
| Vote kilidi / vote xatırlatması | Uyğundur. Heç biri yoxdur. |
| Başqa botun forku olmamalı | Uyğundur (öz kodundur). |
| İstifadəçidən login/token istəməmək | Uyğundur. |
| Copyright faylları paylaşmamaq | Uyğundur. |
| API rate limit | Uyğundur (kütləvi əmrlər gözləmə ilə, log token-bucket). |
| Onlayn, public, invite edilə bilən | **Sənin işin**, aşağıda. |

## 4. SƏNİN etməli olduqların (koddan kənar)
**A. Developer Portal -> Bot:** Public Bot **ON**; Requires OAuth2 Code Grant **OFF**; Message Content Intent **ON**; Server Members Intent **ON**; Presence Intent **OFF** (artıq lazım deyil).
(Bot 100 serverə çatanda Members və Message Content intent-ləri üçün Discord verifikasiyası lazım olacaq.)

**B. Invite linki (Administrator YOX):**
`https://discord.com/oauth2/authorize?client_id=APP_ID&permissions=1374792576214&scope=bot%20applications.commands`
`APP_ID` yerinə botun Application ID-sini yaz. Bu dəyər: View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Use External Emojis, Manage Messages, Manage Channels, Manage Roles, Kick, Ban, Moderate Members, Manage Nicknames, View Audit Log, Send Messages in Threads.
Bot səs kanalına girmir, ona görə Connect/Speak yoxdur; invite yaratmır, ona görə Create Invite yoxdur.

**C. 24/7 onlayn:** bot reviewer baxanda oflayndırsa decline olur. `versa.service` faylı (screen əvəzinə) açılışda başladır, çökəndə yenidən qaldırır. Quraşdırma addımları faylın başındadır.

**D. top.gg bot səhifəsi:** prefix **`.`** yaz (səhv prefix decline səbəbidir); təsvir spam/doldurma olmasın, NSFW olmasın; rəqib bot siyahılarını reklam etmə; düymələr əlaqəli linklərə getsin; seizure yarada bilən GIF qoyma; dəstək linki `https://discord.gg/hxYWsFVWp8` işləməlidir.

**E. Privacy Policy və Terms:** GitHub Pages-də yayımla və linkləri həm Developer Portal-da, həm top.gg səhifəsində göstər.
DİQQƏT: yeni məlumatlar (mesaj sayğacları, günlük səs XP sayı, `/dms` opt-out, səs vəziyyətinin oxunması) siyasətə əlavə olunmalıdır. Bu hələ edilməyib.

**F. Reviewer notes (kopyalayıb yapışdır):**
> Prefix: `.` (or @mention). `.help` / `/help` list everything; the "All commands" page lists every command. The bot never joins voice channels and never creates invites. Moderation commands (ban, kick, mute, purge, lock...) and some /setup features need permissions that top.gg's test server does not grant by default (Manage Messages, Manage Channels, Manage Roles, Kick, Ban, Moderate Members); without them the bot replies with a clear permission message. Owner tools are DM-only and locked to the developer. Voice XP is opt-in: /setup feature -> Voice XP, then /setup vc. Moderation DMs are anonymous staff notices and users can stop them with /dms off. Support: https://discord.gg/hxYWsFVWp8

## 5. Reviewer kimi özün sına
Yeni boş server aç, botu `...&permissions=0&scope=bot%20applications.commands` ilə dəvət et və bunları yoxla:
`.help`, `/help` (hər kateqoriya + "All commands"), `@Versa`, `.ping`, `.bal`, `.daily`, `.rank`, `/vcxp`, `.flag`, `.ban @biri` (icazə mesajı gəlməlidir), `/setup view`, `/dms off`, `/dms on`.

## 6. Qeyd
Decline olsan səbəbi top.gg Discord serverində #mod-logs kanalında görəcəksən; düzəldib yenidən göndər. Eyni səbəblə 3 dəfə decline = qadağa, ona görə səbəbi dəqiq düzəlt.
