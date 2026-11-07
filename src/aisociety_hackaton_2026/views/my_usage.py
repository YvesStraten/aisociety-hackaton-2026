"""My usage tab: where the flat's electricity goes.

Blocks, in page order:
    1. By appliance       - kWh per appliance over the 4 weeks
    2. Week by week       - kWh per student per day, this flat vs similar flats
    3. Average day        - average kWh per hour, by appliance, expensive hours shaded
    4. Vs similar flats   - kWh per student per day for every flat

Data used (FlatContext, see data/context.py):
    ctx.usage              kWh per appliance (appliance_id, label, kind, kwh, share)
    ctx.weekly             kWh per student per day per week ("mine" vs "peers")
    ctx.dataset.hourly     cleaned hourly readings (for the average day)
    ctx.analysis.labels    what each appliance is
    ctx.analysis.baseline  per-flat totals (for the comparison)
    ctx.analysis.prices    expensive hours
The chart code lives in views/charts.py.
"""
from __future__ import annotations

import streamlit as st

from aisociety_hackaton_2026.data.context import FlatContext
from aisociety_hackaton_2026.views import charts


def render(ctx: FlatContext) -> None:
    st.header("Where your electricity goes")
    left, right = st.columns(2, gap="large")
    with left:
        _by_appliance(ctx)
    with right:
        _week_by_week(ctx)
    _average_day(ctx)
    _vs_similar_flats(ctx)


# ---------------------------------------------------------------------- 1. by appliance
def _by_appliance(ctx: FlatContext) -> None:
    st.subheader("By appliance")
    st.altair_chart(charts.by_appliance(ctx), width="stretch")
    st.caption("Appliance types are our best guess from usage patterns: the dataset has no appliance list.")


# ---------------------------------------------------------------------- 2. week by week
def _week_by_week(ctx: FlatContext) -> None:
    st.subheader("Week by week")
    st.altair_chart(charts.week_by_week(ctx), width="stretch")
    st.caption("Per student per day, your flat vs the median of the other flats.")


# ---------------------------------------------------------------------- 3. average day
def _average_day(ctx: FlatContext) -> None:
    prices = ctx.analysis.prices
    st.subheader("Your average day")
    st.altair_chart(charts.average_day(ctx), width="stretch")
    st.caption(f"Shaded columns: expensive hours ({prices['peak_label']}), about {prices['peak_price']:.2f} SEK/kWh "
               f"vs {prices['off_price']:.2f} at other times.")


# ---------------------------------------------------------------------- 4. vs similar flats
def _vs_similar_flats(ctx: FlatContext) -> None:
    st.subheader("You vs similar flats")
    st.altair_chart(charts.vs_similar_flats(ctx), width="stretch")
    st.caption("Your flat is the darker bar. Per student, because flats have 2 to 5 residents.")
