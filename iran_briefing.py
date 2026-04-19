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
    python iran_briefing.py --schedule      # Run on schedule (midday briefing, 12:30 PM ET)
    python iran_briefing.py --test-email    # Send a test email to verify config
    python iran_briefing.py --reset-state   # Delete state.json, restart from baselines
"""

import argparse
import html as html_module
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
STATE_VERSION = 2


BASELINE_MOTIVES_US = [
    {
        "rank": 1,
        "title": "Strategic opportunism",
        "rationale": "Exploits Iran's post-2024 weakness — depleted proxies, economic strain, loss of Assad — to extract concessions that were not on the table before. Administration behavior tracks a 'press while weak' logic more than any fixed doctrine.",
        "trend": "flat",
    },
    {
        "rank": 2,
        "title": "Israeli alignment / Netanyahu partnership",
        "rationale": "Close operational coordination with the Netanyahu government. US posture on Lebanon, nuclear red lines, and timing of escalation has tracked Israeli security objectives more than its own stated policy.",
        "trend": "flat",
    },
    {
        "rank": 3,
        "title": "Legacy and strongman self-image",
        "rationale": "Seeks a historic, personally brandable deal. Willing to threaten maximalist outcomes and walk-away scenarios to produce a 'Nobel-worthy' win he can campaign on.",
        "trend": "flat",
    },
    {
        "rank": 4,
        "title": "Nuclear nonproliferation",
        "rationale": "A real but subordinate motive. Preventing weaponization remains a stated red line, yet the administration has shown willingness to trade duration and verification for face-saving deal structure.",
        "trend": "flat",
    },
    {
        "rank": 5,
        "title": "Energy and oil leverage",
        "rationale": "Conflict-driven oil-price swings are used for domestic political positioning. Gas prices shape the midterm narrative, giving the White House incentive to manage — not eliminate — the premium.",
        "trend": "flat",
    },
]

BASELINE_MOTIVES_IRAN = [
    {
        "rank": 1,
        "title": "Regime survival",
        "rationale": "The existential imperative of the Islamic Republic. Every other motive is instrumental to keeping the clerical system intact, and any deal that credibly threatens the regime is a non-starter regardless of economic cost.",
        "trend": "flat",
    },
    {
        "rank": 2,
        "title": "Economic leverage via Hormuz",
        "rationale": "Restricting Strait of Hormuz traffic is Iran's highest-value coercive tool given its effect on global oil and European allies. Tehran trades access for sanctions relief rather than giving it up wholesale.",
        "trend": "flat",
    },
    {
        "rank": 3,
        "title": "Deterrence restoration",
        "rationale": "After setbacks to proxies and conventional losses, Iran needs to re-establish that attacks on its interests carry real cost — otherwise further coercion by the US and Israel becomes cheap.",
        "trend": "flat",
    },
    {
        "rank": 4,
        "title": "Rally-the-flag nationalism",
        "rationale": "External pressure unifies the domestic population against dissent and is a useful counter to protest movements and economic grievances that have destabilized the regime in recent years.",
        "trend": "flat",
    },
    {
        "rank": 5,
        "title": "Preserving the Axis of Resistance",
        "rationale": "Hezbollah, the Houthis, Iraqi militias, and remnants of the Assad network are strategic depth worth protecting even at high cost — they are Iran's forward defensive perimeter.",
        "trend": "flat",
    },
]


# ─── Configuration ──────────────────────────────────────────────────────────

def load_config():
    """Load config from environment variables, falling back to config.json."""
    config_path = Path(__file__).parent / "config.json"
    file_config = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
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
        # GitHub Pages publishing (optional): copy HTML into docs/, rebuild index, commit + push.
        "publish_enabled": os.getenv("PUBLISH_ENABLED", str(file_config.get("publish_enabled", False))).lower() == "true",
        "site_title": os.getenv("SITE_TITLE", file_config.get("site_title", "Iran Peace Talks — Market Briefings")),
        # Second-pass verifier (optional): after each briefing, re-check cited/derived
        # claims with web search. Contradictions get auto-filed as corrections.
        "verify_enabled": os.getenv("VERIFY_ENABLED", str(file_config.get("verify_enabled", False))).lower() == "true",
        "verify_model": os.getenv("VERIFY_MODEL", file_config.get("verify_model", "sonnet")),
        "verify_effort": os.getenv("VERIFY_EFFORT", file_config.get("verify_effort", "medium")),
    }


# ─── The Analysis Framework (embedded system prompt) ────────────────────────

SYSTEM_PROMPT = """You are a geopolitical and financial analyst producing a daily briefing
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

Structure your briefing exactly as follows. The narrative <briefing> block is
for the human reader. The <state_update> block is for the automation system and
is the AUTHORITATIVE data for the tabbed HTML renderer and for the state carried
into the next briefing — it MUST be valid JSON. The <claims> block at the END
is for an automated fact-checker and MUST be valid JSON.

<briefing>
<header>
Briefing type (Pre-Market or Midday), timestamp, session identifier, and a one-
line market snapshot (S&P futures, Brent, Gold, VIX).
</header>

<situation_update>
2-3 paragraphs synthesizing what happened since the last briefing. Explicitly
address whether the previous "Key Watch" item resolved and how the previous
"Risk Alert" tail risks have evolved.
</situation_update>

<recent_headlines>
5-10 of the most significant headlines from the past ~12 hours (or since the
previous briefing, whichever is longer). One bullet per headline in the form:
"Source — one-sentence summary — https://url". The authoritative structured
list goes in <state_update>.recent_headlines.
</recent_headlines>

<motives_us>
1-2 short paragraphs on whether US / Trump-administration motives have shifted
since the last briefing, and why. The authoritative ranked list of five motives
goes in <state_update>.motives_us.
</motives_us>

<motives_iran>
1-2 short paragraphs on whether Iranian motives have shifted since the last
briefing, and why. The authoritative ranked list of five motives goes in
<state_update>.motives_iran.
</motives_iran>

<hypothesis_update>
1-2 paragraphs of narrative commentary on what moved this briefing: which
hypotheses shifted, any retired or newly introduced, and why. The authoritative
per-hypothesis data — probabilities, rationales, and per-sector market effects
conditional on that outcome — goes in <state_update>.hypotheses.
</hypothesis_update>

<key_watch>
The single most important thing to watch before the next briefing.
</key_watch>

<risk_alert>
Tail risks or surprises that could invalidate the current framework.
</risk_alert>
</briefing>

<state_update>
{
  "situation_snapshot": "2-3 sentence neutral summary of where things currently stand. Injected into the NEXT briefing's prompt so future-you has context.",
  "ceasefire_expiry": "YYYY-MM-DD expiry of the currently active ceasefire, or empty string if none/unknown. Update whenever news shows it was extended, renegotiated, replaced, or broken. If unchanged from the previous run, repeat the same date — do not omit the field.",
  "recent_headlines": [
    {
      "source": "CNN",
      "summary": "One-sentence summary of the headline in your own words.",
      "url": "https://www.cnn.com/..."
    }
  ],
  "motives_us": [
    {
      "rank": 1,
      "title": "Short motive name (e.g. 'Strategic opportunism').",
      "rationale": "2-4 sentences grounded in recent observable behavior — back-test against concrete actions from the last week.",
      "trend": "up | down | flat — direction of change since the previous briefing's ranking of this motive"
    }
  ],
  "motives_iran": [
    {
      "rank": 1,
      "title": "...",
      "rationale": "...",
      "trend": "up | down | flat"
    }
  ],
  "hypotheses": [
    {
      "id": "H1",
      "title": "The Can-Kick — Ceasefire Extension + Vague Framework",
      "probability": 38,
      "trend": "down",
      "one_line_rationale": "Under 25 words — the condensed memory carried into the NEXT briefing.",
      "display_rationale": "2-4 sentences explaining the current probability level for human readers of this briefing.",
      "market_effects": [
        {
          "sector": "Energy (XLE)",
          "direction": "bearish",
          "conviction": "moderate",
          "tickers": "XOM, CVX, COP, OXY",
          "note": "One-line reasoning for this sector call CONDITIONAL on this specific hypothesis playing out."
        }
      ]
    }
  ],
  "newly_retired_hypotheses": [
    {
      "id": "H_OLD",
      "title": "...",
      "reason": "Why retired in THIS briefing."
    }
  ],
  "newly_introduced_hypotheses": [
    {
      "id": "H6",
      "title": "...",
      "reason": "Why introduced in THIS briefing."
    }
  ],
  "previous_key_watch_for_next_run": "Copy the text of your <key_watch> section here verbatim.",
  "previous_risk_alert_for_next_run": "Copy the text of your <risk_alert> section here verbatim."
}
</state_update>

CRITICAL RULES FOR <state_update>:
- It MUST be valid JSON. No trailing commas, no comments, no markdown fences.
- All fields listed above must be present on every run. Missing fields break the
  tabbed HTML renderer and lose memory for the next briefing.
- "motives_us" and "motives_iran" must each contain EXACTLY 5 entries, ranked
  1-5. You may re-order them between briefings; use "trend" to show shifts.
- "hypotheses" contains ALL currently active scenarios. Anything not listed is
  treated as removed. Each must include a "market_effects" array covering at
  least Energy (XLE), Defense (ITA), Airlines (JETS), Tech (QQQ), Consumer
  Discretionary (XLY), Financials (XLF), Gold (GLD/GDX), Industrials (XLI),
  Utilities (XLU), Real Estate (XLRE), and Volatility (VIX / VXX / UVXY).
- "direction" must be one of: "bullish", "bearish", "neutral".
- "conviction" must be one of: "low", "moderate", "high".
- "newly_retired_hypotheses" and "newly_introduced_hypotheses" contain only
  changes made in THIS briefing. Empty arrays [] if nothing changed.
- Probabilities are integers 0-100 and should sum to ~100 across active
  hypotheses. Trend is "up", "down", or "flat".
- Keep "one_line_rationale" under 25 words.
- "recent_headlines" should contain 5-10 entries with real URLs from the
  current web search results.
- "ceasefire_expiry" must always be present.

IMPORTANT: Be specific and actionable. Use concrete numbers, name specific tickers,
give clear directional calls. Hedge where genuinely uncertain, but don't be vague
for the sake of caution. This briefing exists to support decision-making.

IMPORTANT: Respect copyright. Paraphrase all source material. Never quote more
than a few words from any source. Cite sources by name but summarize in your own
words.

## <claims> BLOCK (for automated fact-checker)

After the <state_update> block, emit a <claims> block listing the verifiable
factual claims your briefing depends on. A second-pass automated verifier will
web-fetch sources and sanity-check derivations; anything it contradicts will be
auto-filed as a public correction on this briefing.

Target 6-12 claims. Prioritize:
- Specific quoted figures and statistics (oil prices, percentages, thresholds).
- Named attributions ("General X said Y on date Z").
- Elapsed-time claims ("36 hours since...", "72 hours without...").
- Arithmetic or dated calculations based on other facts in the briefing.
- Any claim the analysis hinges on; if wrong, probabilities would shift.

Do NOT list:
- Your own hypothesis probabilities or analytical conclusions.
- Generic framing ("oil markets are volatile").
- Non-falsifiable statements.

Each claim has four fields:
- "id": "C1", "C2", ... (unique within this briefing).
- "claim": one self-contained sentence stating the fact as the briefing presents it.
- "source_url": the specific URL that should support this claim. Empty string
  only if the claim is purely derived (arithmetic, elapsed-time from other facts).
- "kind": "cited" if verifiable by fetching source_url, or "derived" if it
  depends on calculation or on facts asserted elsewhere in the briefing.

<claims>
[
  {
    "id": "C1",
    "claim": "Brent crude closed at $82.40/bbl on 2026-04-17.",
    "source_url": "https://www.example.com/markets/brent-close",
    "kind": "cited"
  },
  {
    "id": "C2",
    "claim": "It has been ~36 hours since the last Iranian Red Sea threat activation.",
    "source_url": "",
    "kind": "derived"
  }
]
</claims>

CRITICAL RULES FOR <claims>:
- It MUST be valid JSON (a list). No trailing commas, no comments, no markdown fences.
- IDs must be unique within the briefing.
- If the briefing truly has nothing verifiable (e.g., pure editorial), emit [].
- "source_url" for a "cited" claim should be the SAME URL you cite in
  <recent_headlines> or <state_update>.recent_headlines — don't invent a new one."""


USER_PROMPT_TEMPLATE = """Generate the {session_type} briefing for {date_str}.

Today's date is {date_str}. The current time is {time_str} ET.
The NYSE {market_status}.
{ceasefire_line}

{previous_state_block}
{corrections_block}
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

def _fresh_state() -> dict:
    return {
        "version": STATE_VERSION,
        "briefings_count": 0,
        "hypotheses": [],
        "retired_hypotheses": [],
        "situation_snapshot": "",
        "previous_key_watch": "",
        "previous_risk_alert": "",
        "ceasefire_expiry": "2026-04-21",
        "motives_us": [dict(m) for m in BASELINE_MOTIVES_US],
        "motives_iran": [dict(m) for m in BASELINE_MOTIVES_IRAN],
        "last_updated": "",
        "last_briefing_file": "",
    }


def load_state() -> dict:
    """Load the persistent state, applying defaults for any missing keys."""
    if not STATE_FILE.exists():
        return _fresh_state()
    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)
    # Forward-migrate older state files by filling in any new keys with defaults
    for key, value in _fresh_state().items():
        state.setdefault(key, value)
    return state


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

    if state.get("motives_us"):
        lines.append("")
        lines.append("### US / Trump administration motives at end of last briefing (ranked):")
        for m in sorted(state["motives_us"], key=lambda x: x.get("rank", 99)):
            trend_arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(m.get("trend", "flat"), "→")
            lines.append(
                f"- **{m.get('rank', '?')}. {m.get('title', '')}** {trend_arrow} — {m.get('rationale', '')}"
            )

    if state.get("motives_iran"):
        lines.append("")
        lines.append("### Iranian motives at end of last briefing (ranked):")
        for m in sorted(state["motives_iran"], key=lambda x: x.get("rank", 99)):
            trend_arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(m.get("trend", "flat"), "→")
            lines.append(
                f"- **{m.get('rank', '?')}. {m.get('title', '')}** {trend_arrow} — {m.get('rationale', '')}"
            )

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


def extract_claims(briefing_text: str):
    """Pull the JSON <claims> block out of Claude's output. Returns a list or None."""
    match = re.search(r"<claims>(.*?)</claims>", briefing_text, re.DOTALL)
    if not match:
        return None
    json_text = match.group(1).strip()
    json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
    json_text = re.sub(r"\s*```$", "", json_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  ⚠ Failed to parse <claims> JSON: {e}")
        return None
    if not isinstance(data, list):
        print(f"  ⚠ <claims> block was not a JSON list; got {type(data).__name__}.")
        return None
    return data


def strip_claims(briefing_text: str) -> str:
    """Remove the <claims> block so it isn't rendered in the HTML."""
    return re.sub(r"<claims>.*?</claims>", "", briefing_text, flags=re.DOTALL).strip()


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

    # Carry these fields forward unless the model explicitly updated them.
    # Presence of the key in new_update (even if empty) counts as explicit.
    def _carry(key: str, default):
        if key in new_update:
            return new_update[key]
        return old_state.get(key, default)

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
        "ceasefire_expiry": _carry("ceasefire_expiry", ""),
        "motives_us": _carry("motives_us", [dict(m) for m in BASELINE_MOTIVES_US]),
        "motives_iran": _carry("motives_iran", [dict(m) for m in BASELINE_MOTIVES_IRAN]),
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

    pending = pending_corrections()
    if pending:
        print(f"  ⚠ Injecting {len(pending)} pending correction(s) into the analyst prompt.")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        session_type=session_type.replace("-", " ").title(),
        date_str=date_str,
        time_str=time_str,
        market_status=market_status,
        ceasefire_line=ceasefire_line,
        previous_state_block=format_state_for_prompt(state),
        corrections_block=format_corrections_for_prompt(pending),
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
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise RuntimeError(
            f"Claude Code returned exit code {result.returncode}.\n"
            f"stderr: {stderr[:2000]}"
        )

    return _decode_claude_output(result.stdout).strip()


VERIFIER_SYSTEM_PROMPT = """You are an automated fact-checker for a published
geopolitical market briefing. Another Claude just produced the briefing; you
are a second pass. Your sole job is to verify the factual claims it listed and
return a strict JSON verdict array.

For each CLAIM:
- If kind is "cited": fetch source_url with WebFetch and check whether the page
  actually supports the claim. If the URL fails or the page doesn't cover it,
  try web search as a fallback before giving up.
- If kind is "derived": sanity-check the reasoning. For elapsed-time claims
  ("~36 hours since X"), web-search to find when X actually happened and do the
  arithmetic. For dollar/percentage math, verify the inputs and compute.

Status rubric (be calibrated, not hair-trigger):
- "verified": clearly supported by the source or by checkable computation.
- "contradicted": clearly wrong — source says something materially different,
  or the arithmetic is off by a meaningful margin. Small rounding (e.g., 36 vs
  35 hours) is NOT a contradiction; a 2x error (36 vs 18 hours) IS.
- "unverified": you couldn't determine (URL dead, search returned nothing
  usable). Do NOT mark "contradicted" just because you can't verify.

Return ONLY a JSON array. No prose, no markdown fences, no commentary. One
entry per claim in the input:

[
  {
    "claim_id": "C1",
    "status": "verified" | "contradicted" | "unverified",
    "note": "For contradicted: state the CORRECT fact and where it came from — this text is published as a public correction. For verified/unverified: brief one-liner.",
    "summary": "Under 80 characters. Used as a hover tooltip on the correction banner. Only meaningful for 'contradicted'; for others a short stub is fine."
  }
]"""


VERIFIER_USER_TEMPLATE = """Verify the following claims from a briefing
published at {timestamp}.

CLAIMS (JSON):
{claims_json}

Return only the JSON verdict array, one entry per claim, matching the schema in
your system prompt."""


def verify_briefing(claims: list, config: dict, timestamp: str):
    """Second-pass verifier. Returns a list of verdicts, or None on failure.

    Each verdict is {claim_id, status, note, summary}. Best-effort: on any
    error we log and return None so the briefing still ships.
    """
    if not claims:
        return []

    claims_json = json.dumps(claims, ensure_ascii=False, indent=2)
    user_prompt = VERIFIER_USER_TEMPLATE.format(
        timestamp=timestamp,
        claims_json=claims_json,
    )

    model = config.get("verify_model", "sonnet")
    effort = config.get("verify_effort", "medium")
    print(f"  Running verifier (model={model}, effort={effort}) on {len(claims)} claim(s)...")

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", user_prompt,
                "--model", model,
                "--effort", effort,
                "--system-prompt", VERIFIER_SYSTEM_PROMPT,
                "--tools", "WebSearch,WebFetch",
                "--permission-mode", "bypassPermissions",
                "--output-format", "text",
            ],
            capture_output=True,
            timeout=1200,
        )
    except FileNotFoundError:
        print("  ⚠ Verifier skipped: 'claude' CLI not on PATH.")
        return None
    except subprocess.TimeoutExpired:
        print("  ⚠ Verifier timed out after 20 minutes — skipping.")
        return None

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        print(f"  ⚠ Verifier exited {result.returncode}: {stderr[:500]}")
        return None

    raw = _decode_claude_output(result.stdout).strip()
    # Tolerate optional markdown fences or stray prose around the JSON array.
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, flags=re.DOTALL)
    if fence_match:
        json_text = fence_match.group(1)
    else:
        array_match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
        if not array_match:
            print(f"  ⚠ Verifier output had no JSON array. First 300 chars: {raw[:300]!r}")
            return None
        json_text = array_match.group(0)

    try:
        verdicts = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  ⚠ Failed to parse verifier JSON: {e}")
        return None

    if not isinstance(verdicts, list):
        print(f"  ⚠ Verifier output was not a list; got {type(verdicts).__name__}.")
        return None

    return verdicts


def file_verifier_corrections(
    verdicts: list,
    claims: list,
    briefing_filename: str,
) -> int:
    """Append every 'contradicted' verdict to corrections.json for this briefing.

    Returns the number of entries added. Manual corrections (added via
    --add-correction) are untouched; auto-filed entries carry
    source="auto_verifier" and a "summary" field used for the hover tooltip.
    """
    claim_by_id = {str(c.get("id", "")): c for c in claims}

    to_add = []
    for v in verdicts or []:
        if v.get("status") != "contradicted":
            continue
        claim = claim_by_id.get(str(v.get("claim_id", "")), {})
        claim_text = claim.get("claim", "(original claim text unavailable)")
        source_url = claim.get("source_url", "")
        note_body = v.get("note", "").strip() or "(verifier returned no explanation)"
        body = f"Original claim: {claim_text}\nVerifier finding: {note_body}"
        if source_url:
            body += f"\nOriginal source cited: {source_url}"
        to_add.append({
            "summary": v.get("summary", "").strip()[:160] or "Claim contradicted by verifier.",
            "note": body,
        })

    if not to_add:
        return 0

    data = load_corrections()
    added_at = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    for entry in to_add:
        data.setdefault(briefing_filename, []).append({
            "added_at": added_at,
            "source": "auto_verifier",
            "summary": entry["summary"],
            "note": entry["note"],
        })
    save_corrections(data)
    return len(to_add)


def _decode_claude_output(raw_bytes: bytes) -> str:
    """Decode Claude CLI stdout bytes, fixing Windows cp1252 mojibake if needed.

    On some Windows installations the claude.cmd wrapper emits UTF-8 bytes that
    get re-interpreted via the console code page somewhere in the pipeline,
    producing double-encoded mojibake like 'â€"' for em-dash and 'ðŸ"´' for 🔴.
    We decode as UTF-8 first; if the result contains telltale mojibake
    signatures, we round-trip through cp1252 to recover the original characters.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    mojibake_markers = ("ðŸ", "â€", "Â·", "Ã©", "Ã¨", "Ã¡")
    if any(marker in text for marker in mojibake_markers):
        try:
            recovered = text.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
            text = recovered
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            pass
    return text


# ─── HTML Formatting ────────────────────────────────────────────────────────

TREND_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


def _extract_section(raw_text: str, tag: str) -> str:
    match = re.search(fr"<{tag}>(.*?)</{tag}>", raw_text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _narrative_to_html(text: str) -> str:
    """Minimal markdown-ish conversion for narrative sections."""
    if not text:
        return ""
    escaped = html_module.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"(https?://[^\s<>)\]]+)",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        escaped,
    )
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", escaped) if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paragraphs)


def _render_headlines(state_update: dict | None, raw_text: str) -> str:
    items = (state_update or {}).get("recent_headlines") or []
    if items:
        rendered = []
        for h in items:
            source = html_module.escape((h.get("source") or "").strip())
            summary = html_module.escape((h.get("summary") or "").strip())
            url = (h.get("url") or "").strip()
            link = (
                f' <a href="{html_module.escape(url)}" target="_blank" rel="noopener">[link]</a>'
                if url else ""
            )
            rendered.append(f"<li><strong>{source}</strong> — {summary}{link}</li>")
        return "<ul class='headlines'>" + "".join(rendered) + "</ul>"
    narrative = _narrative_to_html(_extract_section(raw_text, "recent_headlines"))
    return narrative or "<p><em>No recent-headlines data in this briefing.</em></p>"


def _render_motives(motives: list, narrative_tag: str, raw_text: str) -> str:
    parts = []
    narrative = _narrative_to_html(_extract_section(raw_text, narrative_tag))
    if narrative:
        parts.append(f'<div class="motives-narrative">{narrative}</div>')
    if motives:
        parts.append("<ol class='motives'>")
        for m in sorted(motives, key=lambda x: x.get("rank", 99)):
            title = html_module.escape((m.get("title") or "").strip())
            rationale = html_module.escape((m.get("rationale") or "").strip())
            arrow = TREND_ARROW.get((m.get("trend") or "flat").lower(), "→")
            parts.append(
                f'<li><div class="motive-title">{title} '
                f'<span class="trend">{arrow}</span></div>'
                f'<div class="motive-rationale">{rationale}</div></li>'
            )
        parts.append("</ol>")
    elif not narrative:
        parts.append("<p><em>No motive data in this briefing.</em></p>")
    return "\n".join(parts)


def _render_outcomes(state_update: dict | None, raw_text: str) -> str:
    parts = []
    narrative = _narrative_to_html(_extract_section(raw_text, "hypothesis_update"))
    if narrative:
        parts.append(f'<div class="outcome-narrative">{narrative}</div>')

    hypotheses = (state_update or {}).get("hypotheses") or []
    if not hypotheses:
        if not narrative:
            parts.append("<p><em>No hypothesis data in this briefing.</em></p>")
        return "\n".join(parts)

    direction_class = {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral"}
    for h in hypotheses:
        h_id = html_module.escape((h.get("id") or "?").strip())
        title = html_module.escape((h.get("title") or "").strip())
        prob = h.get("probability", "?")
        arrow = TREND_ARROW.get((h.get("trend") or "flat").lower(), "→")
        display_rationale = html_module.escape(
            (h.get("display_rationale") or h.get("one_line_rationale") or "").strip()
        )

        effects_rows = []
        for eff in h.get("market_effects") or []:
            sector = html_module.escape((eff.get("sector") or "").strip())
            direction_raw = (eff.get("direction") or "neutral").lower()
            dir_class = direction_class.get(direction_raw, "neutral")
            dir_label = html_module.escape(direction_raw.upper())
            conviction = html_module.escape((eff.get("conviction") or "").strip())
            tickers = html_module.escape((eff.get("tickers") or "").strip())
            note = html_module.escape((eff.get("note") or "").strip())
            effects_rows.append(
                f"<tr>"
                f"<td class='sector'>{sector}</td>"
                f"<td class='direction {dir_class}'>{dir_label}</td>"
                f"<td class='conviction'>{conviction}</td>"
                f"<td class='tickers'>{tickers}</td>"
                f"<td class='note'>{note}</td>"
                f"</tr>"
            )

        if effects_rows:
            effects_html = (
                '<details class="market-effects">'
                '<summary>Market Effects</summary>'
                '<table class="effects-table">'
                '<thead><tr><th>Sector</th><th>Direction</th>'
                '<th>Conviction</th><th>Tickers</th><th>Note</th></tr></thead>'
                f'<tbody>{"".join(effects_rows)}</tbody>'
                '</table>'
                '</details>'
            )
        else:
            effects_html = '<p class="no-effects"><em>No per-sector effects provided for this outcome.</em></p>'

        parts.append(
            f'<details class="hypothesis" open>'
            f'<summary>'
            f'<span class="hyp-id">{h_id}</span>'
            f'<span class="hyp-prob">{prob}% {arrow}</span>'
            f'<span class="hyp-title">{title}</span>'
            f'</summary>'
            f'<div class="hyp-body">'
            f'<p class="hyp-rationale">{display_rationale}</p>'
            f'{effects_html}'
            f'</div>'
            f'</details>'
        )
    return "\n".join(parts)


def format_html_briefing(
    raw_text: str,
    session_type: str,
    timestamp: str,
    state_update: dict | None,
    ceasefire_expiry: str,
) -> str:
    """Render the briefing as a tabbed HTML page driven primarily by state_update JSON."""

    stype = session_type.lower()
    if "pre" in stype:
        session_label = "Pre-Market Briefing"
    elif "midday" in stype:
        session_label = "Midday Briefing"
    else:
        session_label = "On-Demand Briefing"

    situation_html = _narrative_to_html(_extract_section(raw_text, "situation_update")) \
        or "<p><em>No situation update in this briefing.</em></p>"
    headlines_html = _render_headlines(state_update, raw_text)
    motives_us_html = _render_motives(
        (state_update or {}).get("motives_us") or [],
        "motives_us",
        raw_text,
    )
    motives_iran_html = _render_motives(
        (state_update or {}).get("motives_iran") or [],
        "motives_iran",
        raw_text,
    )
    outcomes_html = _render_outcomes(state_update, raw_text)
    key_watch_html = _narrative_to_html(_extract_section(raw_text, "key_watch")) \
        or "<p><em>No key watch item.</em></p>"
    risk_alert_html = _narrative_to_html(_extract_section(raw_text, "risk_alert")) \
        or "<p><em>No risk alert.</em></p>"

    # Header + ceasefire countdown
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    countdown = "Automated Geopolitical & Market Analysis"
    if ceasefire_expiry:
        try:
            expiry_dt = datetime.strptime(ceasefire_expiry, "%Y-%m-%d").replace(tzinfo=et)
            days = (expiry_dt - now).days
            if days >= 0:
                countdown = f"Ceasefire expires {ceasefire_expiry} · {days} day(s) out"
            else:
                countdown = f"Ceasefire expired {abs(days)} day(s) ago ({ceasefire_expiry})"
        except ValueError:
            pass

    css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: Georgia, 'Times New Roman', serif;
        background: #fafaf8;
        color: #1a1a1a;
        line-height: 1.6;
        max-width: 960px;
        margin: 0 auto;
        padding: 24px 20px 48px;
    }
    .masthead {
        border-bottom: 3px double #1a1a1a;
        padding-bottom: 12px;
        margin-bottom: 18px;
    }
    .masthead h1 { font-size: 22px; letter-spacing: -0.02em; }
    .masthead .meta {
        font-size: 13px;
        color: #666;
        font-style: italic;
        margin-top: 4px;
    }
    .tab-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        border-bottom: 1px solid #ccc;
        margin-bottom: 20px;
    }
    .tab-btn {
        background: #f0ede8;
        border: 1px solid #ccc;
        border-bottom: none;
        padding: 9px 16px;
        font-family: inherit;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        color: #555;
        border-radius: 5px 5px 0 0;
        margin-bottom: -1px;
    }
    .tab-btn:hover { background: #e8e4dc; color: #1a1a1a; }
    .tab-btn.active {
        background: #fafaf8;
        color: #1a1a1a;
        border-bottom: 1px solid #fafaf8;
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .tab-panel h2 {
        font-size: 18px;
        margin-bottom: 14px;
        color: #2c2c2c;
        border-bottom: 1px solid #e0ddd8;
        padding-bottom: 6px;
    }
    .tab-panel h2:not(:first-child) { margin-top: 26px; }
    .tab-panel p { margin-bottom: 12px; font-size: 14px; }
    .tab-panel a { color: #3a6ea5; text-decoration: none; }
    .tab-panel a:hover { text-decoration: underline; }
    strong { font-weight: 700; }

    ul.headlines { list-style: none; padding: 0; }
    ul.headlines li {
        padding: 11px 14px;
        margin-bottom: 8px;
        background: #fff;
        border-left: 3px solid #3a6ea5;
        font-size: 14px;
    }

    .motives-narrative { margin-bottom: 14px; }
    ol.motives { list-style: none; counter-reset: motive; padding: 0; }
    ol.motives li {
        counter-increment: motive;
        padding: 12px 14px 12px 48px;
        margin-bottom: 8px;
        background: #fff;
        border-left: 3px solid #8a5a3a;
        font-size: 14px;
        position: relative;
    }
    ol.motives li::before {
        content: counter(motive);
        position: absolute;
        left: 14px;
        top: 11px;
        font-weight: 700;
        font-size: 18px;
        color: #8a5a3a;
    }
    .motive-title { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
    .motive-title .trend { color: #888; font-weight: 400; margin-left: 6px; }
    .motive-rationale { font-size: 13px; color: #444; line-height: 1.55; }

    .outcome-narrative { margin-bottom: 18px; font-size: 14px; }
    details.hypothesis {
        background: #fff;
        border: 1px solid #ddd;
        border-left: 4px solid #3a6ea5;
        border-radius: 4px;
        margin-bottom: 12px;
    }
    details.hypothesis[open] { border-left-color: #1a4e8a; }
    details.hypothesis > summary {
        padding: 12px 16px;
        font-size: 15px;
        cursor: pointer;
        list-style: none;
        font-family: inherit;
        display: flex;
        gap: 12px;
        align-items: baseline;
    }
    details.hypothesis > summary::-webkit-details-marker { display: none; }
    details.hypothesis > summary::before {
        content: "▸";
        color: #888;
        font-size: 12px;
    }
    details.hypothesis[open] > summary::before { content: "▾"; }
    .hyp-id { font-weight: 700; color: #3a6ea5; min-width: 30px; }
    .hyp-prob { font-weight: 700; color: #1a1a1a; min-width: 70px; }
    .hyp-title { color: #2c2c2c; flex: 1; }
    .hyp-body { padding: 4px 16px 14px; border-top: 1px solid #eee; }
    .hyp-rationale { margin: 12px 0; font-size: 14px; color: #333; }

    details.market-effects {
        margin-top: 10px;
        background: #f7f6f2;
        border: 1px solid #e0ddd8;
        border-radius: 4px;
    }
    details.market-effects > summary {
        padding: 8px 12px;
        font-weight: 700;
        font-size: 13px;
        cursor: pointer;
        color: #555;
        list-style: none;
    }
    details.market-effects > summary::-webkit-details-marker { display: none; }
    details.market-effects > summary::before {
        content: "▸ ";
        color: #888;
    }
    details.market-effects[open] > summary::before { content: "▾ "; }
    .effects-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }
    .effects-table th, .effects-table td {
        padding: 6px 10px;
        text-align: left;
        border-top: 1px solid #e0ddd8;
        vertical-align: top;
    }
    .effects-table th { background: #e8e4dc; font-weight: 700; color: #444; }
    .effects-table td.direction { font-weight: 700; white-space: nowrap; }
    .effects-table td.direction.bullish { color: #1f7a3a; }
    .effects-table td.direction.bearish { color: #a8352a; }
    .effects-table td.direction.neutral { color: #888; }
    .effects-table td.tickers { font-family: Consolas, 'Courier New', monospace; font-size: 11px; color: #444; }
    .effects-table td.note { color: #555; }

    .footer {
        margin-top: 30px;
        padding-top: 14px;
        border-top: 1px solid #ddd;
        font-size: 11px;
        color: #999;
        font-style: italic;
    }
    @media (prefers-color-scheme: dark) {
        body { background: #1a1a1a; color: #e0e0e0; }
        .masthead { border-color: #555; }
        .masthead .meta { color: #999; }
        .tab-bar { border-bottom-color: #444; }
        .tab-btn { background: #252525; border-color: #444; color: #aaa; }
        .tab-btn:hover { background: #303030; color: #e0e0e0; }
        .tab-btn.active { background: #1a1a1a; color: #e0e0e0; border-bottom-color: #1a1a1a; }
        .tab-panel h2 { color: #e0e0e0; border-bottom-color: #3a3a3a; }
        ul.headlines li, ol.motives li, details.hypothesis { background: #252525; border-color: #444; }
        details.hypothesis { border-left-color: #4a7eb5; }
        details.hypothesis[open] { border-left-color: #6fa8dc; }
        details.market-effects { background: #202020; border-color: #3a3a3a; }
        .effects-table th { background: #303030; color: #ccc; }
        .effects-table th, .effects-table td { border-color: #3a3a3a; }
        .effects-table td.direction.bullish { color: #7dc88e; }
        .effects-table td.direction.bearish { color: #e38a80; }
        .hyp-id, .tab-panel a { color: #6fa8dc; }
        .hyp-title, .hyp-prob { color: #e0e0e0; }
        .motive-rationale, .hyp-rationale, .effects-table td.note { color: #ccc; }
        .effects-table td.tickers { color: #bbb; }
    }
    """

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Iran Peace Talks — {session_label} — {timestamp}</title>
<style>{css}</style>
</head>
<body>
<div class="masthead">
  <h1>Iran Peace Talks — {session_label}</h1>
  <div class="meta">{timestamp} ET · {countdown}</div>
</div>

<div class="tab-bar">
  <button type="button" class="tab-btn active" data-tab="tab-situation">Situation</button>
  <button type="button" class="tab-btn" data-tab="tab-headlines">Recent Headlines</button>
  <button type="button" class="tab-btn" data-tab="tab-motives">Motives</button>
  <button type="button" class="tab-btn" data-tab="tab-outcomes">Probable Outcomes</button>
  <button type="button" class="tab-btn" data-tab="tab-watch">Key Watch</button>
  <button type="button" class="tab-btn" data-tab="tab-risks">Risk Alert</button>
</div>

<div class="tab-panel active" id="tab-situation">
  <h2>Situation Update</h2>
  {situation_html}
</div>
<div class="tab-panel" id="tab-headlines">
  <h2>Recent Headlines</h2>
  {headlines_html}
</div>
<div class="tab-panel" id="tab-motives">
  <h2>US / Trump Administration Motives</h2>
  {motives_us_html}
  <h2>Iran Motives</h2>
  {motives_iran_html}
</div>
<div class="tab-panel" id="tab-outcomes">
  <h2>Probable Outcomes</h2>
  {outcomes_html}
</div>
<div class="tab-panel" id="tab-watch">
  <h2>Key Watch</h2>
  {key_watch_html}
</div>
<div class="tab-panel" id="tab-risks">
  <h2>Risk Alert</h2>
  {risk_alert_html}
</div>

<div class="footer">
  Automated analytical commentary generated via Claude Code with web search.
  Not investment advice. Sources paraphrased to respect copyright. Consult a
  licensed financial advisor before making investment decisions.
</div>

<script>
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  }});
}});
</script>
</body>
</html>"""
    return html_doc


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

# ─── GitHub Pages publishing ────────────────────────────────────────────────

BRIEFING_FILENAME_RE = re.compile(
    r"^briefing_(\d{8})_(\d{4})_([a-z_]+)\.html$"
)


def _parse_briefing_filename(name: str):
    """Return (datetime, session_label) for a briefing filename, or None if it doesn't match."""
    m = BRIEFING_FILENAME_RE.match(name)
    if not m:
        return None
    date_str, time_str, session_slug = m.groups()
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M")
    except ValueError:
        return None
    label = session_slug.replace("_", " ").title()
    return dt, label


def _build_index_html(site_title: str, briefings: list) -> str:
    """Render docs/index.html given a list of briefings sorted newest-first.

    Each briefing is a dict: {filename, datetime, label}. The newest is loaded
    in an iframe by default; clicking another tab swaps the iframe src.
    """
    if not briefings:
        body_inner = "<p style='padding:2rem;color:#6b6b6b'>No briefings published yet.</p>"
        tabs_html = ""
    else:
        latest = briefings[0]
        tab_items = []
        for i, b in enumerate(briefings):
            date_label = b["datetime"].strftime("%b %d")
            time_label = b["datetime"].strftime("%-I:%M %p") if os.name != "nt" else b["datetime"].strftime("%#I:%M %p")
            active = " active" if i == 0 else ""
            n_corrections = b.get("corrections", 0)
            marker = (
                f'<span class="tab-corrections" title="{n_corrections} correction(s) on this briefing">⚠ {n_corrections}</span>'
                if n_corrections else ""
            )
            tooltip = f'{b["label"]} — {b["datetime"].strftime("%Y-%m-%d %H:%M")}'
            if n_corrections:
                tooltip += f" — {n_corrections} correction(s)"
            tab_items.append(
                f'<button class="folder-tab{active}" '
                f'data-src="briefings/{html_module.escape(b["filename"])}" '
                f'title="{html_module.escape(tooltip)}">'
                f'<span class="tab-date">{date_label}{marker}</span>'
                f'<span class="tab-meta">{html_module.escape(b["label"])} · {time_label}</span>'
                f'</button>'
            )
        tabs_html = "\n".join(tab_items)
        body_inner = (
            f'<iframe id="briefing-frame" src="briefings/{html_module.escape(latest["filename"])}" '
            f'title="Latest briefing"></iframe>'
        )

    updated = datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y %I:%M %p ET")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_module.escape(site_title)}</title>
<style>
  :root {{
    --folder-bg: #f5e9c8;
    --folder-edge: #c9b483;
    --folder-active: #fff8e1;
    --page-bg: #efe7d3;
    --ink: #2c2a26;
    --ink-soft: #6b6b6b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--page-bg);
    color: var(--ink);
  }}
  header {{
    padding: 1rem 1.25rem 0.5rem;
    border-bottom: 1px solid var(--folder-edge);
    background: var(--page-bg);
  }}
  header h1 {{
    margin: 0;
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0.01em;
  }}
  header .updated {{
    margin-top: 0.15rem;
    font-size: 0.78rem;
    color: var(--ink-soft);
  }}
  .tab-strip {{
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    gap: 2px;
    padding: 0.75rem 1rem 0;
    background: var(--page-bg);
    scrollbar-width: thin;
  }}
  .folder-tab {{
    flex: 0 0 auto;
    background: var(--folder-bg);
    border: 1px solid var(--folder-edge);
    border-bottom: none;
    border-radius: 10px 10px 0 0;
    padding: 0.5rem 0.9rem 0.55rem;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    line-height: 1.15;
    color: var(--ink);
    box-shadow: inset 0 -3px 0 rgba(0,0,0,0.04);
    transition: background 0.12s;
  }}
  .folder-tab:hover {{ background: #fbeec3; }}
  .folder-tab.active {{
    background: var(--folder-active);
    box-shadow: inset 0 -3px 0 var(--folder-active);
    position: relative;
    z-index: 2;
  }}
  .folder-tab .tab-date {{
    display: block;
    font-weight: 600;
    font-size: 0.85rem;
  }}
  .folder-tab .tab-meta {{
    display: block;
    font-size: 0.7rem;
    color: var(--ink-soft);
    margin-top: 0.1rem;
  }}
  .folder-tab .tab-corrections {{
    display: inline-block;
    margin-left: 0.4rem;
    padding: 0 0.35rem;
    border-radius: 8px;
    background: #ffd76b;
    color: #604700;
    font-size: 0.65rem;
    font-weight: 600;
    vertical-align: middle;
  }}
  .frame-wrap {{
    background: #fff;
    border-top: 2px solid var(--folder-edge);
    height: calc(100vh - 130px);
    min-height: 400px;
  }}
  #briefing-frame {{
    width: 100%;
    height: 100%;
    border: 0;
    display: block;
    background: #fff;
  }}
  footer {{
    padding: 0.6rem 1.25rem;
    font-size: 0.72rem;
    color: var(--ink-soft);
    text-align: center;
  }}
</style>
</head>
<body>
<header>
  <h1>{html_module.escape(site_title)}</h1>
  <div class="updated">Index updated {html_module.escape(updated)} · {len(briefings)} briefing{'s' if len(briefings) != 1 else ''} on file</div>
</header>
<nav class="tab-strip" aria-label="Briefing archive">
{tabs_html}
</nav>
<main class="frame-wrap">
{body_inner}
</main>
<footer>Automated analytical commentary generated via Claude Code with web search. Not investment advice.</footer>
<script>
  document.querySelectorAll('.folder-tab').forEach(tab => {{
    tab.addEventListener('click', () => {{
      document.querySelectorAll('.folder-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const src = tab.getAttribute('data-src');
      const frame = document.getElementById('briefing-frame');
      if (frame && src) frame.src = src;
    }});
  }});
</script>
</body>
</html>
"""


CORRECTIONS_FILE = Path(__file__).parent / "corrections.json"


def load_corrections() -> dict:
    """Load corrections.json (a map of briefing filename → list of correction entries)."""
    if not CORRECTIONS_FILE.exists():
        return {}
    try:
        with open(CORRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠ Could not read {CORRECTIONS_FILE.name}: {e}")
        return {}


def save_corrections(data: dict) -> None:
    with open(CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def pending_corrections() -> list:
    """Return correction entries that have not yet been delivered to an analyst run.

    Each result is a dict: {briefing, added_at, note}. The 'briefing' field is
    the filename of the briefing the correction applies to, so the analyst can
    reason about which prior conclusions might need revising.
    """
    data = load_corrections()
    pending = []
    for briefing, entries in data.items():
        for entry in entries:
            if entry.get("delivered_to_briefing"):
                continue
            pending.append({
                "briefing": briefing,
                "added_at": entry.get("added_at", ""),
                "note": entry.get("note", ""),
            })
    pending.sort(key=lambda c: c["added_at"])
    return pending


def mark_corrections_delivered(delivered_to_filename: str) -> int:
    """Mark every currently-pending correction as delivered to the given briefing.

    Returns the number of correction entries that were marked. Safe to call
    even if there are none pending.
    """
    data = load_corrections()
    n = 0
    for entries in data.values():
        for entry in entries:
            if not entry.get("delivered_to_briefing"):
                entry["delivered_to_briefing"] = delivered_to_filename
                n += 1
    if n:
        save_corrections(data)
    return n


def format_corrections_for_prompt(pending: list) -> str:
    """Render the corrections section that gets injected into the analyst prompt."""
    if not pending:
        return ""
    lines = [
        "",
        "## CORRECTIONS TO PRIOR BRIEFINGS",
        "",
        "The following factual errors were identified in earlier briefings *after* they were "
        "published. The hypothesis probabilities, motive rankings, and other state you inherited "
        "above were computed using the ERRONEOUS facts. Re-evaluate any inherited conclusion that "
        "depended on a corrected fact, and revise probabilities accordingly in this briefing's "
        "<state_update>. If a correction does not affect a current conclusion, you may ignore it.",
        "",
    ]
    for i, c in enumerate(pending, 1):
        lines.append(f"**Correction {i}** (on `{c['briefing']}`, recorded {c['added_at']}):")
        lines.append(c["note"])
        lines.append("")
    return "\n".join(lines)


def _render_correction_banner(entries: list) -> str:
    """Render a yellow banner listing all corrections for one briefing.

    The banner is injected into the published copy of the briefing HTML. If
    any entry was auto-filed by the verifier (source=="auto_verifier"), the
    banner gets a `title` hover tooltip summarizing those findings.

    Each entry: {"added_at": ISO, "note": "...", "source"?: str, "summary"?: str}
    """
    items = []
    auto_summaries = []
    for e in entries:
        added_at = html_module.escape(e.get("added_at", ""))
        note = html_module.escape(e.get("note", "")).replace("\n", "<br>")
        source = e.get("source", "")
        badge = ""
        if source == "auto_verifier":
            badge = (
                ' <span style="background:#ffd76b;color:#604700;border-radius:8px;'
                'padding:0 0.35rem;font-size:0.7rem;font-weight:600;margin-left:0.25rem;">'
                'auto-verifier</span>'
            )
            summary = e.get("summary", "").strip()
            if summary:
                auto_summaries.append(summary)
        items.append(
            f'<li><time datetime="{added_at}">{added_at}</time>{badge} — {note}</li>'
        )
    items_html = "\n".join(items)
    plural = "s" if len(entries) != 1 else ""

    title_attr = ""
    if auto_summaries:
        tooltip = (
            "The following claims were flagged by an automated verification "
            "protocol: " + "; ".join(auto_summaries)
        )
        title_attr = f' title="{html_module.escape(tooltip, quote=True)}"'

    return (
        f'<aside{title_attr} style="background:#fff3cd;border:1px solid #ffd76b;border-radius:6px;'
        'padding:0.75rem 1rem;margin:0 0 1rem 0;font-family:-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',Roboto,sans-serif;color:#604700;font-size:0.92rem;line-height:1.45">'
        f'<strong>Correction{plural} ({len(entries)})</strong>'
        f'<ul style="margin:0.4rem 0 0 1.1rem;padding:0">{items_html}</ul>'
        '</aside>'
    )


def _inject_correction_banner(html: str, banner: str) -> str:
    """Insert the banner immediately after <body ...> in the briefing HTML.

    Falls back to prepending if no <body> tag is found.
    """
    m = re.search(r"<body[^>]*>", html, flags=re.IGNORECASE)
    if not m:
        return banner + html
    insert_at = m.end()
    return html[:insert_at] + "\n" + banner + "\n" + html[insert_at:]


def publish_to_docs(config: dict, latest_html_path=None) -> bool:
    """Mirror briefings into docs/, rebuild index.html, commit + push.

    Backfills any HTML present in output_dir that isn't yet under docs/briefings/.
    Returns True on success, False if any step failed (publishing is best-effort:
    a failure here should never abort the briefing run).
    """
    repo_root = Path(__file__).parent
    docs_dir = repo_root / "docs"
    docs_briefings = docs_dir / "briefings"
    docs_briefings.mkdir(parents=True, exist_ok=True)

    output_dir = Path(config["output_dir"])
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()

    corrections = load_corrections()

    # Mirror every HTML briefing in output_dir into docs/briefings/.
    # Always rewrite when there are corrections for that file so banner edits
    # in corrections.json propagate even if the source HTML hasn't changed.
    if output_dir.exists():
        for src in output_dir.glob("briefing_*.html"):
            dst = docs_briefings / src.name
            entries = corrections.get(src.name, [])
            needs_update = (
                not dst.exists()
                or src.stat().st_mtime > dst.stat().st_mtime
                or bool(entries)
            )
            if not needs_update:
                continue
            html = src.read_text(encoding="utf-8")
            if entries:
                html = _inject_correction_banner(html, _render_correction_banner(entries))
            dst.write_text(html, encoding="utf-8")

    # Build the archive list newest-first.
    briefings = []
    for f in docs_briefings.glob("briefing_*.html"):
        parsed = _parse_briefing_filename(f.name)
        if parsed is None:
            continue
        dt, label = parsed
        briefings.append({
            "filename": f.name,
            "datetime": dt,
            "label": label,
            "corrections": len(corrections.get(f.name, [])),
        })
    briefings.sort(key=lambda b: b["datetime"], reverse=True)

    index_html = _build_index_html(config.get("site_title", "Iran Peace Talks — Market Briefings"), briefings)
    (docs_dir / "index.html").write_text(index_html, encoding="utf-8")
    # .nojekyll lets GitHub Pages serve files starting with underscores untouched.
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"  ✓ Published {len(briefings)} briefing(s) to docs/")

    # Commit + push. Skip if there's nothing staged (e.g. index unchanged).
    try:
        subprocess.run(["git", "add", "docs"], cwd=repo_root, check=True)
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_root,
        )
        if diff.returncode == 0:
            print("  ─ No docs changes to commit.")
            return True
        msg_label = "briefing"
        if latest_html_path is not None:
            parsed = _parse_briefing_filename(Path(latest_html_path).name)
            if parsed:
                dt, label = parsed
                msg_label = f"{label} {dt.strftime('%Y-%m-%d %H:%M')}"
        commit_msg = f"Publish {msg_label}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_root,
            check=True,
        )
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
        print(f"  ✓ Pushed: {commit_msg}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Publish git step failed: {e}. Briefing files were still written to docs/.")
        return False
    except FileNotFoundError:
        print("  ⚠ `git` not found on PATH — skipping commit/push. Files were written to docs/.")
        return False


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

    # Parse <state_update> and <claims> first so we can strip both blocks before
    # formatting the HTML (they're machine-metadata, not human content).
    state_update = extract_state_update(raw)
    claims = extract_claims(raw)
    ceasefire_expiry = ""
    if state_update and "ceasefire_expiry" in state_update:
        ceasefire_expiry = state_update.get("ceasefire_expiry") or ""
    else:
        ceasefire_expiry = state.get("ceasefire_expiry", "")

    display_text = strip_claims(strip_state_update(raw))
    html = format_html_briefing(
        display_text,
        session_type,
        timestamp,
        state_update,
        ceasefire_expiry,
    )

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

    # Advance persistent state using the state_update we parsed earlier.
    if state_update is None:
        print(f"  ⚠ No valid <state_update> block found — persistent state NOT advanced.")
        print(f"    Next briefing will see the same state as this one did.")
    else:
        new_state = merge_state(state, state_update, str(filepath))
        save_state(new_state)
        print(f"  ✓ State updated: {len(new_state['hypotheses'])} active, "
              f"{len(new_state['retired_hypotheses'])} retired total")
        n_marked = mark_corrections_delivered(filepath.name)
        if n_marked:
            print(f"  ✓ Marked {n_marked} correction(s) as delivered to {filepath.name}.")

    # Second-pass verifier (opt-in, best-effort, never regenerates the briefing).
    # Runs BEFORE email + publish so any auto-filed corrections appear in both.
    if config.get("verify_enabled"):
        if claims is None:
            print("  ⚠ Verifier enabled but no <claims> block was parsed — skipping.")
        else:
            try:
                verdicts = verify_briefing(claims, config, timestamp)
            except Exception as e:
                print(f"  ⚠ Verifier raised unexpected exception: {e}. Briefing still ships.")
                verdicts = None
            if verdicts is not None:
                n_contra = sum(1 for v in verdicts if v.get("status") == "contradicted")
                n_unver = sum(1 for v in verdicts if v.get("status") == "unverified")
                print(
                    f"  ✓ Verifier done: {len(verdicts)} verdict(s) "
                    f"({n_contra} contradicted, {n_unver} unverified)."
                )
                n_filed = file_verifier_corrections(verdicts, claims, filepath.name)
                if n_filed:
                    print(f"  ✓ Auto-filed {n_filed} correction(s) on {filepath.name}.")

    # Email
    subject = f"Iran Briefing: {session_type.replace('-', ' ').title()} — {now.strftime('%b %d')}"
    send_email(config, subject, html)

    # GitHub Pages publish (best-effort — failures don't abort the briefing).
    if config.get("publish_enabled"):
        try:
            publish_to_docs(config, filepath)
        except Exception as e:
            print(f"  ⚠ Publish step raised an unexpected exception: {e}. Briefing itself succeeded.")

    print(f"  ✓ Briefing complete.\n")
    return True


# ─── Scheduler ──────────────────────────────────────────────────────────────

def run_scheduler(config: dict):
    """Simple sleep-based scheduler that runs briefings at configured times."""
    et = ZoneInfo("America/New_York")

    print("\n" + "=" * 60)
    print("  IRAN BRIEFING SCHEDULER")
    print("=" * 60)
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

        midday_time = now.replace(
            hour=config["midday_hour"],
            minute=config["midday_minute"],
            second=0, microsecond=0,
        )

        if now >= midday_time:
            tomorrow_midday = midday_time + timedelta(days=1)
            sleep_secs = (tomorrow_midday - now).total_seconds()
            print(f"  Midday briefing done for today. Next: {tomorrow_midday.strftime('%A %I:%M %p ET')}")
            time.sleep(min(sleep_secs, 3600))
            continue

        session_type, target_time = "midday", midday_time
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
    # Force UTF-8 stdout/stderr so the script's ✓ / — / arrow characters print
    # correctly when launched from a Windows console (Git Bash, cmd, PowerShell)
    # where Python defaults to cp1252 and would crash on those characters.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except ValueError:
                pass

    parser = argparse.ArgumentParser(
        description="Iran Peace Talks Automated Market Briefing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python iran_briefing.py                  Run a single on-demand briefing now
  python iran_briefing.py --premarket      Run a single pre-market briefing now
  python iran_briefing.py --midday         Run a single midday briefing now
  python iran_briefing.py --schedule       Start the automated scheduler
  python iran_briefing.py --test-email     Send a test email to verify SMTP config
  python iran_briefing.py --set-agreement 2026-04-18   Set the agreement date
  python iran_briefing.py --reset-state    Delete state.json and start fresh
        """,
    )
    parser.add_argument("--schedule", action="store_true",
                        help="Run on automated schedule (midday briefing, 12:30 PM ET)")
    parser.add_argument("--midday", action="store_true",
                        help="Label this run as a midday briefing")
    parser.add_argument("--premarket", action="store_true",
                        help="Label this run as a pre-market briefing")
    parser.add_argument("--test-email", action="store_true",
                        help="Send a test email to verify SMTP configuration")
    parser.add_argument("--set-agreement", type=str, metavar="YYYY-MM-DD",
                        help="Record the date a peace agreement was reached")
    parser.add_argument("--reset-state", action="store_true",
                        help="Delete state.json so the next briefing starts from baseline hypotheses")
    parser.add_argument("--publish", action="store_true",
                        help="Re-publish docs/ from local briefings/ and push to GitHub Pages (no new briefing)")
    parser.add_argument("--add-correction", nargs=2, metavar=("BRIEFING", "NOTE"),
                        help="Append a correction note to a published briefing. "
                             "BRIEFING is the .html filename (e.g. briefing_20260415_2342_on_demand.html); "
                             "NOTE is the correction text. Re-run --publish afterward to push.")
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
            with open(config_path, encoding="utf-8") as f:
                file_config = json.load(f)
        file_config["agreement_date"] = args.set_agreement
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(file_config, f, indent=2, ensure_ascii=False)
        print(f"✓ Agreement date set to {args.set_agreement}")
        print(f"  Briefings will auto-stop 7 days after this date.")
        return

    if args.add_correction:
        briefing_name, note = args.add_correction
        if not briefing_name.endswith(".html"):
            briefing_name = briefing_name + ".html"
        repo_root = Path(__file__).parent
        if not (repo_root / "briefings" / briefing_name).exists() and \
           not (repo_root / "docs" / "briefings" / briefing_name).exists():
            print(f"✗ No briefing named {briefing_name} found in briefings/ or docs/briefings/.")
            return
        data = load_corrections()
        added_at = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
        data.setdefault(briefing_name, []).append({"added_at": added_at, "note": note})
        save_corrections(data)
        print(f"✓ Added correction to {briefing_name} ({len(data[briefing_name])} total).")
        print(f"  Run `python iran_briefing.py --publish` to push the banner to GitHub Pages.")
        return

    if args.publish:
        publish_to_docs(config)
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

    if args.midday:
        session_type = "midday"
    elif args.premarket:
        session_type = "pre-market"
    else:
        session_type = "on-demand"
    run_briefing(config, session_type)


if __name__ == "__main__":
    main()
