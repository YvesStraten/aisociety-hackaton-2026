"""Flat Energy Coach - Streamlit entry point.

Run from the repo root:
    uv run streamlit run src/aisociety_hackaton_2026/app.py

Layout:
    data/      load and clean the CSVs, find waste, build the FlatContext for the selected flat
    views/     sidebar.py and one file per tab (my_flat, savings_case, my_usage), plus shared charts
    coach.py   the weekly coach message
"""
from __future__ import annotations

import streamlit as st

from aisociety_hackaton_2026.data import Analysis, Dataset, analyse, build_context, load
from aisociety_hackaton_2026.views import my_flat, my_usage, savings_case, sidebar

st.set_page_config(page_title="Flat Energy Coach", page_icon="⚡", layout="wide")


@st.cache_resource(show_spinner="Cleaning the data and looking for waste...")
def load_data() -> tuple[Dataset, Analysis]:
    """Runs once per server start; every page view reuses the result."""
    ds = load()
    return ds, analyse(ds)


ds, analysis = load_data()
choice = sidebar.render(ds.flats)
ctx = build_context(ds, analysis, choice.flat_id, choice.extra_sek_per_kwh)

tab_flat, tab_case, tab_usage = st.tabs(["🏠 My flat", "📈 Savings case", "📊 My usage"])
with tab_flat:
    my_flat.render(ctx)
with tab_case:
    savings_case.render(ctx)
with tab_usage:
    my_usage.render(ctx)
