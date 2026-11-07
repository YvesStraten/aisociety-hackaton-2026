"""The weekly coach message for a flat.

template_message() always works (no internet, no key).
ai_message() asks Claude to write it from the flat's numbers. It needs the
`anthropic` package and an API key in the ANTHROPIC_API_KEY environment variable.
"""
from __future__ import annotations

import importlib.util
import json

from aisociety_hackaton_2026.data.context import FlatContext

MODEL = "claude-opus-5-5"

SYSTEM = """You are a friendly energy coach for students who share a flat in Sweden.
Write this week's message to the flatmates.

Rules:
- Use only the facts and numbers you are given. Never invent numbers, devices or reasons.
- Plain, warm English a first-year student understands. No jargon, no blame.
- Start with one short line on how the flat is doing compared with similar flats.
- Then up to three actions, most valuable first, each one or two sentences with its yearly saving.
- Say clearly when an action saves money and CO2e but not kWh (moving a load to cheaper hours).
- Under 130 words. No headings. Use a numbered list for the actions."""


class CoachUnavailable(Exception):
    """Raised when Claude cannot be reached; the app keeps the built-in message."""


def template_message(ctx: FlatContext) -> str:
    """A built-in message from the top 3 actions."""
    peer = ctx.peer_kwh_student_day
    ratio = ctx.baseline.kwh_student_day / peer if peer else 1.0
    if ratio > 1.25:
        opener = f"Hi {ctx.flat_id}! You use {ratio:.1f}× the electricity per person of similar flats, so there's money to save."
    elif ratio < 0.8:
        opener = f"Hi {ctx.flat_id}! You already use less electricity per person than similar flats. Nice work."
    else:
        opener = f"Hi {ctx.flat_id}! You're about level with similar flats."
    if ctx.findings.empty:
        return opener + " Nothing stands out this week. Keep it up!"

    lines = [opener, "", "This week's best moves:"]
    for i, a in enumerate(ctx.findings.head(3).itertuples(), start=1):
        if a.kwh_year > 0:
            worth = f"about {a.kwh_year:,.0f} kWh and {a.sek_year:,.0f} SEK a year"
        else:
            worth = f"about {a.sek_year:,.0f} SEK and {a.kg_year:.1f} kg CO2e a year (same kWh, cheaper hours)"
        lines.append(f"{i}. **{a.title}.** {a.todo} Worth {worth}.")
    return "\n".join(lines)


def ai_available() -> bool:
    return importlib.util.find_spec("anthropic") is not None


def flat_facts(ctx: FlatContext) -> dict:
    """The numbers Claude is allowed to use."""
    return {
        "flat": ctx.flat_id,
        "students": ctx.residents,
        "kwh_per_student_per_day": round(float(ctx.baseline.kwh_student_day), 2),
        "similar_flats_kwh_per_student_per_day": round(ctx.peer_kwh_student_day, 2),
        "actions": [
            {
                "title": a.title,
                "what_we_saw": a.saw,
                "what_to_do": a.todo,
                "kwh_saved_per_year": round(float(a.kwh_year)),
                "sek_saved_per_year_spot_price": round(float(a.sek_year)),
                "kg_co2e_saved_per_year": round(float(a.kg_year), 1),
                "saves_kwh": bool(a.kwh_year > 0),
                "confidence": a.confidence,
            }
            for a in ctx.findings_spot.head(3).itertuples()
        ],
    }


def ai_message(ctx: FlatContext) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise CoachUnavailable("The anthropic package is not installed (uv add anthropic).") from e
    try:  # use the operating system's certificate store (works behind corporate proxies)
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

    facts = json.dumps(flat_facts(ctx), indent=2, ensure_ascii=False)
    try:
        response = anthropic.Anthropic().beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Facts for this week:\n{facts}"}],
        )
    except anthropic.AuthenticationError as e:
        raise CoachUnavailable("No valid Anthropic API key. Set ANTHROPIC_API_KEY and restart the app.") from e
    except anthropic.RateLimitError as e:
        raise CoachUnavailable("The AI coach is busy (rate limit). Try again in a minute.") from e
    except anthropic.APIConnectionError as e:
        raise CoachUnavailable("Could not reach the Anthropic API. Check the internet connection.") from e
    except anthropic.APIStatusError as e:
        raise CoachUnavailable(f"The Anthropic API returned an error ({e.status_code}).") from e
    except anthropic.AnthropicError as e:
        raise CoachUnavailable(f"The AI coach is not set up: {e}") from e

    if response.stop_reason == "refusal":
        raise CoachUnavailable("The AI coach declined this request.")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise CoachUnavailable("The AI coach returned an empty message.")
    return text
