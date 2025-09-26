# 📖 Palaemon Discord Bot – Instruction Manual

The **Palaemon Bot** is your all-in-one assistant for **disaster alerts**, **crypto price lookups**, **server moderation**, and **community engagement**.  
It’s designed to support **Palaemon Emergency Services** while keeping your Discord active and safe.  

---

## 🔔 Where Things Happen

- **Disaster Alerts (live)** → posted in <#1419729720941088848> every 5 minutes.  
- **Disaster Digest (daily)** → posted in **#general** each morning at the time you configure.  
- **Market Lookups** → `/price` commands, available in any channel.  
- **Admin / Mod Tools** → restricted to users with the right permissions.  
- **Community Engagement** → welcome messages, polls, raids, reaction roles.  

---

## 🧑‍💻 How to Use the Bot (Walkthroughs)

### 🌍 Disaster Alerts
- You don’t need to do anything: alerts flow automatically.  
- Use `/disasters_now` if you want an immediate fetch instead of waiting for the next 5-min cycle.  
- Switch to **digest mode** in `.env` if you only want one bundled update each day.  

### 📊 PAL & Market Prices
- `/price` → shows PAL’s live price from DexScreener (using the contract in `.env`).  
- `/price DOGE` → looks up another token by name.  
- `/price_debug 0xContract` → shows which trading pairs DexScreener found for troubleshooting.  

### 👮 Moderation
- `/role_add @user Disaster Alerts` → give someone a role.  
- `/role_remove @user Disaster Alerts` → take it away.  
- `/purge 20` → delete last 20 messages in the channel.  
- `/kick @user` or `/ban @user` → remove troublemakers.  
- `/slowmode 30` → set 30s slowmode to calm spammy chats.  

⚠️ Note: Only staff with the right **permissions** (Manage Roles, Kick Members, etc.) can run these.  

### 📢 Announcements
- `/announce Big update coming soon!`  
  → Posts an embed with 📣 in the current channel.  
- Only users with **Manage Server** can do this.  

### 🎉 Community Engagement
- **Welcome Messages** → The bot auto-greets new members with a random rotating message.  
- **Reaction Roles** →  
  1. Copy a message link (`Right-click → Copy Message Link`).  
  2. Run `/rr_add [id] 😀 Disaster Alerts`.  
  3. When users click 😀 on that message, they get the role.  
- **Polls** → `/poll "Which exchange first?" "Binance,KuCoin" 15` runs for 15 minutes.  
- **Raids** (Twitter/X pushes):  
  - `/raid_new [url] [title] 30` → creates a raid panel (Like/Retweet buttons).  
  - `/raid_ping` → re-pings raiders.  
  - `/raid_status` → shows progress.  
  - `/raid_end` → ends raid early.  

### 🏓 Utility
- `/ping` → bot health check. Replies with “🏓 Pong!”.  
- `/debug` → show current config (guild, channels, API filters). *Ephemeral.*  
- `/ids` → show current server & channel IDs. *Ephemeral.*  

---

## ⚙️ Slash Command Reference

### 🌍 Disaster
- `/disasters_now` – force fetch & post.  

### 📊 Market
- `/price [query]` – get token price (PAL by default).  
- `/price_debug [query]` – list candidate trading pairs.  

### 👮 Moderation
- `/role_add @user role`  
- `/role_remove @user role`  
- `/role_create name [mentionable]`  
- `/role_delete role`  
- `/purge amount`  
- `/kick @user [reason]`  
- `/ban @user [reason]`  
- `/slowmode seconds`  

### 📢 Admin
- `/announce [message]`  
- `/debug`  
- `/ids`  

### 🎉 Engagement
- `/poll question options time`  
- `/rr_add msgId emoji role`  
- `/rr_remove msgId emoji`  
- `/raid_new url title minutes`  
- `/raid_ping`  
- `/raid_status`  
- `/raid_end`  

### 🏓 Utility
- `/ping`  

---

## 🛠️ Configuration

All settings live in `.env`:  

| Variable               | Description                                       | Default |
|------------------------|---------------------------------------------------|---------|
| `DISCORD_TOKEN`        | Bot login token                                   | —       |
| `GUILD_ID`             | Server ID for syncing commands                    | —       |
| `DISASTER_CHANNEL_ID`  | Channel where disaster updates are posted         | —       |
| `DISASTER_MODE`        | `rt` (real-time) or `digest`                      | `rt`    |
| `DISASTER_POLL_MINUTES`| How often to poll for updates                     | `5`     |
| `DIGEST_TIME_UTC`      | If digest mode, time to post (UTC HH:MM)          | `09:00` |
| `USGS_MIN_MAG`         | Min earthquake magnitude                          | `6.0`   |
| `RELIEFWEB_LIMIT`      | Number of ReliefWeb items to fetch                | `5`     |
| `RELIEFWEB_APPNAME`    | ReliefWeb app identifier                          | `pal-discord-bot` |
| `PAL_TOKEN_ADDRESS`    | Contract for PAL token                            | —       |
| `DEXSCREENER_CHAIN`    | Chain to filter on (e.g. `bsc`)                   | —       |

---

## ✅ Best Practices

- Keep <#1419729720941088848> as **Announcements** so alerts can be shared across Discord.  
- Use `/debug` after editing `.env` to confirm config is loaded.  
- Restart the bot after making changes to `.env`.  
- Move the **bot’s role to the top** of your server’s role hierarchy so it can manage others.  
- Create a **Disaster Alerts** role for people who want pings.  

---

© Palaemon Emergency Services – Powered by $PAL
