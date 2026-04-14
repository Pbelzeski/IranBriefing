# Iran Peace Talks — Automated Market Briefing System

Generates twice-daily geopolitical and market analysis briefings on the 2026 Iran War peace talks and their NYSE sector implications.

The system calls the Anthropic API with web search enabled, applies a structured analytical framework (5 hypotheses, motive analysis for both sides, 10 NYSE sectors), and produces timestamped HTML briefings. Optionally emails them to you.

## What You Get

Each briefing includes:
- **Situation Update** — what happened since the last briefing
- **Hypothesis Probabilities** — updated weightings for 5 peace-talk outcome scenarios
- **NYSE Sector Calls** — directional predictions for Energy, Defense, Airlines, Tech, Consumer Discretionary, Financials, Gold, Industrials, Utilities, Real Estate
- **Key Watch** — the single most important thing to monitor before the next briefing
- **Risk Alert** — tail risks that could invalidate the current framework

Briefings auto-stop 7 days after a peace agreement is reached.

---

## Quick Start (5 minutes)

### 1. Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **An Anthropic API key** — get one at https://console.anthropic.com

### 2. Install

```bash
# Clone or download the files to a folder
cd iran_briefing

# Install the dependency
pip install -r requirements.txt
```

### 3. Configure

Edit `config.json` and replace `YOUR_API_KEY_HERE` with your Anthropic API key:

```json
{
  "anthropic_api_key": "sk-ant-your-key-here",
  "model": "claude-sonnet-4-20250514",
  "output_dir": "./briefings"
}
```

Alternatively, set an environment variable:
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

### 4. Run a Test Briefing

```bash
python iran_briefing.py
```

This generates a single pre-market briefing and saves it to `./briefings/`. Open the HTML file in your browser to review.

### 5. Start the Automated Scheduler

```bash
python iran_briefing.py --schedule
```

This runs continuously, generating briefings at:
- **9:00 AM ET** — Pre-market briefing (30 min before NYSE open)
- **12:30 PM ET** — Midday briefing (halfway through trading)

It skips weekends automatically. Press `Ctrl+C` to stop.

---

## Email Delivery (Optional)

To receive briefings in your inbox, update `config.json`:

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
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-your-key-here</string>
    </dict>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.iran.briefing.plist
```

### Linux — Cron (Alternative to Built-in Scheduler)

If you prefer cron over the built-in scheduler:

```bash
crontab -e
```

Add these lines:
```
0 9 * * 1-5 cd /path/to/iran_briefing && python3 iran_briefing.py >> cron_log.txt 2>&1
30 12 * * 1-5 cd /path/to/iran_briefing && python3 iran_briefing.py --midday >> cron_log.txt 2>&1
```

### Windows — Task Scheduler

1. Open Task Scheduler
2. Create Basic Task → name it "Iran Briefing Pre-Market"
3. Trigger: Daily at 9:00 AM
4. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\iran_briefing.py`
   - Start in: `C:\path\to\iran_briefing\`
5. Repeat for 12:30 PM with `--midday` flag

### Cloud Server (Cheapest Hands-Free Option)

A $5/month VPS (DigitalOcean, Linode, Vultr) can run this 24/7:

```bash
# SSH into your server
ssh user@your-server

# Install Python and clone your files
sudo apt update && sudo apt install python3 python3-pip -y
pip3 install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY="sk-ant-your-key"

# Run with nohup
nohup python3 iran_briefing.py --schedule > log.txt 2>&1 &
```

---

## When a Peace Agreement Is Reached

When a deal is reached, record the date:

```bash
python iran_briefing.py --set-agreement 2026-04-18
```

The system will continue generating briefings for 7 more days (tracking implementation, market positioning, sector rotation) and then auto-stop.

To restart after it stops, clear the agreement date:
```bash
python iran_briefing.py --set-agreement ""
```

---

## CLI Reference

| Command | What it does |
|---------|-------------|
| `python iran_briefing.py` | Run one pre-market briefing now |
| `python iran_briefing.py --midday` | Run one midday briefing now |
| `python iran_briefing.py --schedule` | Start automated scheduler |
| `python iran_briefing.py --test-email` | Verify email configuration |
| `python iran_briefing.py --set-agreement 2026-04-18` | Set agreement date for auto-stop |

---

## Configuration Reference

All settings can be set in `config.json` or via environment variables:

| Config Key | Env Variable | Default | Description |
|-----------|-------------|---------|-------------|
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | (required) | Your API key |
| `model` | `BRIEFING_MODEL` | `claude-sonnet-4-20250514` | Model to use |
| `output_dir` | `BRIEFING_OUTPUT_DIR` | `./briefings` | Where to save HTML files |
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
| `agreement_date` | `AGREEMENT_DATE` | | YYYY-MM-DD, triggers auto-stop after 7 days |

---

## Cost Estimate

Each briefing uses approximately 10,000-20,000 tokens (input + output), plus web search calls. At current Sonnet pricing, expect roughly $0.10-0.30 per briefing, or about $0.40-1.00 per trading day. Monthly cost for a full month of trading days: approximately $8-20.

---

## Disclaimer

This system generates analytical commentary based on publicly available information and historical market patterns. It is not investment advice. All sector predictions are directional estimates for discussion purposes. Actual market movements depend on countless variables beyond any model's ability to predict. Always consult a licensed financial advisor before making investment decisions.
