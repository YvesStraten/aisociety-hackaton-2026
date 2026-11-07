"""Savings case tab: the numbers for the pitch slide, for all students in all flats.

Blocks, in page order:
    1. Headline     - expected savings per student per year (kWh, SEK, CO2e), central and low case
    2. Baseline     - what the average student uses now
    3. All actions  - every action found, in every flat, with how it was scaled to a year
    4. Assumptions  - data, prices, scaling and caveats, with sources

Data used (FlatContext, see data/context.py):
    ctx.all_findings       every flat's actions, SEK including the extra cost
    ctx.analysis.baseline  4-week totals per flat (kwh, sek, kg, residents)
    ctx.analysis.prices    expensive hours (peak_label)
    ctx.dataset.flats      residents per flat
    ctx.dataset.days       number of days in the data (28)
"""
from __future__ import annotations

import streamlit as st

from aisociety_hackaton_2026.data import savings_case
from aisociety_hackaton_2026.data.context import FlatContext


def render(ctx: FlatContext) -> None:
    _headline(ctx)
    _baseline(ctx)
    _all_actions(ctx)
    _assumptions(ctx)


# ---------------------------------------------------------------------- 1. headline
def _headline(ctx: FlatContext) -> None:
    case = savings_case(ctx.all_findings, ctx.dataset.flats)
    st.header("Expected savings per student per year")
    if "central" not in case:
        st.info("No actions found, so there are no savings to show.")
        return
    central, low = case["central"], case["low"]
    st.caption(f"All {case['students']} students in the {len(ctx.dataset.flats)} flats, including those with nothing "
               f"to fix. {case['students_affected']} of them live in a flat where we found a problem. "
               f"Cost: {ctx.cost_note}.")
    k1, k2, k3 = st.columns(3)
    k1.metric("Energy saved", f"{central['net_kwh']:,.0f} kWh", border=True,
              help="Net energy: excludes the radiator case, where heat moves to district heating.")
    k2.metric("Money saved", f"{central['sek']:,.0f} SEK", border=True,
              help="Includes moving loads to cheaper hours and the radiator case (it comes off the electricity bill).")
    k3.metric("CO2e avoided", f"{central['kg']:,.1f} kg", border=True)
    st.caption(f"Low case: {low['net_kwh']:,.0f} kWh · {low['sek']:,.0f} SEK · {low['kg']:,.1f} kg CO2e "
               "per student per year.")


# ---------------------------------------------------------------------- 2. baseline
def _baseline(ctx: FlatContext) -> None:
    b = ctx.analysis.baseline
    students = b.residents.sum()
    kwh = b.kwh.sum() / students
    st.info(f"Baseline: the average student used {kwh:.0f} kWh in these 4 weeks "
            f"({kwh / ctx.dataset.days:.1f} kWh a day), costing {b.sek.sum() / students:.0f} SEK at spot price "
            f"and {b.kg.sum() / students:.1f} kg CO2e.")


# ---------------------------------------------------------------------- 3. all actions
def _all_actions(ctx: FlatContext) -> None:
    st.subheader("Every action we found")
    f = ctx.all_findings
    if f.empty:
        st.write("No actions found.")
        return
    table = f.assign(
        Flat=f.flat_id,
        Action=f.icon + " " + f.title,
        kWh_year=f.kwh_year.round(0),
        SEK_year=f.sek_year.round(0),
        kg_year=f.kg_year.round(1),
        Net=f.energy_saving,
        Low_case_kWh=f.kwh_year_low.round(0),
        Basis=f.basis,
    )[["Flat", "Action", "kWh_year", "SEK_year", "kg_year", "Net", "Low_case_kWh", "Basis"]]
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "kWh_year": st.column_config.NumberColumn("kWh / year", format="%d"),
        "SEK_year": st.column_config.NumberColumn("SEK / year", format="%d"),
        "kg_year": st.column_config.NumberColumn("kg CO2e / year", format="%.1f"),
        "Net": st.column_config.CheckboxColumn("Net energy?"),
        "Low_case_kWh": st.column_config.NumberColumn("Low case kWh", format="%d"),
        "Basis": st.column_config.TextColumn("How we scaled it", width="large"),
    })


# ---------------------------------------------------------------------- 4. assumptions and sources
def _assumptions(ctx: FlatContext) -> None:
    st.subheader("Assumptions and sources")
    st.markdown(f"""
- **Data:** the organisers' synthetic student-flat dataset: 8 flats, 25 students, hourly readings for 7 circuits per flat, 1-28 October 2026.
- **Prices and carbon:** the dataset's synthetic SE3 hourly spot price and operational carbon factor. A live version would use [elprisetjustnu.se](https://www.elprisetjustnu.se) for spot prices and [Electricity Maps](https://www.electricitymaps.com) for carbon intensity.
- **Money:** spot price only, excluding VAT, unless you add energy tax, grid fee and VAT in the sidebar (sources: Skatteverket for energy tax, your grid operator's tariff). Fixed monthly fees never go down.
- **Expensive hours:** hours whose average price is at least 1.5× the typical hour: {ctx.analysis.prices['peak_label']}.
- **Scaling to a year:** heaters over the heating season only (Oct-Apr, 212 days) at October's rate, which is conservative because winter is colder; always-on waste over 365 days; a fault for 6 months before someone would notice; moved runs over 365 days.
- **Low case:** half the change, or only the hours nobody was home, to allow for partial uptake and people slipping back into old habits.
- **Not counted as energy saved:** the radiator case (the heat comes from district heating instead) and moved runs (same kWh, different hour).
- **Caveat:** four autumn weeks of synthetic data are fine for a demo but are not evidence of real-world savings.
""")
