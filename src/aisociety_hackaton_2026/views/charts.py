"""Charts shared by the tabs (Altair, which comes with Streamlit).

Each function takes the FlatContext (or one action) and returns a chart, or draws
it directly for the evidence charts. Colours are fixed per appliance type, so an
appliance keeps its colour on every chart.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from aisociety_hackaton_2026.data import LABELS
from aisociety_hackaton_2026.data.context import FlatContext

# ------------------------------------------------------------------ colours
KIND_COLORS = {
    "fridge": "#2a78d6",       # blue
    "heater": "#eb6834",       # orange
    "night": "#1baf7a",        # aqua
    "cooking": "#eda100",      # yellow
    "timed": "#e87ba4",        # magenta
    "laundry": "#008300",      # green
    "electronics": "#6250d6",  # violet
}
BLUE = "#2a78d6"
LIGHT_BLUE = "#9ec5f4"
ORANGE = "#eb6834"
MUTED = "#898781"


# ------------------------------------------------------------------ building blocks
def peak_band(ctx: FlatContext) -> alt.Chart:
    """Shaded columns behind the expensive hours (layer it under an hour-of-day chart)."""
    band = pd.DataFrame({"hour": ctx.analysis.prices["peak_hours"]})
    return alt.Chart(band).mark_bar(color=ORANGE, opacity=0.10, width={"band": 1}).encode(
        x=alt.X("hour:O"), tooltip=alt.value("Expensive hour"))


# ------------------------------------------------------------------ usage charts
def by_appliance(ctx: FlatContext) -> alt.Chart:
    """Horizontal bars: kWh per appliance over the 4 weeks, biggest first."""
    use = ctx.usage
    order = use.sort_values("kwh", ascending=False).label.tolist()
    bars = alt.Chart(use).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height={"band": 0.7}).encode(
        y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=220)),
        x=alt.X("kwh:Q", title="kWh in 4 weeks"),
        color=alt.Color("kind:N", scale=alt.Scale(domain=list(KIND_COLORS), range=list(KIND_COLORS.values())),
                        legend=None),
        tooltip=["label", "appliance_id", alt.Tooltip("kwh:Q", format=".1f", title="kWh"),
                 alt.Tooltip("share:Q", format=".0%", title="Share")])
    shares = bars.mark_text(align="left", dx=4, color=MUTED).encode(text=alt.Text("share:Q", format=".0%"))
    return (bars + shares).properties(height=240)


def week_by_week(ctx: FlatContext) -> alt.Chart:
    """Lines: kWh per student per day for each week, this flat vs similar flats."""
    mine, peers = f"Flat {ctx.flat_id}", "Similar flats"
    w = ctx.weekly.melt(id_vars=["week", "label"], value_vars=["mine", "peers"], var_name="who", value_name="kwh")
    w["who"] = w.who.map({"mine": mine, "peers": peers})
    return alt.Chart(w).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=60)).encode(
        x=alt.X("label:N", sort=None, title=None),
        y=alt.Y("kwh:Q", title="kWh per student per day", scale=alt.Scale(zero=True)),
        color=alt.Color("who:N", title=None, scale=alt.Scale(domain=[mine, peers], range=[BLUE, MUTED]),
                        legend=alt.Legend(orient="top")),
        tooltip=["who", "label", alt.Tooltip("kwh:Q", format=".2f", title="kWh/student/day")],
    ).properties(height=240)


def average_day(ctx: FlatContext) -> alt.Chart:
    """Stacked bars: average kWh per hour of the day, split by appliance, expensive hours shaded."""
    h = ctx.dataset.hourly
    h = h[h.flat_id == ctx.flat_id].merge(ctx.analysis.labels[["kind", "label"]],
                                          left_on="appliance_id", right_index=True)
    day = (h.groupby(["hour", "kind", "label"]).kwh.sum() / ctx.dataset.days).reset_index()
    day = day[day.kind != "unused"]
    stack = alt.Chart(day).mark_bar().encode(
        x=alt.X("hour:O", title="Hour of day"),
        y=alt.Y("kwh:Q", title="kWh per day", stack="zero"),
        color=alt.Color("label:N", title=None, scale=alt.Scale(
            domain=[LABELS[k] for k in KIND_COLORS], range=list(KIND_COLORS.values())),
            legend=alt.Legend(orient="right", labelLimit=260)),
        order=alt.Order("kind:N"),
        tooltip=["hour", "label", alt.Tooltip("kwh:Q", format=".2f", title="kWh")])
    return (peak_band(ctx) + stack).properties(height=280)


def vs_similar_flats(ctx: FlatContext) -> alt.Chart:
    """Bars: kWh per student per day for every flat, the selected flat highlighted."""
    bf = ctx.analysis.baseline.reset_index()[["flat_id", "kwh_student_day", "residents"]]
    bf["selected"] = bf.flat_id == ctx.flat_id
    return alt.Chart(bf).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("flat_id:N", sort="-y", title=None),
        y=alt.Y("kwh_student_day:Q", title="kWh per student per day"),
        color=alt.condition("datum.selected", alt.value(BLUE), alt.value(LIGHT_BLUE)),
        tooltip=[alt.Tooltip("flat_id", title="Flat"), alt.Tooltip("residents", title="Students"),
                 alt.Tooltip("kwh_student_day:Q", format=".2f", title="kWh/student/day")],
    ).properties(height=260)


# ------------------------------------------------------------------ evidence for one action
def show_evidence(ctx: FlatContext, action) -> None:
    """Draw the chart that backs up one action (the 'Show me the evidence' expander)."""
    kind = action.evidence["type"]
    if kind == "daily":
        _evidence_daily(ctx, action)
    elif kind == "profile":
        _evidence_profile(ctx, action)
    elif kind == "heater":
        _evidence_heater(ctx, action)
    elif kind == "timing":
        _evidence_timing(ctx, action)


def _evidence_daily(ctx: FlatContext, action) -> None:
    ev, h = action.evidence, ctx.dataset.hourly
    daily = (h[h.appliance_id == ev["appliance_id"]].groupby("date").kwh.mean() * 24).reset_index()
    daily["date"] = pd.to_datetime(daily.date)
    line = alt.Chart(daily).mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2, color=BLUE).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("kwh:Q", title="kWh per day", scale=alt.Scale(zero=True)),
        tooltip=[alt.Tooltip("date:T", format="%a %d %b"), alt.Tooltip("kwh:Q", format=".2f", title="kWh")])
    levels = pd.DataFrame({"y": [ev["before"], ev["after"]], "what": ["Before", "After"]})
    rules = alt.Chart(levels).mark_rule(strokeDash=[4, 4], color=MUTED).encode(
        y="y:Q", tooltip=["what", alt.Tooltip("y:Q", format=".2f")])
    st.altair_chart((rules + line).properties(height=220), width="stretch")
    st.caption("Each dot is one day. The dashed lines are the average before and after the jump.")


def _evidence_profile(ctx: FlatContext, action) -> None:
    ev = action.evidence
    valid = ctx.dataset.hourly[ctx.dataset.hourly.kwh.notna()]
    mine_w = valid[valid.appliance_id == ev["appliance_id"]].groupby("hour").kwh.mean() * 1000
    peer_w = (valid[valid.appliance_id.isin(ev["peers"])]
              .groupby(["appliance_id", "hour"]).kwh.mean().unstack().median() * 1000)
    mine, peers = f"Flat {ctx.flat_id}", "Similar flats"
    prof = pd.concat([pd.DataFrame({"hour": mine_w.index, "W": mine_w.values, "who": mine}),
                      pd.DataFrame({"hour": peer_w.index, "W": peer_w.values, "who": peers})])
    lines = alt.Chart(prof).mark_line(strokeWidth=2, point=True).encode(
        x=alt.X("hour:O", title="Hour of day"),
        y=alt.Y("W:Q", title="Average watts"),
        color=alt.Color("who:N", title=None, scale=alt.Scale(domain=[mine, peers], range=[BLUE, ORANGE]),
                        legend=alt.Legend(orient="top")),
        tooltip=["who", "hour", alt.Tooltip("W:Q", format=".0f")])
    st.altair_chart(lines.properties(height=240), width="stretch")
    st.caption(f"{action.label}: average power by hour, your flat vs the median of similar flats.")


def _evidence_heater(ctx: FlatContext, action) -> None:
    ev, h, labels = action.evidence, ctx.dataset.hourly, ctx.analysis.labels
    daily = h[h.appliance_id == ev["appliance_id"]].groupby("date").kwh.sum().reset_index()
    daily["date"] = pd.to_datetime(daily.date)
    bars = alt.Chart(daily).mark_bar(color=ORANGE, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("kwh:Q", title="Heater kWh per day"),
        tooltip=[alt.Tooltip("date:T", format="%a %d %b"), alt.Tooltip("kwh:Q", format=".1f")])

    mine, others = f"Flat {ctx.flat_id}", "Flats with no heater"
    heater_flats = set(labels[(labels.kind == "heater") & (labels.kwh_day > 0.01)].flat_id)
    temp = ctx.dataset.context.copy()
    temp["date"] = pd.to_datetime(temp.local.dt.date)
    temp["who"] = None
    temp.loc[temp.flat_id == ctx.flat_id, "who"] = mine
    temp.loc[~temp.flat_id.isin(heater_flats), "who"] = others
    temp = temp.dropna(subset=["who"]).groupby(["date", "who"]).indoor_temp_c.mean().reset_index()
    temps = alt.Chart(temp).mark_line(strokeWidth=2).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("indoor_temp_c:Q", title="Indoor °C", scale=alt.Scale(domain=[18, 24])),
        color=alt.Color("who:N", title=None, scale=alt.Scale(domain=[mine, others], range=[BLUE, MUTED]),
                        legend=alt.Legend(orient="top")),
        tooltip=["who", alt.Tooltip("date:T", format="%a %d %b"),
                 alt.Tooltip("indoor_temp_c:Q", format=".1f", title="°C")])

    left, right = st.columns(2)
    left.altair_chart(bars.properties(height=220, title="Heater use"), width="stretch")
    right.altair_chart(temps.properties(height=220, title="Indoor temperature"), width="stretch")


def _evidence_timing(ctx: FlatContext, action) -> None:
    h = ctx.dataset.hourly
    runs = h[h.appliance_id.isin(action.evidence["appliance_ids"]) & (h.kwh > 0)]
    per_hour = runs.groupby("hour").size().reindex(range(24), fill_value=0).reset_index(name="runs")
    bars = alt.Chart(per_hour).mark_bar(color=BLUE, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("hour:O", title="Hour of day"),
        y=alt.Y("runs:Q", title="Hours running"),
        tooltip=["hour", "runs"])
    st.altair_chart((peak_band(ctx) + bars).properties(height=220), width="stretch")
    st.caption("Shaded columns are the expensive, high-carbon hours.")
