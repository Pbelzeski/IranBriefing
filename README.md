# Iran Peace Talks — Automated Market Briefing System

Generates a daily geopolitical and market analysis briefing on the 2026 Iran War peace talks and their NYSE sector implications, with additional ad-hoc briefings on demand.

The system shells out to the [Claude Code](https://docs.claude.com/claude-code) CLI in headless mode (running Opus at max effort with web search), applies a structured analytical framework, and produces a timestamped tabbed HTML page per run. A persistent state file carries hypotheses, motives, and ceasefire status forward across runs so the analysis drifts continuously instead of resetting each briefing. Runs are billed against your Claude subscription, not the Anthropic API.

## What You Get

Each briefing is rendered as a tabbed HTML page with the following sections:

- **Situation Update** — what happened since the last briefing, and whether the previous "Key Watch" item resolved
- **Recent Headlines** — 5-10 of the most significant news items since the last run, with source and URL
- **Probable Motives (US)** — ranked top 5 drivers behind current US / Trump-administration policy, with a trend arrow showing whether each motive gained or lost weight since the last briefing
- **Probable Motives (Iran)** — same ranking for Iran's side
- **Probable Outcomes** — each active hypothesis is a collapsible card showing its current probability, trend, rationale, and a nested per-sector market-effects table conditional on that scenario playing out. Hypotheses can be retired, merged, or newly introduced as the situation evolves.
- **Key Watch** — the single most important thing to monitor before the next briefing
- **Risk Alert** — tail risks that could invalidate the current framework

The per-hypothesis market-effects tables cover Energy (XLE), Defense (ITA), Airlines (JETS), Tech (QQQ), Consumer Discretionary (XLY), Financials (XLF), Gold (GLD/GDX), Industrials (XLI), Utilities (XLU), Real Estate (XLRE), and Volatility (VIX / VXX / UVXY), each with a direction (bullish / bearish / neutral), a conviction level, tickers, and a one-line rationale.

Briefings auto-stop 7 days after a peace agreement is recorded.

---

## Tested vs. Untested Functionality

This project was built and tested on **Windows 11** using the **Claude Code CLI** against a **Claude Max subscription**. Anything outside that configuration is provided as a best-effort convenience but has not been exercised end-to-end. Treat the untested items as starting points rather than known-good recipes.

| Feature | Status |
|---|---|
| One-shot briefing generation (`python iran_briefing.py`) | ✅ Tested on Windows |
| On-demand, pre-market, and midday session labels | ✅ Tested on Windows |
| Tabbed HTML output with collapsible hypothesis cards | ✅ Tested on Windows |
| Persistent state (hypotheses, motives, ceasefire, headlines carry-forward) | ✅ Tested on Windows |
| `--reset-state` | ✅ Tested on Windows |
| `--set-agreement` and 7-day auto-stop logic | ✅ Tested on Windows (auto-stop not yet observed in the wild) |
| Built-in scheduler (`--schedule`) | ✅ Tested on Windows |
| Windows Task Scheduler (recommended production path) | ✅ Tested |
| Email delivery (`email_enabled`, SMTP, `--test-email`) | ⚠️ **Untested.** SMTP code path has never been exercised. Gmail app password setup and the provider table are best-effort guidance — expect to debug. |
| macOS `nohup` background run | ⚠️ **Untested.** Shell syntax should be correct but has not been run on a Mac. |
| macOS Launch Agent (`launchd` plist) | ⚠️ **Untested.** The plist has not been loaded on a real machine. Verify paths and the `launchctl load` flow yourself before relying on it. |
| Linux cron entry | ⚠️ **Untested.** Cron line is syntactically correct but has not been installed on a Linux host. |
| Running against the Anthropic API instead of the Claude Code CLI | ❌ **Not supported.** The script shells out to the `claude` CLI only. There is no API-based code path. |

### Cost note for always-on hosting

If you want to run this on a small always-on machine so your laptop isn't the point of failure, a $5/month Linux VPS (DigitalOcean, Hetzner, Linode, etc.) is enough to host the `claude` CLI and cron. **However**, the `claude` CLI still requires an interactive browser-based login (`claude auth`) that is tied to a Pro or Max subscription — the same subscription that covers your local usage, not a per-API-call bill. If you can't get the subscription session to persist on the remote host and fall back to the Anthropic API, every briefing becomes a metered API call with real per-token costs on top of the server rent. Budget accordingly before committing to a remote host.

---

## Quick Start

### 1. Prerequisites

- **Python 3.11+** (required for `zoneinfo`) — check with `python3 --version`
- **Claude Code CLI**, installed and authenticated with an active Claude Pro or Max subscription:
  1. Install: https://docs.claude.com/claude-code
  2. Run `claude auth` to log in
  3. Verify with `claude --version`

No third-party Python packages are needed — the script uses only the standard library. `requirements.txt` is included but empty.

### 2. Configure

Edit [config.json](config.json) if you want to override defaults:

```json
{
  "model": "opus",
  "effort": "max",
  "output_dir": "./briefings",
  "premarket_hour": 9,
  "premarket_minute": 0,
  "midday_hour": 12,
  "midday_minute": 30,
  "agreement_date": ""
}
```

All fields can also be overridden via environment variables (see [Configuration Reference](#configuration-reference)).

### 3. Run a Test Briefing

```bash
python iran_briefing.py
```

This generates a single on-demand briefing and saves it to `./briefings/` as both an HTML file (for reading) and a `.txt` file (full raw output including the `<state_update>` JSON block, for audit). Open the HTML file in your browser to review.

At max effort with web search, a single briefing can take several minutes.

### 4. Start the Automated Scheduler

```bash
python iran_briefing.py --schedule
```

This runs continuously, generating one briefing per trading day:
- **12:30 PM ET** — Midday briefing (halfway through trading)

Weekends are skipped automatically. Press `Ctrl+C` to stop. To run an extra ad-hoc briefing between scheduled runs (for example after breaking news), invoke `python iran_briefing.py` manually in another terminal — it shares the same persistent state and will be labeled "on-demand" in the header and filename.

---

## How Persistent State Works

After each briefing, the script parses a `<state_update>` JSON block out of Claude's output and writes it to [state.json](state.json) in the project root. The next run injects that state into the prompt so the analyst sees:

- The previous situation snapshot
- All currently active hypotheses with their last probabilities, rationales, and per-sector market effects
- Retired hypotheses (so they aren't accidentally re-introduced)
- The top 5 ranked motives for each side, with trend arrows
- The currently tracked ceasefire expiry date
- The previous "Key Watch" and "Risk Alert" items

This means hypotheses, motives, and the ceasefire timeline drift over time rather than resetting to baseline each run. To start fresh from the baseline framework, reset the state file:

```bash
python iran_briefing.py --reset-state
```

---

## Email Delivery (Optional)

> ⚠️ **Untested.** The email code path has not been exercised end-to-end. Treat this section as a starting point and expect to debug before relying on it.

To receive briefings in your inbox, update [config.json](config.json):

```json
{
  "email_enabled": true,
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "your.email@gmail.com",
  "smtp_password": "your_app_password",
  "email_to": "your.email@gmail.com"
}
```

### Gmail Setup

Gmail requires an **App Password** (not your regular password):

1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and your device
3. Copy the 16-character password
4. Paste it as `smtp_password` in config.json

### Test Email

```bash
python iran_briefing.py --test-email
```

### Other Email Providers

| Provider    | SMTP Server             | Port |
|-------------|-------------------------|------|
| Gmail       | smtp.gmail.com          | 587  |
| Outlook     | smtp.office365.com      | 587  |
| Yahoo       | smtp.mail.yahoo.com     | 587  |
| iCloud      | smtp.mail.me.com        | 587  |

---

## Running in the Background

### macOS / Linux — Keep Running After Closing Terminal

> ⚠️ **Untested.** This shell pattern has not been run on a Mac or Linux host as part of this project. The syntax is standard but verify on your side.

```bash
nohup python iran_briefing.py --schedule > briefing_log.txt 2>&1 &
echo $! > briefing_pid.txt
```

To stop later:
```bash
kill $(cat briefing_pid.txt)
```

### macOS — Launch Agent (starts on boot)

> ⚠️ **Untested.** The plist below has not been loaded on a real machine. Verify paths and the `launchctl load` flow before trusting it in production.

Create `~/Library/LaunchAgents/com.iran.briefing.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.iran.briefing</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/iran_briefing/iran_briefing.py</string>
        <string>--schedule</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/iran_briefing/briefing_log.txt</string>
    <key>StandardErrorPath</key>
    <string>/path/to/iran_briefing/briefing_error.txt</string>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.iran.briefing.plist
```

The Launch Agent inherits your authenticated `claude` CLI credentials, so no API key environment variable is needed.

### Linux — Cron (Alternative to Built-in Scheduler)

> ⚠️ **Untested.** Cron line is syntactically correct but has not been installed on a Linux host.

```bash
crontab -e
```

Add:
```
30 12 * * 1-5 cd /path/to/iran_briefing && python3 iran_briefing.py --midday >> cron_log.txt 2>&1
```

### Windows — Task Scheduler

> ✅ **Tested.** This is the production path used by the author. Windows Task Scheduler handles timing, weekends, and reboots, and the script's internal auto-stop handles the 7-day post-agreement cutoff.

1. Open Task Scheduler
2. Create Basic Task → name it "Iran Briefing Midday"
3. Trigger: Daily at 12:30 PM
4. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\iran_briefing.py --midday`
   - Start in: `C:\path\to\iran_briefing\`

Make sure the task runs under a user account that has already run `claude auth`.

---

## When a Peace Agreement Is Reached

Record the date:

```bash
python iran_briefing.py --set-agreement 2026-04-18
```

The system continues generating briefings for 7 more days (tracking implementation, market positioning, sector rotation) and then auto-stops.

To restart after it stops, clear the agreement date by editing `agreement_date` back to `""` in [config.json](config.json).

---

## CLI Reference

| Command | What it does |
|---------|-------------|
| `python iran_briefing.py` | Run one on-demand briefing now (labeled On-Demand) |
| `python iran_briefing.py --premarket` | Run one pre-market briefing now |
| `python iran_briefing.py --midday` | Run one midday briefing now |
| `python iran_briefing.py --schedule` | Start the automated scheduler |
| `python iran_briefing.py --test-email` | Verify email configuration |
| `python iran_briefing.py --set-agreement 2026-04-18` | Set agreement date for auto-stop |
| `python iran_briefing.py --reset-state` | Delete `state.json` and restart from baseline hypotheses |

---

## Configuration Reference

All settings can be set in [config.json](config.json) or via environment variables:

| Config Key | Env Variable | Default | Description |
|-----------|-------------|---------|-------------|
| `model` | `BRIEFING_MODEL` | `opus` | Model passed to `claude --model` |
| `effort` | `BRIEFING_EFFORT` | `max` | Effort level passed to `claude --effort` |
| `output_dir` | `BRIEFING_OUTPUT_DIR` | `./briefings` | Where to save HTML + raw text files |
| `email_enabled` | `EMAIL_ENABLED` | `false` | Send briefings via email |
| `smtp_server` | `SMTP_SERVER` | `smtp.gmail.com` | SMTP server |
| `smtp_port` | `SMTP_PORT` | `587` | SMTP port |
| `smtp_user` | `SMTP_USER` | | Email login |
| `smtp_password` | `SMTP_PASSWORD` | | Email password / app password |
| `email_to` | `EMAIL_TO` | | Recipient email |
| `premarket_hour` | `PREMARKET_HOUR` | `9` | Pre-market briefing hour (ET) |
| `premarket_minute` | `PREMARKET_MINUTE` | `0` | Pre-market briefing minute |
| `midday_hour` | `MIDDAY_HOUR` | `12` | Midday briefing hour (ET) |
| `midday_minute` | `MIDDAY_MINUTE` | `30` | Midday briefing minute |
| `agreement_date` | `AGREEMENT_DATE` | | YYYY-MM-DD, triggers auto-stop 7 days later |

---

## Files Produced

- `briefings/briefing_YYYYMMDD_HHMM_<session>.html` — styled HTML briefing for reading
- `briefings/briefing_YYYYMMDD_HHMM_<session>.txt` — full raw output including the `<state_update>` JSON block
- `state.json` — persistent hypothesis state carried between runs (safe to delete via `--reset-state`)

---

## Cost

Because the script invokes the Claude Code CLI, briefings run against your Claude Pro or Max subscription rather than per-token API billing. There is no marginal cost per briefing beyond your existing subscription, subject to whatever usage limits apply to your plan. Each briefing can consume significant tool-use time at max effort with web search.

---

## Disclaimer

This system generates analytical commentary based on publicly available information and historical market patterns. It is not investment advice. All sector predictions are directional estimates for discussion purposes. Actual market movements depend on countless variables beyond any model's ability to predict. Always consult a licensed financial advisor before making investment decisions.
