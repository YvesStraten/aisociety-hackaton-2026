"""Sidebar: pick a flat and (optionally) the extra cost per kWh on top of the spot price."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class SidebarChoice:
    flat_id: str
    extra_sek_per_kwh: float


def render(flats: pd.DataFrame) -> SidebarChoice:
    with st.sidebar:
        # ---------------------------------------------------------- 1. title
        st.title("Energy, here's the thing...")
        st.caption("Finds the energy waste in your flat and tells you what to do about it.")

        # ---------------------------------------------------------- 2. flat picker
        info = flats.set_index("flat_id")
        flat_id = st.selectbox(
            "Your flat",
            info.index.tolist(),
            format_func=lambda f: f"{f} · {info.loc[f, 'residents']} students · {info.loc[f, 'floor_area_m2']} m²",
        )

        # ---------------------------------------------------------- 3. extra cost per kWh
        extra = st.number_input(
            "Extra cost per kWh on top of the spot price (SEK)",
            min_value=0.0, max_value=5.0, value=0.0, step=0.05,
            help=("The dataset only has the spot price. Energy tax, the grid fee per kWh and VAT come on top. "
                  "Look up today's values (Skatteverket for energy tax, your grid operator for the fee) and enter "
                  "the total here to see full-bill savings. Fixed monthly fees never go down."),
        )

    return SidebarChoice(flat_id=flat_id, extra_sek_per_kwh=float(extra))
