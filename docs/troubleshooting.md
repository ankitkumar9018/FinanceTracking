# Troubleshooting Guide

> FinanceTracker -- Common Issues and Solutions

---

## Backend Issues

### Backend fails to start: "ModuleNotFoundError"

**Cause**: Python dependencies are not installed.

**Solution**:
```bash
cd backend
uv sync
```

If `uv` is not installed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

### "Database is locked" error (SQLite)

**Cause**: Multiple processes are trying to write to SQLite simultaneously. This typically happens when both the API server and a Celery worker access the same SQLite file.

**Solution**:
1. For development, stop the Celery worker and rely on the APScheduler fallback
2. For production, switch to PostgreSQL:
   ```
   DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/financetracker
   ```
3. If you must use SQLite with Celery, enable WAL journal mode on the database:
   ```sql
   PRAGMA journal_mode=WAL;
   ```
   Note: the app's `backend/app/database.py` passes `check_same_thread=False` and sets `PRAGMA foreign_keys=ON` per connection — neither enables WAL; you would need to add a `PRAGMA journal_mode=WAL` to the same connect hook (or run it once against the file, since WAL is persistent).

---

### "Address already in use" / port 8420 is busy

**Note**: This is rarely a problem anymore. `python -m app` and the launch
scripts (`run.sh`, `scripts/start.sh`) auto-advance to a free port
automatically when `8420` is taken (and print which port they chose), so
startup does not fail on a busy port.

The only case that still fails is a **bare** `uvicorn ... --port 8420` (or any
invocation passing `--strict-port`), which requires the exact port.

**Solution**:
```bash
# Recommended: run via the module entry point, which auto-picks a free port
cd backend && uv run python -m app --port 8420

# ...or pick a different explicit port
cd backend && uv run uvicorn app.main:app --reload --port 8421

# To see what is holding 8420 (only needed if you insist on that exact port)
lsof -i :8420
kill -9 <PID>
```

---

### Alembic migration fails: "Target database is not up to date"

**Cause**: There are unapplied migrations, or the database is ahead of the migration scripts.

**Solution**:
```bash
cd backend

# Check current revision
uv run alembic current

# Check available revisions
uv run alembic history

# Apply all pending migrations
uv run alembic upgrade head

# If that fails, reset and start fresh (DEVELOPMENT ONLY - destroys data)
rm finance.db
uv run alembic upgrade head
```

---

### "SECRET_KEY not set" warning

**Cause**: The `.env` file is missing or does not contain a SECRET_KEY.

**Solution**:
```bash
cd backend
cp .env.example .env

# Generate a random secret key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Copy the output into your .env file as SECRET_KEY=<value>
```

---

## Frontend Issues

### "pnpm install" fails with dependency conflicts

**Cause**: Node.js version mismatch or corrupted cache.

**Solution**:
```bash
# Verify Node.js version (needs 20+)
node --version

# Clear pnpm cache and reinstall
pnpm store prune
rm -rf node_modules apps/web/node_modules packages/ui/node_modules
pnpm install
```

---

### Next.js dev server shows blank page

**Cause**: Usually a build error in a component or missing environment variable.

**Solution**:
1. Check the terminal for error messages
2. Make sure the API URL is set:
   ```bash
   # In apps/web/.env.local
   NEXT_PUBLIC_API_URL=http://localhost:8420
   ```
3. Clear Next.js cache:
   ```bash
   rm -rf apps/web/.next
   pnpm --filter web dev
   ```

---

### "WebSocket connection failed"

**Cause**: The backend is not running or the WebSocket URL is wrong.

**Solution**:
1. Verify the backend is running: `curl http://localhost:8420/health`
2. Check browser console for the exact error message
3. If using HTTPS in production, make sure WebSocket uses `wss://` not `ws://`

---

## Broker Connection Issues

### Zerodha: "TokenException: Token is invalid or has expired"

**Cause**: Zerodha access tokens expire daily at 6 AM IST.

**Solution**:
1. Go to Settings -> Brokers -> Zerodha
2. Click **Reconnect**
3. Log in again on the Zerodha page
4. The app will get a fresh access token

This is a Zerodha limitation -- tokens cannot be refreshed automatically.

---

### Broker sync shows 0 holdings even though I have stocks

**Cause**: The broker account might have a different segment (equity vs commodity vs futures).

**Solution**:
1. Verify you are checking the equity/delivery segment in your broker app
2. Try fetching positions in addition to holdings:
   - Holdings = long-term delivery stocks
   - Positions = intraday or recent delivery trades
3. Some brokers separate demat holdings from trading positions

---

### OAuth broker (Zerodha) connection does not complete

**Cause**: OAuth brokers require a browser login step. The app has no OAuth callback route — `POST /api/v1/broker/connect` returns a `login_url` that you must open and authorize, then the flow is completed by re-submitting the connect request with the `request_token` from the redirect.

**Solution**:
1. Connect the broker from the Brokers page (or `POST /api/v1/broker/connect` with your API key/secret)
2. Open the returned `login_url` in a browser and log in to the broker
3. Copy the `request_token` from the redirect URL you land on
4. Re-submit the connection with `additional_params: {"request_token": "..."}` (the Brokers page prompts for this automatically)
5. The redirect URL registered in your broker's developer portal can be any page you can read the `request_token` from — it does not point at the FinanceTracker API

---

## Price Data Issues

### Stock prices show "stale" indicator

**Cause**: yfinance is unable to fetch current prices (rate limited, network issue, or market closed).

**Solution**:
1. Check if the market is open (NSE: 9:15-15:30 IST, XETRA: 9:00-17:30 CET)
2. If the market is open, the app will retry automatically every 5 minutes
3. Check your internet connection

---

### Wrong stock symbol or "Symbol not found"

**Cause**: yfinance uses specific symbol suffixes for different exchanges.

**Solution**:

| Exchange | Suffix | Example |
|---|---|---|
| NSE (India) | `.NS` | `RELIANCE.NS` |
| BSE (India) | `.BO` | `RELIANCE.BO` |
| XETRA (Germany) | `.DE` | `SAP.DE` |
| Frankfurt | `.F` | `SAP.F` |

The app should handle this automatically, but if you entered a stock manually, make sure the symbol includes the correct suffix.

---

### RSI value seems wrong

**Cause**: RSI is calculated from the last 14+ days of closing prices. If the stock is recently added, there may not be enough historical data.

**Solution**:
1. Wait for at least 14 trading days of data to accumulate
2. Or force a historical data fetch: the app fetches 30+ days of history for accurate RSI
3. RSI is recalculated on every price update -- verify the value matches other sources (e.g., TradingView, MoneyControl)

---

## AI Assistant Issues

### "AI assistant offline" message

**Cause**: No LLM provider is available.

**Solution**:
1. **Ollama (recommended)**: Install Ollama and pull the model:
   ```bash
   # Install Ollama from https://ollama.ai
   ollama serve   # Start the server
   ollama pull llama3.2   # Download the model (~4GB)
   ```
2. Verify Ollama is running: `curl http://localhost:11434`
3. Or configure an API key for OpenAI/Claude/Gemini in Settings -> AI Assistant

---

### AI responses are very slow

**Cause**: The LLM model is running on CPU without enough RAM.

**Solution**:
1. Llama 3.2 needs about 4-8GB of RAM. Close other memory-intensive applications.
2. Use a smaller model: `ollama pull llama3.2:1b` (1B parameter version, faster but less capable)
3. Use a cloud API (OpenAI/Claude/Gemini) instead of local Ollama for faster responses
4. Check Settings -> AI to see which provider is active

---

### AI gives inaccurate information about my portfolio

**Cause**: The LLM might hallucinate or have stale context.

**Solution**:
1. Start a new chat session (click "New Chat")
2. Be specific in your questions: "What is the RSI of RELIANCE.NS?" instead of "How is Reliance doing?"
3. The AI uses tools to fetch real data, but verify critical decisions independently
4. AI responses include a disclaimer -- they are not financial advice

---

## Notification Issues

### Email notifications not being sent

**Cause**: SendGrid API key is missing or invalid.

**Solution**:
1. Go to Settings -> Notifications -> Email
2. Enter a valid SendGrid API key
3. Set the "From" email address (must be verified in SendGrid)
4. Click **Test** to send a test email
5. Check your spam folder

---

### Telegram bot not responding

**Cause**: The bot token is wrong or you have not messaged the bot yet.

**Solution**:
1. Create a bot via @BotFather on Telegram and copy the token
2. Message your bot (send `/start`) -- this is required for the app to detect your Chat ID
3. Enter the bot token in Settings -> Notifications -> Telegram
4. Click **Test**

---

## Authentication Issues

### Password reset email never arrives

**Cause**: `POST /auth/forgot-password` emails the reset link/token via SendGrid. If SendGrid is not configured (`SENDGRID_API_KEY` + `EMAIL_FROM` unset) or the `sendgrid` package isn't installed, the email is silently skipped. The endpoint always returns the same generic success message, so it never reveals whether an account exists — meaning a missing email looks identical to a delivered one.

**Solution**:
1. Configure SendGrid in `backend/.env` (`SENDGRID_API_KEY` and a verified `EMAIL_FROM`), then request the reset again.
2. If you can't use SendGrid, recover the token manually — it is still generated and stored. The backend logs a warning (`SendGrid not configured — skipping email`), and the full reset email (including the raw token and the `/reset-password?token=...` link) is written to the `notification_logs` table with status `FAILED`:
   ```sql
   SELECT subject, body, created_at FROM notification_logs
   WHERE channel = 'email' AND status = 'FAILED'
   ORDER BY id DESC LIMIT 1;
   ```
   Copy the token out of `body` and paste it into the reset-password form (the token is valid for 1 hour).

---

## Database Issues

### Want to start fresh with a clean database

**WARNING**: This deletes all your data.

```bash
cd backend
rm finance.db   # Delete SQLite database
uv run alembic upgrade head   # Create fresh tables
```

For PostgreSQL:
```bash
cd backend
uv run alembic downgrade base   # Drop all tables
uv run alembic upgrade head     # Recreate tables
```

---

### How to backup my database

**SQLite**:
```bash
cp backend/finance.db backend/finance_backup_$(date +%Y%m%d).db
```

**PostgreSQL**:
```bash
pg_dump -Fc financetracker > backup_$(date +%Y%m%d).dump
```

**In-app**: Reports page -> export cards (holdings/transactions CSV, JSON portfolio backup, HTML report; the SQLite database download is available to the instance owner).

---

## Desktop App Issues

### Desktop app shows a loading spinner for a minute on first launch

**Cause**: This is normal, not a hang. The bundled backend is a onefile PyInstaller binary that re-extracts itself on every launch, and on first run macOS Gatekeeper / Windows antivirus also scans it. A cold start can take **40–120 seconds**.

**Solution**:
1. Leave the window open — it shows a "Starting local server… First launch can take a minute or two" spinner and switches to the app automatically once the backend is healthy.
2. If it runs past 120 seconds, a self-healing recovery page appears that keeps polling the backend and has a "Retry now" button. It navigates on its own as soon as the backend responds — no need to restart.
3. Subsequent launches are faster (no first-run security scan), but the extraction step still adds a few seconds.

---

### Tauri app fails to build: "Rust compilation error"

**Cause**: Rust toolchain is not installed or outdated.

**Solution**:
```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Update Rust
rustup update stable

# Rebuild
cd apps/desktop && pnpm tauri build
```

---

### Desktop app shows "Cannot connect to API"

**Cause**: The backend sidecar failed to start, or the port was already in use.

**Solution**:
1. In dev mode, start the backend manually: `cd backend && uv run python -m app --port 8420`
2. In production (built installer), the sidecar starts automatically — check if the sidecar binary exists:
   ```bash
   ls apps/desktop/src-tauri/binaries/
   # Should contain financetracker-backend-{target_triple}[.exe]
   ```
3. Test the sidecar standalone:
   ```bash
   ./apps/desktop/src-tauri/binaries/financetracker-backend-{TRIPLE} --port 9999 --db-path /tmp/test.db
   ```

---

### Desktop app build fails: "failed to create sidecar command"

**Cause**: The sidecar binary is missing or has the wrong filename.

**Solution**:
Tauri expects the binary named `financetracker-backend-{TARGET_TRIPLE}[.exe]` in `apps/desktop/src-tauri/binaries/`. Check your target triple:
```bash
rustc -vV | grep host
```
Then ensure the binary matches. See [desktop-app.md](desktop-app.md) for the full target triple reference table.

---

### Windows: Console window flashes when desktop app starts

**Cause**: PyInstaller was built with `console=True`.

**Solution**: This was fixed — the spec now sets `console=False` on Windows. Rebuild the sidecar:
```bat
cd backend
uv run pyinstaller financetracker.spec --clean --noconfirm
```

---

### macOS: "FinanceTracker is damaged and can't be opened"

**Cause**: The app is not code-signed. macOS Gatekeeper blocks unsigned apps.

**Solution**:
```bash
xattr -cr /Applications/FinanceTracker.app
```
For distribution, configure code signing in the Tauri config.

---

### Linux: Desktop app fails to build — "libwebkit2gtk not found"

**Cause**: Missing system libraries required by Tauri.

**Solution**:
```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
```

---

## Performance Issues

### Dashboard is slow with many holdings (100+)

**Solution**:
1. Enable virtual scrolling (enabled by default for 50+ rows)
2. Switch to "Compact" table density in Settings -> Display
3. Reduce the number of visible columns
4. Use Chrome or Edge (they have better performance than Firefox for large tables)

---

### Backend API response times are slow

**Solution**:
1. Check if the database has proper indexes (run `uv run alembic upgrade head` to ensure all indexes are created)
2. For PostgreSQL, run `ANALYZE` to update query planner statistics
3. Check if yfinance requests are timing out (visible in backend logs)
4. Consider enabling Redis for background tasks so price fetching does not block API requests

---

## Windows-Specific Issues

### PowerShell scripts fail with "execution policy" error

**Cause**: PowerShell's default execution policy blocks scripts.

**Solution**:
```powershell
# Allow scripts for current user
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### "Get-NetTCPConnection: Access is denied"

**Cause**: Some PowerShell scripts use `Get-NetTCPConnection` which may require elevated permissions.

**Solution**: Run PowerShell as Administrator, or use the `run.ps1` launcher which handles this gracefully.

---

### PyInstaller build fails on Windows: "No module named 'app'"

**Cause**: Running from wrong directory or venv not activated.

**Solution**:
```bat
cd backend
uv run pyinstaller financetracker.spec --clean --noconfirm
```
Always use `uv run` to ensure the correct venv is used.

---

## Still Stuck?

1. Check the backend logs: `tail -f logs/backend.log`
2. Check the browser console for frontend errors (F12 -> Console)
3. Run the health check script: `./scripts/health-check.sh` (or `.\scripts\health-check.ps1` on Windows)
4. Open a GitHub issue with:
   - What you were trying to do
   - The exact error message
   - Your OS and browser version
   - Relevant log output
