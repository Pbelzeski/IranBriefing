#!/usr/bin/env python3
"""
Iran War Peace Talks — Automated Market Briefing System
========================================================
Generates twice-daily briefings analyzing peace talk developments,
hypothesis probability shifts, and NYSE sector predictions.

Shells out to the Claude Code CLI in headless mode (-p) with Opus at max
effort and web search. Runs are billed against your Claude subscription
rather than the Anthropic API. Maintains a condensed state file so
hypotheses drift continuously across briefings instead of resetting to
baseline each run.

Usage:
    python iran_briefing.py                 # Run once now
    python iran_briefing.py --schedule      # Run on schedule (9:00 AM & 12:30 PM ET)
    python iran_briefing.py --test-email    # Send a test email to verify config
    python iran_briefing.py --reset-state   # Delete state.json, restart from baselines
"""

import argparse
import json
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_FILE = Path(__file__).parent / "state.json"
STATE_VERSION = 1


# ─── Configuration ──────────────────────────────────────────────────────────

def load_config():
    """Load config from environment variables, falling back to config.json."""
    config_path = Path(__file__).parent / "config.json"
    file_config = {}
    if config_path.exists():
        with open(config_path) as f:
            file_config = json.load(f)

    return {
        "model": os.getenv("BRIEFING_MODEL", file_config.get("model", "opus")),
        "effort": os.getenv("BRIEFING_EFFORT", file_config.get("effort", "max")),
        "output_dir": os.getenv("BRIEFING_OUTPUT_DIR", file_config.get("output_dir", "./briefings")),
        # Email settings (optional)
        "email_enabled": os.getenv("EMAIL_ENABLED", str(file_config.get("email_enabled", False))).lower() == "true",
        "smtp_server": os.getenv("SMTP_SERVER", file_config.get("smtp_server", "smtp.gmail.com")),
        "smtp_port": int(os.getenv("SMTP_PORT", file_config.get("smtp_port", 587))),
        "smtp_user": os.getenv("SMTP_USER", file_config.get("smtp_user", "")),
        "smtp_password": os.getenv("SMTP_PASSWORD", file_config.get("smtp_password", "")),
        "email_to": os.getenv("EMAIL_TO", file_config.get("email_to", "")),
        # Schedule settings
        "premarket_hour": int(os.getenv("PREMARKET_HOUR", file_config.get("premarket_hour", 9))),
        "premarket_minute": int(os.getenv("PREMARKET_MINUTE", file_config.get("premarket_minute", 0))),
        "midday_hour": int(os.getenv("MIDDAY_HOUR", file_config.get("midday_hour", 12))),
        "midday_minute": int(os.getenv("MIDDAY_MINUTE", file_config.get("midday_minute", 30))),
        # Auto-stop: stop running after agreement + 7 days
        "agreement_date": os.getenv("AGREEMENT_DATE", file_config.get("agreement_date", "")),
    }


# ─── The Analysis Framework (embedded system prompt) ────────────────────────

SYSTEM_PROMPT = """You are a geopolitical and financial analyst producing a twice-daily briefing
on the 2026 Iran War peace talks and their NYSE market implications.

## YOUR ANALYTICAL FRAMEWORK

You maintain and continuously update a set of HYPOTHESES for peace talk outcomes.
Each hypothesis has a probability weighting and NYSE sector implications.

This hypothesis set is DYNAMIC:
- Probabilities shift every briefing as new information arrives.
- Hypotheses can be RETIRED if they go stale (probability stays below ~3% for
  multiple consecutive briefings, OR they are superseded by a new framing that
  better fits reality).
- NEW hypotheses can be INTRODUCED (next available ID, e.g. H6, H7) when the
  existing set no longer captures a scenario that has become plausible.
- Hypotheses can be MERGED if they converge (keep the dominant one, retire the
  other with a note).
- Total probabilities across all active hypotheses should sum to ~100%.

## BASELINE HYPOTHESES (use these for the FIRST briefing only — subsequent briefings inherit live state from the previous run)

### H1: "The Can-Kick" — Ceasefire Extension + Vague Framework (~40% baseline)
Both sides extend ceasefire with a non-binding framework. Strait partially reopens. Core issues deferred.
- Oil: down 8-15%. S&P: up 3-6%.
- Winners: Airlines, Tech, Financials. Losers: Energy, Gold.

### H2: "Back to the Brink" — Talks Collapse, Ceasefire Unravels (~25% baseline)
Talks fail. Israel escalates Lebanon. Ceasefire expires with no renewal. Fighting resumes.
- Oil: up 15-30%. S&P: down 8-15%.
- Winners: Energy, Defense, Gold. Losers: Airlines, Tech, Consumer Discretionary.

### H3: "The Half-Loaf" — Narrow Hormuz-for-Sanctions Deal (~15% baseline)
Transactional deal: Iran reopens Strait for targeted sanctions relief. Nuclear issues deferred.
- Oil: down 20-30%. S&P: up 7-12%.
- Winners: Airlines, Tech, Consumer Discretionary, Industrials. Losers: Energy, Gold, Defense.

### H4: "The Potemkin Deal" — Symbolic Agreement, Contradictory Interpretations (~12% baseline)
Deliberately ambiguous agreement. Both sides claim victory. Markets rally then reverse.
- Oil: down 10-18% then rebounds. S&P: up 4-8% then fades.
- Key feature: extreme volatility, worst scenario for investor confidence.

### H5: "The Grand Bargain" — Comprehensive Peace Deal (~8% baseline)
Historic comprehensive agreement on nuclear, Strait, sanctions, reconstruction.
- Oil: down 30-40%. S&P: up 12-20%.
- Winners: Airlines, Tech, Consumer Disc, EM. Losers: Energy, Defense, Gold.

## MOTIVE FRAMEWORKS

### Trump's Motives (ranked):
1. Strategic opportunism — exploiting Iran's weakness
2. Israeli alignment / Netanyahu partnership
3. Legacy & strongman self-image
4. Nuclear nonproliferation
5. Energy/oil leverage

### Iran's Motives (ranked):
1. Regime survival (existential imperative)
2. Economic leverage via Hormuz closure
3. Deterrence restoration
4. Rally-the-flag nationalism vs. domestic dissent
5. Preserving Axis of Resistance / proxy network

## KEY VARIABLES TO TRACK
- Strait of Hormuz status (shipping traffic, blockade enforcement)
- Israel-Lebanon situation (strikes, Hezbollah activity)
- Oil prices (Brent crude level)
- Peace talk status (scheduled, ongoing, failed, succeeded)
- US domestic politics (gas prices, midterm positioning)
- Iran internal dynamics (protests, regime stability, nuclear activity)
- Ceasefire status (holding, violated, expired)

## YOUR TASK FOR EACH BRIEFING

1. READ the "Previous Briefing State" block in the user prompt (if present).
   It tells you where things stood at the last briefing: the current active
   hypotheses with their probabilities, the retired hypotheses (do NOT
   re-introduce without strong new evidence), and the previous "Key Watch" item.
2. SEARCH for the latest developments on every key variable using web search.
3. ADDRESS whether the previous "Key Watch" item resolved, and how.
4. ASSESS how new information shifts each active hypothesis. Update probabilities
   relative to where they stood last time, not relative to baseline.
5. RETIRE, REPLACE, or INTRODUCE hypotheses as warranted. When retiring, give a
   reason. When introducing a new one, explain why the existing set missed it.
6. PREDICT specific NYSE sector impacts based on current trajectory.
7. IDENTIFY the single most important thing to watch before the next briefing.

## OUTPUT FORMAT

Structure your briefing exactly as follows. The <briefing> block is for human
readers and will be rendered as HTML. The <state_update> block at the END is
for the automation system to parse — it MUST be valid JSON inside the tags.

<briefing>
<header>
Briefing type (Pre-Market or Midday), timestamp, session identifier
</header>

<situation_update>
What happened since the last briefing? Key developments in 2-3 paragraphs.
Explicitly address whether the previous "Key Watch" item resolved.
</situation_update>

<hypothesis_update>
For each ACTIVE hypothesis: ID, title, current probability, direction of change
from the previous briefing (↑↓→), and 1-2 sentence justification.
If you RETIRED or INTRODUCED hypotheses this briefing, call it out clearly
here with the reason.
</hypothesis_update>

<sector_calls>
For each major sector: current call (bullish/bearish/neutral), conviction level,
specific tickers to watch.
Sectors: Energy (XLE), Defense (ITA), Airlines (JETS), Tech (QQQ), Consumer Discretionary (XLY),
Financials (XLF), Gold (GLD/GDX), Industrials (XLI), Utilities (XLU), Real Estate (XLRE)
</sector_calls>

<key_watch>
The single most important thing to watch before the next briefing.
</key_watch>

<risk_alert>
Any tail risks or surprises that could invalidate the current framework.
</risk_alert>
</briefing>

<state_update>
{
  "situation_snapshot": "2-3 sentence neutral summary of where things currently stand. Will be injected into the NEXT briefing's prompt so future-you has context.",
  "hypotheses": [
    {
      "id": "H1",
      "title": "The Can-Kick — Ceasefire Extension + Vague Framework",
      "probability": 38,
      "trend": "down",
      "one_line_rationale": "Short reason for current probability, under 25 words, for future-you to read at next briefing.",
      "sectors_brief": "Bullish tech/airlines, bearish energy"
    }
  ],
  "newly_retired_hypotheses": [
    {
      "id": "H_OLD",
      "title": "...",
      "reason": "Why this was retired in THIS briefing."
    }
  ],
  "newly_introduced_hypotheses": [
    {
      "id": "H6",
      "title": "...",
      "reason": "Why this was introduced in THIS briefing."
    }
  ],
  "previous_key_watch_for_next_run": "Copy the text of your <key_watch> section here verbatim.",
  "previous_risk_alert_for_next_run": "Copy the text of your <risk_alert> section here verbatim.",
  "ceasefire_expiry": "YYYY-MM-DD expiry date of the currently active ceasefire, or empty string if none/unknown. Update this whenever news indicates the ceasefire was extended, renegotiated, replaced, broken, or a new one was announced. If unchanged from the previous run, repeat the same date — do not omit the field."
}
</state_update>

CRITICAL RULES FOR <state_update>:
- It MUST be valid JSON. No trailing commas, no comments, no markdown fences.
- The "hypotheses" array must contain ALL currently ACTIVE hypotheses. Anything
  not in this array is treated as removed.
- "newly_retired_hypotheses" and "newly_introduced_hypotheses" contain only
  changes made in THIS briefing. Leave them as empty arrays [] if nothing changed.
- Probabilities are integers 0-100. Trend is "up", "down", or "flat".
- Keep "one_line_rationale" under 25 words — this is the condensed memory that
  gets carried forward.
- "ceasefire_expiry" must always be present. Repeat the prior date if nothing
  changed, update it if news shows the ceasefire was extended/renegotiated/broken,
  or set it to "" if there is no longer a dated ceasefire in effect.

IMPORTANT: Be specific and actionable. Use concrete numbers, name specific tickers,
give clear directional calls. Hedge where genuinely uncertain, but don't be vague
for the sake of caution. This briefing exists to support decision-making.

IMPORTANT: Respect copyright. Paraphrase all source material. Never quote more
than a few words from any source. Cite sources by name but summarize in your own
words."""


USER_PROMPT_TEMPLATE = """Generate the {session_type} briefing for {date_str}.

Today's date is {date_str}. The current time is {time_str} ET.
The NYSE {market_status}.
{ceasefire_line}

{previous_state_block}

Search for the LATEST information on:
1. Iran-US peace talks status and any new developments today
2. Strait of Hormuz / blockade status
3. Current oil prices (Brent crude)
4. Israel-Lebanon situation
5. Any US stock market pre-market or intraday moves related to Iran
6. Any statements from Trump, Vance, Iranian officials, or mediators

Then produce the full briefing following the framework in your instructions,
including the <state_update> JSON block at the end.

If a peace agreement has been reached, note this clearly and shift analysis to
implementation risks and post-agreement market positioning."""


# ─── Persistent Hypothesis State ────────────────────────────────────────────

def load_state() -> dict:
    """Load the persistent hypothesis state, or return a fresh empty state."""
    if not STATE_FILE.exists():
        return {
            "version": STATE_VERSION,
            "briefings_count": 0,
            "hypotheses": [],
            "retired_hypotheses": [],
            "situation_snapshot": "",
            "previous_key_watch": "",
            "previous_risk_alert": "",
            "ceasefire_expiry": "2026-04-21",
            "last_updated": "",
            "last_briefing_file": "",
        }
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def format_state_for_prompt(state: dict) -> str:
    """Render the persistent state as a text block for injection into the user prompt."""
    if state["briefings_count"] == 0:
        return (
            "## PREVIOUS BRIEFING STATE\n\n"
            "This is the FIRST briefing in this series. There is no prior state. "
            "Use the baseline hypotheses from your instructions as your starting point, "
            "then adjust them based on current news."
        )

    lines = [
        "## PREVIOUS BRIEFING STATE",
        "",
        f"(Briefing #{state['briefings_count']} was at {state.get('last_updated', 'unknown time')}.)",
        "",
        "### Situation snapshot (from last briefing):",
        state.get("situation_snapshot", "(none recorded)"),
        "",
        "### Active hypotheses at end of last briefing:",
    ]
    for h in state.get("hypotheses", []):
        trend_arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(h.get("trend", "flat"), "→")
        lines.append(
            f"- **{h.get('id', '?')}** ({h.get('probability', '?')}%, {trend_arrow}) "
            f"{h.get('title', '')} — {h.get('one_line_rationale', '')}"
        )

    if state.get("retired_hypotheses"):
        lines.append("")
        lines.append("### Retired hypotheses (do NOT re-introduce without strong new evidence):")
        for h in state["retired_hypotheses"]:
            lines.append(f"- **{h.get('id', '?')}** {h.get('title', '')} — retired: {h.get('reason', '')}")

    if state.get("previous_key_watch"):
        lines.append("")
        lines.append("### Previous 'Key Watch' item (address whether this resolved):")
        lines.append(state["previous_key_watch"])

    if state.get("previous_risk_alert"):
        lines.append("")
        lines.append("### Previous 'Risk Alert':")
        lines.append(state["previous_risk_alert"])

    return "\n".join(lines)


def extract_state_update(briefing_text: str):
    """Pull the JSON state_update block out of Claude's output."""
    match = re.search(r"<state_update>(.*?)</state_update>", briefing_text, re.DOTALL)
    if not match:
        return None
    json_text = match.group(1).strip()
    # Tolerate optional markdown fences in case the model adds them
    json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
    json_text = re.sub(r"\s*```$", "", json_text)
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  ⚠ Failed to parse <state_update> JSON: {e}")
        return None


def strip_state_update(briefing_text: str) -> str:
    """Remove the <state_update> block so it isn't rendered in the HTML."""
    return re.sub(r"<state_update>.*?</state_update>", "", briefing_text, flags=re.DOTALL).strip()


def merge_state(old_state: dict, new_update: dict, briefing_file: str) -> dict:
    """Fold a parsed state_update from Claude into the persistent state."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    retired = list(old_state.get("retired_hypotheses", []))
    for r in (new_update.get("newly_retired_hypotheses") or []):
        retired.append({
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "reason": r.get("reason", ""),
            "retired_on_briefing": old_state.get("briefings_count", 0) + 1,
            "retired_on_date": now.strftime("%Y-%m-%d"),
        })

    # Carry ceasefire_expiry forward unless the model explicitly updated it.
    # Presence of the key in new_update (even if "") counts as an explicit update.
    if "ceasefire_expiry" in new_update:
        ceasefire_expiry = new_update["ceasefire_expiry"]
    else:
        ceasefire_expiry = old_state.get("ceasefire_expiry", "")

    return {
        "version": STATE_VERSION,
        "briefings_count": old_state.get("briefings_count", 0) + 1,
        "last_updated": now.strftime("%Y-%m-%d %H:%M %Z"),
        "last_briefing_file": briefing_file,
        "situation_snapshot": new_update.get("situation_snapshot", ""),
        "hypotheses": new_update.get("hypotheses", []),
        "retired_hypotheses": retired,
        "previous_key_watch": new_update.get("previous_key_watch_for_next_run", ""),
        "previous_risk_alert": new_update.get("previous_risk_alert_for_next_run", ""),
        "ceasefire_expiry": ceasefire_expiry,
    }


# ─── Claude Code Invocation ─────────────────────────────────────────────────

def generate_briefing(config: dict, session_type: str, state: dict) -> str:
    """Call the Claude Code CLI in headless mode to generate a briefing."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    expiry_str = (state.get("ceasefire_expiry") or "").strip()
    if expiry_str:
        try:
            ceasefire_expiry = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=et)
            days_until = (ceasefire_expiry - now).days
            if days_until < 0:
                ceasefire_line = (
                    f"As of the last briefing, the ceasefire was set to expire on {expiry_str} "
                    f"— that was {abs(days_until)} days ago. Verify via web search whether it was "
                    f"extended, replaced, or has lapsed, and update ceasefire_expiry accordingly."
                )
            else:
                ceasefire_line = (
                    f"As of the last briefing, the ceasefire is set to expire on {expiry_str} "
                    f"— that's {days_until} days from now. If news indicates this has been "
                    f"extended, renegotiated, or broken, update ceasefire_expiry in <state_update>."
                )
        except ValueError:
            ceasefire_line = (
                f"Current ceasefire expiry field is malformed ({expiry_str!r}). "
                f"Set a valid YYYY-MM-DD value in ceasefire_expiry or empty string if unknown."
            )
    else:
        ceasefire_line = (
            "Ceasefire expiry is currently unknown or no active ceasefire is in effect. "
            "Determine current status via web search and set ceasefire_expiry in <state_update> "
            "if a dated ceasefire exists."
        )

    hour = now.hour
    if session_type == "pre-market":
        market_status = "opens in approximately 30 minutes"
    elif 9 <= hour < 16:
        market_status = "is currently open"
    else:
        market_status = "is currently closed"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        session_type=session_type.replace("-", " ").title(),
        date_str=date_str,
        time_str=time_str,
        market_status=market_status,
        ceasefire_line=ceasefire_line,
        previous_state_block=format_state_for_prompt(state),
    )

    print(f"  Calling Claude Code (model={config['model']}, effort={config['effort']}) with web search...")
    print(f"  This can take several minutes at max effort. Please wait.")

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", user_prompt,
                "--model", config["model"],
                "--effort", config["effort"],
                "--system-prompt", SYSTEM_PROMPT,
                "--tools", "WebSearch,WebFetch",
                "--permission-mode", "bypassPermissions",
                "--output-format", "text",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1800,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "The 'claude' CLI was not found on PATH. Install Claude Code and run "
            "'claude auth' to log in with your Pro subscription. "
            "See https://docs.claude.com/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude Code call timed out after 30 minutes.")

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude Code returned exit code {result.returncode}.\n"
            f"stderr: {result.stderr[:2000]}"
        )

    return result.stdout.strip()


# ─── HTML Formatting ────────────────────────────────────────────────────────

def format_html_briefing(raw_text: str, session_type: str, timestamp: str) -> str:
    """Wrap the raw briefing text in a styled HTML document."""
    content = raw_text

    content = content.replace("&", "&amp;").replace("<briefing>", "").replace("</briefing>", "")

    content = re.sub(r"^### (.+)$", r"<h3>\1</h3>", content, flags=re.MULTILINE)
    content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", content, flags=re.MULTILINE)
    content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content, flags=re.MULTILINE)

    content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)

    section_map = {
        "header": ("📋", "Briefing Header"),
        "situation_update": ("🌍", "Situation Update"),
        "hypothesis_update": ("📊", "Hypothesis Probabilities"),
        "sector_calls": ("📈", "NYSE Sector Calls"),
        "key_watch": ("👁", "Key Watch"),
        "risk_alert": ("⚠️", "Risk Alert"),
    }

    for tag, (emoji, title) in section_map.items():
        open_tag = f"&lt;{tag}&gt;"
        close_tag = f"&lt;/{tag}&gt;"
        content = content.replace(open_tag,
            f'<div class="section"><div class="section-header">{emoji} {title}</div><div class="section-body">')
        content = content.replace(close_tag, "</div></div>")

    paragraphs = content.split("\n\n")
    content = "\n".join(f"<p>{p.strip()}</p>" if not p.strip().startswith("<") else p for p in paragraphs if p.strip())

    session_label = "Pre-Market Briefing" if "pre" in session_type.lower() else "Midday Briefing"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Iran Peace Talks — {session_label} — {timestamp}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: Georgia, 'Times New Roman', serif;
        background: #fafaf8;
        color: #1a1a1a;
        line-height: 1.65;
        max-width: 780px;
        margin: 0 auto;
        padding: 30px 24px;
    }}
    .masthead {{
        border-bottom: 3px double #1a1a1a;
        padding-bottom: 14px;
        margin-bottom: 24px;
    }}
    .masthead h1 {{
        font-size: 22px;
        letter-spacing: -0.02em;
    }}
    .masthead .meta {{
        font-size: 13px;
        color: #666;
        font-style: italic;
        margin-top: 4px;
    }}
    .section {{
        margin: 20px 0;
        border: 1px solid #e0ddd8;
        border-radius: 6px;
        overflow: hidden;
    }}
    .section-header {{
        background: #f0ede8;
        padding: 10px 16px;
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.02em;
        border-bottom: 1px solid #e0ddd8;
    }}
    .section-body {{
        padding: 16px;
        font-size: 14px;
    }}
    .section-body p {{
        margin-bottom: 12px;
    }}
    .section-body p:last-child {{
        margin-bottom: 0;
    }}
    h2 {{
        font-size: 17px;
        margin: 18px 0 8px;
        color: #2c2c2c;
    }}
    h3 {{
        font-size: 15px;
        margin: 14px 0 6px;
        color: #444;
    }}
    strong {{
        font-weight: 700;
    }}
    .footer {{
        margin-top: 30px;
        padding-top: 14px;
        border-top: 1px solid #ddd;
        font-size: 11px;
        color: #999;
        font-style: italic;
    }}
    @media (prefers-color-scheme: dark) {{
        body {{ background: #1a1a1a; color: #e0e0e0; }}
        .masthead {{ border-color: #555; }}
        .section {{ border-color: #333; }}
        .section-header {{ background: #252525; border-color: #333; }}
        h2, h3 {{ color: #ccc; }}
        .masthead .meta {{ color: #888; }}
    }}
</style>
</head>
<body>
<div class="masthead">
    <h1>Iran Peace Talks — {session_label}</h1>
    <div class="meta">{timestamp} ET · Automated Geopolitical & Market Analysis</div>
</div>

{content}

<div class="footer">
    This briefing was generated automatically using Claude Code with web search.
    It is analytical commentary, not investment advice. All sector predictions are directional
    estimates for discussion purposes. Consult a licensed financial advisor before making
    investment decisions. Sources are paraphrased to respect copyright.
</div>
</body>
</html>"""
    return html


# ─── Email Delivery ─────────────────────────────────────────────────────────

def send_email(config: dict, subject: str, html_body: str):
    """Send the briefing via email."""
    if not config["email_enabled"]:
        return

    if not all([config["smtp_user"], config["smtp_password"], config["email_to"]]):
        print("  ⚠ Email enabled but credentials missing. Skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = config["smtp_user"]
    msg["To"] = config["email_to"]
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["smtp_user"], config["smtp_password"])
            server.send_message(msg)
        print(f"  ✓ Email sent to {config['email_to']}")
    except Exception as e:
        print(f"  ✗ Email failed: {e}")


# ─── Main Briefing Runner ──────────────────────────────────────────────────

def run_briefing(config: dict, session_type: str = "pre-market"):
    """Execute a single briefing cycle."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    timestamp = now.strftime("%B %d, %Y %I:%M %p")
    file_timestamp = now.strftime("%Y%m%d_%H%M")

    print(f"\n{'='*60}")
    print(f"  IRAN BRIEFING — {session_type.upper()}")
    print(f"  {timestamp} ET")
    print(f"{'='*60}")

    # Auto-stop after agreement + 7 days
    if config.get("agreement_date"):
        try:
            agreement = datetime.strptime(config["agreement_date"], "%Y-%m-%d").replace(tzinfo=et)
            stop_date = agreement + timedelta(days=7)
            if now > stop_date:
                print(f"\n  ■ Auto-stop: Agreement was reached on {config['agreement_date']}.")
                print(f"    7-day post-agreement monitoring period ended {stop_date.strftime('%B %d')}.")
                print(f"    Briefing system shutting down. Edit agreement_date in config to restart.")
                return False
        except ValueError:
            pass

    # Load persistent state so Claude can build on it
    state = load_state()
    print(f"  Loaded state: about to run briefing #{state['briefings_count'] + 1}, "
          f"{len(state.get('hypotheses', []))} active hypotheses carried forward")

    # Generate briefing
    try:
        raw = generate_briefing(config, session_type, state)
    except RuntimeError as e:
        print(f"  ✗ Error: {e}")
        return True
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}")
        return True

    # Save the pretty HTML (with state_update stripped) and the full raw text
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"briefing_{file_timestamp}_{session_type.replace('-', '_')}.html"
    filepath = output_dir / filename

    display_text = strip_state_update(raw)
    html = format_html_briefing(display_text, session_type, timestamp)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ Saved HTML briefing to {filepath}")

    # Full raw text includes the <state_update> block for your own audit trail
    txt_path = output_dir / filename.replace(".html", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"IRAN BRIEFING — {session_type.upper()} — {timestamp} ET\n")
        f.write("=" * 60 + "\n\n")
        f.write(raw)
    print(f"  ✓ Saved full raw text to {txt_path}")

    # Parse the state update block and advance persistent state
    state_update = extract_state_update(raw)
    if state_update is None:
        print(f"  ⚠ No valid <state_update> block found — persistent state NOT advanced.")
        print(f"    Next briefing will see the same state as this one did.")
    else:
        new_state = merge_state(state, state_update, str(filepath))
        save_state(new_state)
        print(f"  ✓ State updated: {len(new_state['hypotheses'])} active, "
              f"{len(new_state['retired_hypotheses'])} retired total")

    # Email
    subject = f"Iran Briefing: {session_type.replace('-', ' ').title()} — {now.strftime('%b %d')}"
    send_email(config, subject, html)

    print(f"  ✓ Briefing complete.\n")
    return True


# ─── Scheduler ──────────────────────────────────────────────────────────────

def run_scheduler(config: dict):
    """Simple sleep-based scheduler that runs briefings at configured times."""
    et = ZoneInfo("America/New_York")

    print("\n" + "=" * 60)
    print("  IRAN BRIEFING SCHEDULER")
    print("=" * 60)
    print(f"  Pre-market briefing: {config['premarket_hour']:02d}:{config['premarket_minute']:02d} ET")
    print(f"  Midday briefing:     {config['midday_hour']:02d}:{config['midday_minute']:02d} ET")
    print(f"  Model / effort:      {config['model']} / {config['effort']}")
    print(f"  Output directory:    {config['output_dir']}")
    print(f"  State file:          {STATE_FILE}")
    print(f"  Email delivery:      {'enabled' if config['email_enabled'] else 'disabled'}")
    if config.get("agreement_date"):
        print(f"  Auto-stop after:     {config['agreement_date']} + 7 days")
    else:
        print(f"  Auto-stop:           Set agreement_date in config when deal is reached")
    print(f"\n  Press Ctrl+C to stop.\n")

    while True:
        now = datetime.now(et)

        if now.weekday() >= 5:
            tomorrow = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
            sleep_secs = (tomorrow - now).total_seconds()
            print(f"  Weekend — sleeping until {tomorrow.strftime('%A %I:%M %p ET')}")
            time.sleep(min(sleep_secs, 3600))
            continue

        premarket_time = now.replace(
            hour=config["premarket_hour"],
            minute=config["premarket_minute"],
            second=0, microsecond=0,
        )
        midday_time = now.replace(
            hour=config["midday_hour"],
            minute=config["midday_minute"],
            second=0, microsecond=0,
        )

        upcoming = []
        if now < premarket_time:
            upcoming.append(("pre-market", premarket_time))
        if now < midday_time:
            upcoming.append(("midday", midday_time))

        if not upcoming:
            tomorrow_premarket = premarket_time + timedelta(days=1)
            sleep_secs = (tomorrow_premarket - now).total_seconds()
            print(f"  All briefings done for today. Next: {tomorrow_premarket.strftime('%A %I:%M %p ET')}")
            time.sleep(min(sleep_secs, 3600))
            continue

        session_type, target_time = upcoming[0]
        sleep_secs = (target_time - now).total_seconds()

        if sleep_secs > 60:
            print(f"  Next briefing: {session_type} at {target_time.strftime('%I:%M %p ET')} "
                  f"(in {int(sleep_secs // 3600)}h {int((sleep_secs % 3600) // 60)}m)")
            while sleep_secs > 30:
                time.sleep(min(sleep_secs, 60))
                now = datetime.now(et)
                sleep_secs = (target_time - now).total_seconds()

        should_continue = run_briefing(config, session_type)
        if not should_continue:
            print("\n  Scheduler stopped (auto-stop condition met).")
            break

        time.sleep(120)


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Iran Peace Talks Automated Market Briefing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python iran_briefing.py                  Run a single pre-market briefing now
  python iran_briefing.py --midday         Run a single midday briefing now
  python iran_briefing.py --schedule       Start the automated scheduler
  python iran_briefing.py --test-email     Send a test email to verify SMTP config
  python iran_briefing.py --set-agreement 2026-04-18   Set the agreement date
  python iran_briefing.py --reset-state    Delete state.json and start fresh
        """,
    )
    parser.add_argument("--schedule", action="store_true",
                        help="Run on automated schedule (9:00 AM & 12:30 PM ET)")
    parser.add_argument("--midday", action="store_true",
                        help="Run a midday briefing (default is pre-market)")
    parser.add_argument("--test-email", action="store_true",
                        help="Send a test email to verify SMTP configuration")
    parser.add_argument("--set-agreement", type=str, metavar="YYYY-MM-DD",
                        help="Record the date a peace agreement was reached")
    parser.add_argument("--reset-state", action="store_true",
                        help="Delete state.json so the next briefing starts from baseline hypotheses")
    args = parser.parse_args()

    config = load_config()

    if args.reset_state:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print(f"✓ Deleted {STATE_FILE}. Next briefing will start from baseline hypotheses.")
        else:
            print(f"No state file at {STATE_FILE}. Nothing to reset.")
        return

    if args.set_agreement:
        config_path = Path(__file__).parent / "config.json"
        file_config = {}
        if config_path.exists():
            with open(config_path) as f:
                file_config = json.load(f)
        file_config["agreement_date"] = args.set_agreement
        with open(config_path, "w") as f:
            json.dump(file_config, f, indent=2)
        print(f"✓ Agreement date set to {args.set_agreement}")
        print(f"  Briefings will auto-stop 7 days after this date.")
        return

    if args.test_email:
        config["email_enabled"] = True
        send_email(config, "Iran Briefing — Test Email",
                   "<html><body><h1>Test Successful</h1>"
                   "<p>Your email configuration is working. "
                   "Briefings will be delivered to this address.</p></body></html>")
        return

    if args.schedule:
        try:
            run_scheduler(config)
        except KeyboardInterrupt:
            print("\n\n  Scheduler stopped by user. Goodbye.\n")
        return

    session_type = "midday" if args.midday else "pre-market"
    run_briefing(config, session_type)


if __name__ == "__main__":
    main()
