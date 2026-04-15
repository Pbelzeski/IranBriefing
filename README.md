# Iran Peace Talks — Automated Market Briefing System

Generates twice-daily geopolitical and market analysis briefings on the 2026 Iran War peace talks and their NYSE sector implications.

The system shells out to the [Claude Code](https://docs.claude.com/claude-code) CLI in headless mode (running Opus at max effort with web search), applies a structured analytical framework, and produces timestamped HTML briefings. A persistent state file carries hypotheses forward across runs so probabilities drift continuously instead of resetting each briefing. Runs are billed against your Claude subscription, not the Anthropic API.

## What You Get

Each briefing includes:
- **Situation Update** — what happened since the last briefing, and whether the previous "Key Watch" item resolved
- **Hypothesis Probabilities** — updated weightings for the active peace-talk outcome scenarios (hypotheses can be retired, merged, or newly introduced as the situation evolves)
- **NYSE Sector Calls** — directional predictions for Energy (XLE), Defense (ITA), Airlines (JETS), Tech (QQQ), Consumer Discretionary (XLY), Financials (XLF), Gold (GLD/GDX), Industrials (XLI), Utilities (XLU), Real Estate (XLRE)
- **Key Watch** — the single most important thing to monitor before the next briefing
- **Risk Alert** — tail risks that could invalidate the current framework

Briefings auto-stop 7 days after a peace agreement is recorded.

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

This generates a single pre-market briefing and saves it to `./briefings/` as both an HTML file (for reading) and a `.txt` file (full raw output including the `<state_update>` JSON block, for audit). Open the HTML file in your browser to review.

At max effort with web search, a single briefing can take several minutes.

### 4. Start the Automated Scheduler

```bash
python iran_briefing.py --schedule
```

This runs continuously, generating one briefing per trading day:
- **12:30 PM ET** — Midday briefing (halfway through trading)

Weekends are skipped automatically. Press `Ctrl+C` to stop. To run an ad-hoc pre-market briefing on top of the scheduled midday one, invoke `python iran_briefing.py` manually without `--schedule`.

---

## How Persistent State Works

After each briefing, the script parses a `<state_update>` JSON block out of Claude's output and writes it to [state.json](state.json) in the project root. The next run injects that state into the prompt so Claude sees:

- The previous situation snapshot
- All currently active hypotheses with their last probabilities and rationales
- Retired hypotheses (so they aren't accidentally re-introduced)
- The previous "Key Watch" and "Risk Alert" items

This means hypotheses drift over time rather than resetting to baseline each run. To start fresh from the baseline hypotheses, delete the state file:

```bash
python iran_briefing.py --reset-state
```

---

## Email Delivery (Optional)

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

```bash
nohup python iran_briefing.py --schedule > briefing_log.txt 2>&1 &
echo $! > briefing_pid.txt
```

To stop later:
```bash
kill $(cat briefing_pid.txt)
```

### macOS — Launch Agent (starts on boot)

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

```bash
crontab -e
```

Add:
```
30 12 * * 1-5 cd /path/to/iran_briefing && python3 iran_briefing.py --midday >> cron_log.txt 2>&1
```

### Windows — Task Scheduler

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
| `python iran_briefing.py` | Run one pre-market briefing now |
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
