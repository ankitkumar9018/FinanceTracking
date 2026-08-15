# Using the AI Assistant

This guide explains how to use the AI chatbot in FinanceTracker to ask questions about your portfolio in plain, everyday language.

---

## What Is the AI Assistant?

The AI assistant is like having a knowledgeable friend who knows everything about your portfolio. You can ask it questions in plain English (or any language), and it will analyze your portfolio data to give you answers.

**Important**: The AI assistant is an optional feature. Everything else in FinanceTracker works perfectly without it.

---

## How to Open the Chat

There are two ways:
1. Click **AI Assistant** in the sidebar menu
2. Click the chat bubble icon in the bottom-right corner of any page

The chat panel opens on the right side of the screen.

---

## What You Can Ask

Here are some examples of questions the AI can answer:

### About Your Portfolio

- "How is my portfolio doing?"
- "What is my total portfolio value?"
- "Which stocks am I making the most profit on?"
- "What is my best performing stock this month?"
- "Which stocks are in the red?"
- "Show me my top 5 holdings by value"

### About Specific Stocks

- "What is the current price of Reliance?"
- "What is the RSI of TCS?"
- "How has HDFC Bank performed in the last 30 days?"
- "Is Infosys overbought or oversold?"
- "When did I buy my first shares of Wipro?"

### About Alerts and Actions

- "Which stocks need action right now?"
- "Are any of my stocks near their base level?"
- "Which stocks are approaching their top level?"
- "Show me all stocks with RSI below 30"

### About Tax

- "How much STCG tax will I owe this year?"
- "Which stocks become LTCG eligible in the next 3 months?"
- "Should I sell any stocks for tax harvesting?"
- "What is my total dividend income this year?"

### About Risk and Analysis

- "What is my portfolio's Sharpe ratio?"
- "Am I too concentrated in any one stock?"
- "What is the risk level of my portfolio?"
- "Compare my portfolio performance to Nifty 50"

### General Financial Questions

- "What does RSI mean?"
- "Explain Bollinger Bands simply"
- "What is the difference between STCG and LTCG?"

---

## Tips for Getting Good Answers

1. **Be specific**: "What is the RSI of RELIANCE.NS?" works better than "How is Reliance?"
2. **Use stock symbols when possible**: The AI recognizes symbols like TCS.NS, SAP.DE better than just company names
3. **One question at a time**: Ask one clear question rather than a long paragraph with multiple questions
4. **Start a new chat for new topics**: If the conversation gets long, click "New Chat" to start fresh

---

## Asking the Assistant to Do Things

Besides answering questions, the assistant can help you **record a transaction**, **add a new holding**, or **create an alert**:

- "Buy 10 TCS at 3500"
- "Add 50 shares of Infosys at an average price of 1450"
- "Alert me if Reliance goes above 3000"

**It never does any of this on its own.** When it recognises one of these requests, it replies with a plain summary of exactly what it would do -- "Buy 10 TCS (NSE) at 3500 on 2026-08-15." -- and waits. You click **Confirm** to go ahead, or **Dismiss** to throw it away and change nothing.

What keeps this safe:

- The assistant **proposes; you confirm**. The model can never change your data by itself.
- When you confirm, the details are **checked again on the server** and the holding or portfolio is re-checked as yours.
- The change is made through the **same code as manual entry**, so the same rules apply -- you still cannot sell more than your ledger says you hold.
- If the stock is not in your portfolios, or you hold it in more than one place, it tells you and sets nothing up rather than guessing.
- A proposal **expires after 15 minutes**, and at most **5** can be waiting in a conversation at once. If one expires, just ask again.

This needs a connected AI model. Without one, use the normal Holdings, Transactions, and Alerts screens.

---

## Your Portfolio Digest

The digest is a short written round-up of your portfolio -- total invested versus current value, overall profit and loss, your biggest positions, notable gainers and losers, and any concentration flags.

- **Generate one any time** from the AI Assistant area; the newest one is stored so you can reopen it.
- **Or schedule it**: **Off**, **Daily**, or **Weekly** (weekly digests go out on Mondays). Scheduled digests are delivered through your usual notification channels -- in-app always, plus email, Telegram, WhatsApp, or SMS if you have those turned on.

**The digest works even with no AI model connected.** It is assembled from your own computed numbers first; a model is only ever asked to rewrite those numbers into nicer prose. If no model is available (or it is too slow), you still get the numbers-only version, and the digest reports its provider as `none`.

---

## AI in Reports and Alerts

- **Reports**: when exporting the HTML report or PDF you can opt in to a short **AI summary** at the top. It is slower and needs a connected model -- and if the model is unavailable, the report exports exactly as normal, just without the summary.
- **Alerts**: a triggered alert notification can carry **one short AI sentence** explaining what the trigger means. It is tightly time-boxed, so a slow model never delays your alert, and it is skipped silently if AI is unavailable.

---

## AI Providers

The AI assistant can use different language models. You choose which one in Settings.

### Ollama (Default -- Free, Private, Local)

This runs entirely on your computer. Your data never leaves your machine.

- **Model**: Llama 3.2
- **Cost**: Free
- **Privacy**: Complete -- nothing sent to the internet
- **Speed**: Depends on your computer (4-8GB RAM recommended)
- **Setup**: Install Ollama from https://ollama.ai, then run `ollama pull llama3.2`

### OpenAI (Optional -- Cloud)

Uses GPT-4 from OpenAI. Faster and more capable, but requires internet and an API key.

- **Cost**: Pay per use (a few cents per conversation)
- **Setup**: Get an API key from https://platform.openai.com and enter it in Settings -> AI

### Claude (Optional -- Cloud)

Uses Claude from Anthropic. Known for careful and thoughtful responses.

- **Cost**: Pay per use
- **Setup**: Get an API key from https://console.anthropic.com and enter it in Settings -> AI

### Gemini (Optional -- Cloud)

Uses Gemini from Google.

- **Cost**: Free tier available
- **Setup**: Get an API key from Google AI Studio and enter it in Settings -> AI

### How the Fallback Works

The AI tries providers in order:
1. First, it tries your preferred provider (usually Ollama)
2. If that fails, it tries the next available provider
3. If all providers are unavailable, you see "AI assistant offline"

The rest of the app works normally even when AI is offline.

---

## Changing Your AI Provider

1. Go to **Settings** then **AI Assistant**
2. Under **Active Provider**, select your preferred provider from the dropdown
3. If using a cloud provider, enter the API key
4. Click **Test Connection** to verify it works
5. Click **Save**

---

## Starting a New Chat

Each conversation is saved as a "session." To start fresh:
- Click the **New Chat** button at the top of the chat panel
- Your previous conversations are saved and can be accessed from the chat history

---

## What the AI Cannot Do

- It cannot place trades or buy/sell stocks for you -- it can only *propose* recording a transaction, holding, or alert in your own records, which you then confirm
- It cannot predict future prices
- It does not provide financial advice (it provides information and analysis)
- It may sometimes give incorrect information -- always verify important decisions
- It cannot access data outside of your FinanceTracker portfolio
- It cannot access the internet (it only uses data stored in your app)

---

## Common Questions

**Q: Is my data sent to the cloud when I use Ollama?**
A: No. With Ollama, everything runs locally on your computer. Your portfolio data never leaves your machine.

**Q: Is my data sent to the cloud when I use OpenAI/Claude/Gemini?**
A: Yes, the conversation (including relevant portfolio data) is sent to the provider's servers to generate a response. If privacy is a priority, stick with Ollama.

**Q: The AI says "I don't have access to that information." What do I do?**
A: Try rephrasing your question. If you are asking about a specific stock, use the full symbol (e.g., RELIANCE.NS instead of just Reliance).

**Q: Can I use the AI without any API key?**
A: Yes, if you install Ollama (free). Without Ollama or any API key, the AI feature is simply disabled.

---

Want to learn about other features? Check out [Understanding Alerts](understanding-alerts.md) or the [Glossary](glossary.md).
