"""My flat tab: how the flat is doing this week and what to do about it.

Blocks, in page order:
    1. Header        - which flat, how big, which week
    2. Key numbers   - use per student this week, similar flats, cost this week, possible yearly saving
    3. Top actions   - the most valuable actions, each with a "Show me the evidence" chart
    4. Coach message - a short weekly message built from the actions (Claude can rewrite it)

Data used (FlatContext, see data/context.py):
    ctx.flat_id, ctx.residents, ctx.floor_area_m2, ctx.price_area
    ctx.weekly             kWh per student per day per week: this flat ("mine") and similar flats ("peers")
    ctx.this_week          this flat's hourly rows for the last 7 days (kwh, sek, kg)
    ctx.findings           this flat's actions, best first (title, saw, todo, kwh_year, sek_year, ...)
    ctx.extra_sek_per_kwh  extra cost per kWh from the sidebar
"""
from __future__ import annotations

import streamlit as st

from aisociety_hackaton_2026 import coach
from aisociety_hackaton_2026.data.context import FlatContext
from aisociety_hackaton_2026.views import charts

MAX_ACTIONS = 3  # how many action cards to show before "more ideas"


def render(ctx: FlatContext) -> None:
    _header(ctx)
    _key_numbers(ctx)
    left, right = st.columns([3, 2], gap="large")
    with left:
        _top_actions(ctx)
    with right:
        _coach_message(ctx)


# ---------------------------------------------------------------------- 1. header
def _header(ctx: FlatContext) -> None:
    st.header(f"Flat {ctx.flat_id}")
    st.caption(f"{ctx.residents} students · {ctx.floor_area_m2:.0f} m² · price area {ctx.price_area} · "
               "this week = 22-28 Oct 2026")


# ---------------------------------------------------------------------- 2. key numbers
def _key_numbers(ctx: FlatContext) -> None:
    this_week, week_before = ctx.weekly.iloc[-1], ctx.weekly.iloc[-2]
    week_kwh = ctx.this_week.kwh.sum()
    week_sek = ctx.this_week.sek.sum() + week_kwh * ctx.extra_sek_per_kwh
    week_kg = ctx.this_week.kg.sum()
    save_sek = ctx.findings.sek_year.sum() if not ctx.findings.empty else 0.0
    save_kwh = ctx.findings.kwh_year.sum() if not ctx.findings.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Electricity per student", f"{this_week.mine:.1f} kWh/day", border=True,
              delta=f"{this_week.mine - week_before.mine:+.1f} vs the week before", delta_color="inverse",
              help="Average per student per day over the last 7 days.")
    c2.metric("Similar flats", f"{this_week.peers:.1f} kWh/day", border=True,
              delta=f"you use {this_week.mine / this_week.peers:.1f}×", delta_color="off", delta_arrow="off",
              help="Median of the other flats, per student per day, same week.")
    c3.metric("Cost this week", f"{week_sek:,.0f} SEK", border=True,
              delta=f"{week_kg:.1f} kg CO2e", delta_color="off", delta_arrow="off",
              help=f"Whole flat, {ctx.cost_note}, excluding VAT.")
    c4.metric("You could save a year", f"{save_sek:,.0f} SEK", border=True,
              delta=f"{save_kwh:,.0f} kWh off the bill" if save_kwh else "same kWh, cheaper hours",
              delta_color="off", delta_arrow="off",
              help=f"Central estimate for the whole flat, {ctx.cost_note}. Each action shows its basis and low case.")


# ---------------------------------------------------------------------- 3. top actions
def _top_actions(ctx: FlatContext) -> None:
    st.subheader("Your top actions")
    if ctx.findings.empty:
        st.success("Nothing stands out for your flat. Keep doing what you're doing!")
        return

    for action in ctx.findings.head(MAX_ACTIONS).itertuples():
        _action_card(ctx, action)

    more = ctx.findings.iloc[MAX_ACTIONS:]
    if len(more):
        with st.expander(f"{len(more)} more idea(s)"):
            for action in more.itertuples():
                st.markdown(f"**{action.icon} {action.title}**: {action.todo} "
                            f"*(about {action.sek_year:,.0f} SEK a year)*")


def _action_card(ctx: FlatContext, action) -> None:
    """One action: what we saw, what to do, what it saves, and the evidence."""
    kwh_text = f"{action.kwh_year:,.0f} kWh" if action.kwh_year else "same kWh, cheaper hours"
    counts_co2 = action.energy_saving or action.kind == "shift"
    kg_text = f"{action.kg_year:,.1f} kg CO2e" if counts_co2 else "CO2e not counted"

    with st.container(border=True):
        st.markdown(f"#### {action.icon} {action.title}")
        st.write(action.saw)
        st.markdown(f"**What to do:** {action.todo}")
        st.markdown(f"**Saves a year:** :blue-badge[{kwh_text}] :orange-badge[{action.sek_year:,.0f} SEK] "
                    f":green-badge[{kg_text}] :gray-badge[Confidence: {action.confidence}]")
        st.caption(f"{action.why_confident} {action.basis} "
                   f"Low case: {action.kwh_year_low:,.0f} kWh, {action.sek_year_low:,.0f} SEK.")
        with st.expander("Show me the evidence"):
            charts.show_evidence(ctx, action)


# ---------------------------------------------------------------------- 4. coach message
def _coach_message(ctx: FlatContext) -> None:
    st.subheader("💬 This week's message")
    key = f"coach_message_{ctx.flat_id}"
    message = st.session_state.get(key) or coach.template_message(ctx)
    with st.container(border=True):
        st.markdown(message)

    if not coach.ai_available():
        st.caption("Add the `anthropic` package and an API key to let Claude write this message.")
        return
    if st.button("✨ Write it with the AI coach", help="Asks Claude to write this week's message from your numbers."):
        with st.spinner("Writing your message..."):
            try:
                st.session_state[key] = coach.ai_message(ctx)
                st.rerun()
            except coach.CoachUnavailable as e:
                st.warning(f"{e} Showing the built-in message instead.")
    if key in st.session_state:
        st.caption("Written by Claude from the numbers on this page.")
