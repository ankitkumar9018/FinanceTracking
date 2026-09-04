# Setting Up Notifications

This guide explains how to configure FinanceTracker to send you alerts when your stocks need attention.

---

## Read this first: where credentials live

**FinanceTracker has no screen for entering API keys.** SendGrid keys, Twilio
credentials and Telegram bot tokens are *server* configuration: they go in
`backend/.env` (or real environment variables) and are read **once, at backend
startup**. Changing one requires restarting the backend.

The **Settings → Notifications** panel in the app does only four things:

1. turns each channel on or off,
2. stores your **phone number** (used by WhatsApp and SMS),
3. stores your **Telegram chat ID** (typed in by you — it is not auto-detected),
4. shows a **Test Email** / **Test Telegram** button once the matching
   server-side key is present.

If you are running the packaged **desktop app**, the sidecar reads the same
`backend/.env` file that ships beside it — see [desktop-app.md](../desktop-app.md#external-services-notifications-and-ai)
for the exact location on each platform.

---

## How Notifications Work

When a stock's price enters one of your alert zones (light red, dark red, light green, or dark green), FinanceTracker can notify you through several channels:

| Channel | What the server needs | Best For |
|---|---|---|
| **In-App** | Nothing — always available | The notification bell in the header |
| **Email** | `SENDGRID_API_KEY` + `EMAIL_FROM` | Daily summaries and non-urgent alerts |
| **Telegram** | `TELEGRAM_BOT_TOKEN` + your chat ID | Instant alerts on your phone |
| **WhatsApp** | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_WHATSAPP_FROM` + your phone number | Instant alerts via WhatsApp |
| **SMS** | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_SMS_FROM` + your phone number | Critical alerts when other channels are unavailable |

There is **no desktop/browser push channel** and no broker-side notification —
those five are the whole list.

---

## In-App Notifications

Always available, no setup.

- The **bell icon** in the header shows a badge counting alerts triggered since
  you last opened it.
- Click the bell to see the recent triggered-alert history (it is backed by
  `GET /alerts/history` and refreshes live over the WebSocket).
- There is no pop-up toast for triggered alerts — the badge is the signal.

---

## Email Notifications

Email is good for daily summaries and less urgent alerts. You need a SendGrid account (the free tier gives you 100 emails per day).

### Step 1: Create a SendGrid Account

1. Go to https://sendgrid.com and sign up (free)
2. After verifying your account, go to **Settings** then **API Keys**
3. Click **Create API Key**
4. Choose **Full Access**, or **Restricted Access** with the Mail Send permission
5. Copy the API key (it starts with `SG.`)
6. Verify a sender address in SendGrid — SendGrid rejects mail from an
   unverified `From`

### Step 2: Put the key in `backend/.env`

```bash
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=alerts@yourdomain.com     # must be verified in SendGrid
```

Restart the backend. Alerts are sent to **your account's login email** — there
is no separate recipient field.

### Step 3: Turn it on in the app

1. Go to **Settings → Notifications**
2. Tick **Email Notifications**
3. Click **Save Changes**
4. A **Test Email** button appears once the server has a SendGrid key — click it
   and check your inbox (and spam folder)

---

## Telegram Notifications

Telegram is the recommended channel for instant alerts on your phone. It is completely free.

### Step 1: Create a Telegram Bot

1. Open Telegram on your phone or computer
2. Search for **@BotFather** and start a chat
3. Send the command: `/newbot`
4. Follow the prompts:
   - Give your bot a name (e.g., "My FinanceTracker Alerts")
   - Give your bot a username (e.g., "my_finance_alerts_bot")
5. BotFather will give you a **bot token** — it looks like `123456789:ABCdefGhIJklMNopQRSTuvWXYz`

### Step 2: Find your Chat ID

The app does **not** discover this for you.

1. In Telegram, search for the bot username you just created and send it `/start`
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and
   read `result[0].message.chat.id`

   *(or simply message `@userinfobot`, which replies with your numeric ID)*

### Step 3: Put the token in `backend/.env`

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJklMNopQRSTuvWXYz
```

Restart the backend.

### Step 4: Turn it on in the app

1. Go to **Settings → Notifications**
2. Tick **Telegram Notifications** — a **Telegram chat ID** field appears
3. Type the numeric chat ID from Step 2 into it
4. Click **Save Changes**
5. Click **Test Telegram** (shown once the server has a bot token)

> A global `TELEGRAM_CHAT_ID` in `.env` acts as a fallback for users who have
> not set their own; the per-user value always wins.

### What Telegram Messages Look Like

When an alert triggers, you will receive a message like:

> **ALERT: HDFC Bank (HDFCBANK.NS)**
>
> Price entered LOWER MID RANGE
> Current Price: 1,580.00
> Lower Mid Range: 1,500.00 - 1,600.00
>
> Action may be needed.

---

## WhatsApp Notifications

WhatsApp notifications use Twilio, which is a paid service (they offer a free trial).

### Step 1: Set Up Twilio

1. Go to https://www.twilio.com and create an account
2. Activate the WhatsApp sandbox (for testing) or request a WhatsApp business number
3. Note your **Account SID** and **Auth Token** from the Twilio dashboard
4. Note your Twilio WhatsApp sender number

### Step 2: Put the credentials in `backend/.env`

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

Restart the backend.

### Step 3: Turn it on in the app

1. Go to **Settings → Notifications**
2. Tick **WhatsApp Notifications** — a **Phone number** field appears
3. Enter *your* number in E.164 format (e.g. `+9198XXXXXXXX`)
4. Click **Save Changes**

There is no Test button for WhatsApp or SMS — trigger a real alert to verify.

---

## SMS Notifications

SMS also uses Twilio. Best reserved for critical alerts only, since SMS costs money per message.

Same as WhatsApp, but set `TWILIO_SMS_FROM` (a plain `+1...` number, no
`whatsapp:` prefix) instead of `TWILIO_WHATSAPP_FROM`, and tick **SMS
Notifications**. The phone-number field is shared between the two.

---

## Which alert goes to which channel

Routing is **per alert**, decided when you create it — not a global matrix.

1. Go to the **Alerts** page and click **New Alert**
2. Fill in the stock, type and threshold
3. Pick one channel in the **Notify Via** dropdown (In-App, Email, Telegram,
   WhatsApp or SMS)

Each alert therefore notifies through exactly one channel. To change it, delete
the alert and recreate it, or call `PUT /alerts/{alert_id}/channels` directly —
that endpoint accepts a *list*, so API users can fan one alert out to several
channels at once. There is no Settings → Alert Routing panel.

> **The Settings toggles do not gate stock alerts.** They control which channels
> the daily **AI portfolio digest** is delivered on (in-app always, plus every
> channel you ticked). A stock alert always goes to the channel stored on the
> alert itself.

A practical setup:

| Alert | Suggested channel |
|---|---|
| **Dark Red** (critical, stock at base level) | Telegram or SMS |
| **Dark Green** (target reached) | Telegram |
| **Light Red / Light Green** (mid-range) | Email or In-App |
| **RSI alerts** (overbought/oversold) | In-App |
| **AI digest** | Whatever you tick in Settings |

---

## Notification Cooldown

To prevent being spammed with the same alert, a triggered alert will not fire
again for **5 minutes**.

This is a fixed constant — `ALERT_COOLDOWN_SECONDS = 300` in
`backend/app/services/alert_service.py`. It is **not** a setting, an env var, or
adjustable from the UI. Changing it means editing that constant and restarting
the backend.

Alerts also require a *rising edge*: a condition that simply stays true does not
re-notify, and one-shot alerts deactivate themselves after they fire.

---

## Viewing Notification History

All sent notifications are logged. To see your history, click the **bell icon**
in the header. There is no Settings → Notifications → History panel.

The history shows:
- Which stock triggered the alert
- What type of alert (color/zone)
- The message that was sent
- When it triggered

> **Logs are kept indefinitely.** Nothing prunes the notification log or old
> chat sessions automatically — see [security.md](../security.md#data-retention).

---

## Troubleshooting

**Notifications not arriving?**
- Check the channel is selected on the *alert itself* (Alerts page → **Notify Via**), not just ticked in Settings
- Check the server-side credential is actually set: if **Settings → Notifications** shows no **Test Email** / **Test Telegram** button, the backend has no SendGrid key / bot token
- Confirm you restarted the backend after editing `backend/.env`
- For email: check your spam folder, and that `EMAIL_FROM` is verified in SendGrid
- For Telegram: make sure you sent `/start` to your bot and typed the right chat ID
- For WhatsApp: make sure you opted in to the Twilio sandbox and your phone number is in E.164 format

**Getting too many notifications?**
- Delete and recreate noisy alerts on a quieter channel (In-App or Email)
- Delete alerts you no longer need — the 5-minute cooldown is not adjustable

---

Need help with something else? Check the [Troubleshooting Guide](../troubleshooting.md) or the [FAQ](../faq.md).
