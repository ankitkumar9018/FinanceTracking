# Setting Up Notifications

This guide explains how to configure FinanceTracker to send you alerts when your stocks need attention.

---

## How Notifications Work

When a stock's price enters one of your alert zones (light red, dark red, light green, or dark green), FinanceTracker can notify you through multiple channels:

| Channel | What You Need | Best For |
|---|---|---|
| **In-App** | Nothing -- always active | Seeing alerts when you have the app open |
| **Desktop Push** | Nothing -- just enable it | Getting alerts on your computer even when the app is in the background |
| **Email** | SendGrid account (free) | Daily summaries and non-urgent alerts |
| **Telegram** | Telegram account + bot (free) | Instant alerts on your phone |
| **WhatsApp** | Twilio account | Instant alerts via WhatsApp |
| **SMS** | Twilio account | Critical alerts when other channels are unavailable |

You can use any combination of these. Most users start with in-app + Telegram or in-app + email.

---

## In-App Notifications

These are always active. When an alert triggers:
- A toast notification appears in the top-right corner of the app
- The notification bell icon in the header shows a red badge with the count
- Click the bell to see your notification history

No setup needed.

---

## Desktop Push Notifications

These pop up as native notifications on your computer, even if the app is running in the background.

### Setup

1. Go to **Settings** then **Notifications** then **Desktop Push**
2. Toggle **Enable Push Notifications** to ON
3. Your browser will ask for permission -- click **Allow**
4. Click **Test** to send yourself a test notification

For the desktop app (Tauri), push notifications use your operating system's native notification system and are enabled by default.

---

## Email Notifications

Email is good for daily summaries and less urgent alerts. You need a SendGrid account (free tier gives you 100 emails per day).

### Step 1: Create a SendGrid Account

1. Go to https://sendgrid.com and sign up (free)
2. After verifying your account, go to **Settings** then **API Keys**
3. Click **Create API Key**
4. Choose **Full Access** or **Restricted Access** with Mail Send permission
5. Copy the API key (it starts with "SG.")

### Step 2: Configure in FinanceTracker

1. Go to **Settings** then **Notifications** then **Email**
2. Paste your SendGrid API key
3. Enter the "From" email address (this must be verified in SendGrid)
4. Enter your email address as the recipient
5. Click **Test** to send a test email
6. Check your inbox (and spam folder) for the test email
7. Toggle **Enable Email Notifications** to ON

### What Emails You Will Receive

- **Alert emails**: Sent immediately when a stock enters an alert zone
- **Daily summary** (optional): A morning email summarizing your portfolio status

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
5. BotFather will give you a **bot token** -- it looks like `123456789:ABCdefGhIJklMNopQRSTuvWXYz`
6. Copy this token

### Step 2: Start a Chat with Your Bot

1. In Telegram, search for the bot username you just created
2. Start a chat and send `/start`
3. This is required so the bot knows your Chat ID

### Step 3: Configure in FinanceTracker

1. Go to **Settings** then **Notifications** then **Telegram**
2. Paste the bot token
3. The app will automatically detect your Chat ID (because you messaged the bot)
4. Click **Test** to send a test message to your Telegram
5. Toggle **Enable Telegram Notifications** to ON

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
4. Note your Twilio WhatsApp phone number

### Step 2: Configure in FinanceTracker

1. Go to **Settings** then **Notifications** then **WhatsApp**
2. Enter your Twilio Account SID
3. Enter your Twilio Auth Token
4. Enter the Twilio WhatsApp phone number
5. Enter your personal WhatsApp number as the recipient
6. Click **Test** to send a test message
7. Toggle **Enable WhatsApp Notifications** to ON

---

## SMS Notifications

SMS also uses Twilio. Best reserved for critical alerts only (dark red / dark green) since SMS costs money per message.

### Setup

Same as WhatsApp -- use your Twilio credentials, but enter your Twilio SMS phone number instead.

---

## Alert Routing Rules

You can choose which types of alerts go to which channels. Go to **Settings** then **Notifications** then **Alert Routing**.

### Suggested Configuration

| Alert Type | Channels |
|---|---|
| **Dark Red** (critical, stock at base level) | All channels -- Email + Telegram + WhatsApp + Push |
| **Dark Green** (target reached) | All channels -- Email + Telegram + WhatsApp + Push |
| **Light Red** (caution, lower mid range) | Email + Telegram + In-App |
| **Light Green** (opportunity, upper mid range) | Email + Telegram + In-App |
| **RSI alerts** (overbought/oversold) | Email + In-App |
| **Daily summary** | Email only |

This way, you are not overwhelmed with messages but still get critical alerts through every possible channel.

---

## Notification Cooldown

To prevent being spammed with the same alert, there is a cooldown period. By default, after an alert triggers for a stock, it will not trigger again for the same zone for 60 minutes.

You can change this in **Settings** then **Notifications** then **Cooldown Period**.

---

## Viewing Notification History

All sent notifications are logged. To see your history:

1. Click the **bell icon** in the header
2. Or go to **Settings** then **Notifications** then **History**

The history shows:
- Which stock triggered the alert
- What type of alert (color/zone)
- Which channels were notified
- Whether the notification was delivered successfully or failed
- Timestamp

---

## Troubleshooting

**Notifications not arriving?**
- Check that the channel is enabled (toggle is ON)
- Click **Test** to send a test notification and check for errors
- For email: check your spam folder
- For Telegram: make sure you sent `/start` to your bot
- For WhatsApp: make sure you opted in to the Twilio sandbox

**Getting too many notifications?**
- Increase the cooldown period
- Set routing rules so routine alerts only go to email/in-app
- Disable channels you do not need

---

Need help with something else? Check the [Troubleshooting Guide](../troubleshooting.md) or the [FAQ](../faq.md).
