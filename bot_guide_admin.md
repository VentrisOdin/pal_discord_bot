# 🛠️ Palaemon Discord Bot – Admin / Moderator Manual

This document covers **admin-only operations**, setup, and best practices.

---

## 📦 Core Setup

### Environment highlights (`.env`)
- `DISCORD_TOKEN`, `GUILD_ID`, `OWNER_ID`
- Channels: `GENERAL_CHANNEL_ID`, `DISASTER_CHANNEL_ID`, `VERIFY_REVIEW_CHANNEL_ID`
- Disasters: `DISASTER_MODE` (`rt`/`digest`), `DISASTER_POLL_MINUTES`, `USGS_MIN_MAG`, `USGS_PING_MAG`, `DIGEST_TIME_UTC`, `RELIEFWEB_*`
- Market: `PAL_TOKEN_ADDRESS`, `DEXSCREENER_CHAIN`
- Leveling:
  - Curve: `LEVEL_BASE=100`, `LEVEL_EXP=1.5`
  - XP: `LEVEL_COOLDOWN_SEC`, `LEVEL_XP_MIN`, `LEVEL_XP_MAX`
  - Daily/streaks: `LEVEL_DAILY_BONUS`, `LEVEL_STREAK_PCT`, `LEVEL_STREAK_MAX`
  - Ladder: `LEVEL_ROLE_*` (e.g., `LEVEL_ROLE_5=Responder`)
  - Behavior: `LEVEL_KEEP_PREVIOUS=false`
  - Optional boosts: `LEVEL_CHANNEL_BOOSTS=channelId:multiplier,...`
- Guides (optional): `PUBLIC_GUIDE_PATH`, `ADMIN_GUIDE_PATH`

> After editing `.env`, **restart the bot**. Use `/debug` to verify active config.

---

## 🧩 Channel & Role Bootstrapping
- The bot can **auto-create** key channels on startup (general, disaster-alerts, verification review) if missing (requires *Manage Channels*).
- Create ladder roles quickly:
  - `/roles_bootstrap` — creates missing roles for the XP ladder and core roles (e.g., *Disaster Alerts*, *Raiders*).

> Ensure the bot’s role is **above** all roles it needs to assign.

---

## 🔔 Disasters

### Automatic
- Polls USGS, ReliefWeb, EONET, GDACS on a schedule.
- **Real-time mode** (`rt`): posts items as they arrive.
- **Digest mode**: collects and posts a daily digest at `DIGEST_TIME_UTC`.

### Commands
- `/disasters_now` — manual fetch & post
- `/status` — watcher status (last poll, filters, source toggles)

### Tips
- Use `USGS_PING_MAG` to @role ping only for big quakes (set the role name in `ALERT_ROLE_NAME`).
- Keep disaster alerts in a dedicated channel (can be set as *Announcements*).

---

## 💱 Market

- `/price` — looks up PAL (from `PAL_TOKEN_ADDRESS`) or any query (symbol/address).
- `/price_debug` — lists candidate pairs from DexScreener to troubleshoot.

---

## 🎮 Leveling / Gamification

- Awarded by message activity with cooldown to prevent spam.
- `/daily` gives a base bonus; **streaks** add +% up to a cap.
- **Ladder roles** come from `LEVEL_ROLE_*`.  
- Keep only the **highest** rank by setting `LEVEL_KEEP_PREVIOUS=false`.

### Commands
- `/rank`, `/top`, `/daily`, `/titles`, `/level_curve`
- Admin utility: `/level_givexp @member 250` to reward events

### Optional
- Channel XP boosts: define `LEVEL_CHANNEL_BOOSTS` (e.g., general 2× during launch).

---

## 👮 Moderation

- **Roles**: `/role_add`, `/role_remove`, `/role_create`, `/role_delete`
- **Chat**: `/purge`, `/slowmode`
- **Members**: `/kick`, `/ban`

> Requires the respective Discord permissions (Manage Roles, Kick Members, etc.).

---

## 🎉 Engagement

- **Announcements**: `/announce "Message..."` — Posts an embed to current channel.
- **Reaction Roles**:
  1) Copy **message link**  
  2) `/rr_add <messageId> 😀 <Role>`  
  3) Users react 😀 to self-assign the role  
  - Remove: `/rr_remove <messageId> 😀`
- **Polls**:
  - `/poll "Question" "Option A,Option B,Option C" 15` (minutes)  
  - Close early: `/poll_close <messageId>`

---

## ⚡ Raids (Social Pushes)

- Create: `/raid_new <url> <title> <minutes>`  
- Ping participants: `/raid_ping`  
- Status: `/raid_status`  
- End: `/raid_end`  
- Mark completed: `/raid_done`  

> Use the **Raiders** role (opt-in) to avoid pinging everyone.

---

## ✅ Verification (Pros)

- Queue: `/verify_queue`  
- Approve: `/verify_approve @user`  
- Deny: `/verify_deny @user`  
- Review channel: set `VERIFY_REVIEW_CHANNEL_ID`.  
- Verified roles list in `.env`: `VERIFIED_ROLES=Paramedic (Verified),Doctor (Verified),...`

---

## 🧰 Utilities

- `/debug` — shows live config values (ephemeral)
- `/ids` — shows server & channel IDs (ephemeral)
- `/help` — command index for all loaded cogs
- `/guide` — public quick start (DMs public manual)
- `/admin_guide` — staff quick start (DMs admin manual)

---

## Best Practices
- Keep bot token secret; regenerate if leaked.
- Use a **separate “bot admin” channel** for testing changes.
- Pin the **public guide** (or post `/guide`) in your general channel for new members.
- Audit roles and bot permissions after big changes.

---

© Palaemon Emergency Services – Powered by $PAL
