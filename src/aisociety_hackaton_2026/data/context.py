"""Everything the tabs need about the selected flat, in one object.

This is the hand-off point between the data and the views:

    1. add a field to FlatContext (with a comment saying what it holds)
    2. fill it in build_context()
    3. read it in the view as ctx.<field>

The views never read the CSV files themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .analysis import Analysis
from .cleaning import START, Dataset

WEEK_LABELS = list(map(lambda num: f"{num} Week", range(1, 5)))


@dataclass(frozen=True)
class FlatContext:
    # ---- the selected flat ----------------------------------------------------
    flat_id: str
    residents: int
    floor_area_m2: float
    price_area: str

    # ---- settings from the sidebar --------------------------------------------
    extra_sek_per_kwh: float     # energy tax + grid fee + VAT on top of spot; 0 = spot only

    # ---- this flat -------------------------------------------------------------
    baseline: pd.Series          # 4-week totals: kwh, sek, kg, coverage, kwh_student_day, ...
    peer_kwh_student_day: float  # median of the other flats, kWh per student per day (4 weeks)
    weekly: pd.DataFrame         # week, label, mine, peers: kWh per student per day per week
    this_week: pd.DataFrame      # this flat's hourly rows for the last 7 days (kwh, sek, kg, ...)
    usage: pd.DataFrame          # appliance_id, label, kind, kwh, share: use per appliance (4 weeks)
    findings: pd.DataFrame       # this flat's actions, best first, SEK including the extra cost
    findings_spot: pd.DataFrame  # the same actions with SEK at spot price only (for the coach)

    # ---- all flats (comparisons and the savings case) --------------------------
    all_findings: pd.DataFrame   # every flat's actions, SEK including the extra cost
    dataset: Dataset             # cleaned data: hourly, context, prices, flats, quality
    analysis: Analysis           # labels, findings, baseline, prices

    @property
    def cost_note(self) -> str:
        """Short text saying which price the SEK figures use."""
        if self.extra_sek_per_kwh == 0:
            return "spot price only"
        return f"spot + {self.extra_sek_per_kwh:.2f} SEK/kWh"


def build_context(ds: Dataset, an: Analysis, flat_id: str, extra_sek_per_kwh: float = 0.0) -> FlatContext:
    flat = ds.flats.set_index("flat_id").loc[flat_id]
    all_findings = add_extra_cost(an.findings, extra_sek_per_kwh)
    return FlatContext(
        flat_id=flat_id,
        residents=int(flat.residents),
        floor_area_m2=float(flat.floor_area_m2),
        price_area=str(flat.price_area),
        extra_sek_per_kwh=extra_sek_per_kwh,
        baseline=an.baseline.loc[flat_id],
        peer_kwh_student_day=float(an.baseline.drop(index=flat_id).kwh_student_day.median()),
        weekly=weekly_per_student(ds, flat_id),
        this_week=last_week_rows(ds, flat_id),
        usage=usage_by_appliance(ds, an, flat_id),
        findings=_for_flat(all_findings, flat_id),
        findings_spot=_for_flat(an.findings, flat_id),
        all_findings=all_findings,
        dataset=ds,
        analysis=an,
    )


# ---------------------------------------------------------------------- helpers
def add_extra_cost(findings: pd.DataFrame, extra_sek_per_kwh: float) -> pd.DataFrame:
    """Add energy tax, grid fee and VAT (SEK per kWh saved) to the SEK figures."""
    if findings.empty or extra_sek_per_kwh == 0:
        return findings
    out = findings.copy()
    out["sek_year"] = out.sek_year + out.kwh_year * extra_sek_per_kwh
    out["sek_year_low"] = out.sek_year_low + out.kwh_year_low * extra_sek_per_kwh
    return out


def weekly_per_student(ds: Dataset, flat_id: str) -> pd.DataFrame:
    """kWh per student per day for each week: this flat and the median of the other flats."""
    week = _week_index(ds.hourly.ts)
    residents = ds.flats.set_index("flat_id").residents
    per = ds.hourly.assign(week=week).groupby(["flat_id", "week"]).kwh.sum().unstack()
    per = per.div(residents, axis=0) / 7
    return pd.DataFrame({
        "week": per.columns,
        "label": WEEK_LABELS[: len(per.columns)],
        "mine": per.loc[flat_id].values,
        "peers": per.drop(index=flat_id).median().values,
    })


def last_week_rows(ds: Dataset, flat_id: str) -> pd.DataFrame:
    """This flat's hourly rows for the last 7 days of data (22-28 Oct)."""
    week = _week_index(ds.hourly.ts)
    return ds.hourly[(ds.hourly.flat_id == flat_id) & (week == week.max())]


def usage_by_appliance(ds: Dataset, an: Analysis, flat_id: str) -> pd.DataFrame:
    """kWh per appliance over the 4 weeks, with our guess of what each appliance is."""
    labels = an.labels[(an.labels.flat_id == flat_id) & (an.labels.kind != "unused")]
    use = (ds.hourly[ds.hourly.flat_id == flat_id].groupby("appliance_id").kwh.sum()
           .rename("kwh").to_frame().join(labels[["label", "kind"]], how="inner").reset_index())
    use["share"] = use.kwh / use.kwh.sum()
    return use


def _week_index(ts: pd.Series) -> pd.Series:
    return (ts - START).dt.days // 7


def _for_flat(findings: pd.DataFrame, flat_id: str) -> pd.DataFrame:
    if findings.empty:
        return findings
    return findings[findings.flat_id == flat_id].reset_index(drop=True)
