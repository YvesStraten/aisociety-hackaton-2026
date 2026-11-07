"""Load, clean and join the hackathon dataset.

Rule we never break: bad or missing data stays missing (NaN). It is never
silently turned into zero, because zero means "the appliance was off".
Every fix is counted in a data-quality log so it can be shown to the judges.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Repo root /datasets by default; set DATASET_DIR to point somewhere else.
DATA_DIR = Path(os.environ.get("DATASET_DIR", Path(__file__).resolve().parents[3] / "datasets"))
TZ = "Europe/Stockholm"
START = pd.Timestamp("2026-10-01", tz="UTC")
END = pd.Timestamp("2026-10-29", tz="UTC")  # exclusive
# A 16 A, 230 V circuit cannot deliver more than about 3.7 kWh in one hour.
MAX_KWH_PER_HOUR = 3.7
TEMP_SENTINEL_BELOW = -50.0  # -99 is used as a "no reading" code


@dataclass
class Dataset:
    flats: pd.DataFrame      # one row per flat
    hourly: pd.DataFrame     # one row per appliance-hour, joined to price and context
    context: pd.DataFrame    # one row per flat-hour
    prices: pd.DataFrame     # one row per hour
    quality: pd.DataFrame    # the cleaning log: check, rows affected, what we did

    @property
    def days(self) -> float:
        return (END - START) / pd.Timedelta(days=1)


def _read(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(data_dir / name, dtype=str, keep_default_na=False)


def _parse_utc(series: pd.Series) -> tuple[pd.Series, int]:
    s = series.str.strip()
    iso = pd.to_datetime(s, format="%Y-%m-%dT%H:%M:%SZ", errors="coerce", utc=True)
    legacy = pd.to_datetime(s, format="%Y/%m/%d %H:%M", errors="coerce", utc=True)
    legacy_used = int((iso.isna() & legacy.notna()).sum())
    return iso.fillna(legacy), legacy_used


def load(data_dir: Path | None = None) -> Dataset:
    """Read the four CSV files from data_dir (default: DATA_DIR), clean them and join them."""
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    log: list[dict] = []

    def note(check: str, rows: int, action: str) -> None:
        log.append({"Check": check, "Rows affected": int(rows), "What we did": action})

    # ---------- flats ----------
    flats = _read(data_dir, "flats.csv")
    flats["flat_id"] = flats.flat_id.str.strip().str.upper()
    flats["residents"] = pd.to_numeric(flats.residents)
    flats["floor_area_m2"] = pd.to_numeric(flats.floor_area_m2)
    known_flats = set(flats.flat_id)

    # ---------- energy readings ----------
    er = _read(data_dir, "energy_readings.csv")
    raw_rows = len(er)

    er["appliance_id_raw"] = er.appliance_id
    er["appliance_id"] = er.appliance_id.str.strip().str.upper()
    note("Appliance IDs with stray spaces or lowercase letters",
         (er.appliance_id != er.appliance_id_raw).sum(),
         "Trimmed and upper-cased, e.g. ' f001-a02 ' became 'F001-A02'.")

    er["flat_reported"] = er.flat_id.str.strip().str.upper()
    er["flat_id"] = er.appliance_id.str[:4]
    note("Readings filed under a different flat than the appliance belongs to",
         (er.flat_reported != er.flat_id).sum(),
         "Trusted the appliance ID: these rows fill exactly the hours missing from that appliance's own series.")

    unknown = ~er.flat_id.isin(known_flats)
    note("Readings from a flat that is not in flats.csv",
         unknown.sum(),
         "Set aside (quarantined). They cannot be joined to residents, area or price area.")
    er = er[~unknown].copy()

    er["ts"], legacy_used = _parse_utc(er.timestamp_utc)
    note("Timestamps in the old 'YYYY/MM/DD HH:MM' format", legacy_used,
         "Parsed as UTC, as the README says.")
    bad_ts = er.ts.isna() | (er.ts < START) | (er.ts >= END)
    note("Timestamps that cannot be read or fall outside 1-28 Oct", bad_ts.sum(), "Dropped.")
    er = er[~bad_ts].copy()

    v = er.energy_value.str.strip()
    is_blank = v.isin(["", "N/A", "NA", "n/a", "null", "None"])
    note("Blank or 'N/A' energy values", is_blank.sum(), "Kept as missing - not zero.")
    has_comma = v.str.contains(",", regex=False)
    note("Values written with a decimal comma (0,033)", has_comma.sum(), "Read as decimal numbers.")
    val = pd.to_numeric(v.str.replace(",", ".", regex=False).mask(is_blank), errors="coerce")

    unit = er.energy_unit.str.strip().str.lower()
    note("Unit labels with stray spaces or the wrong case (' kwh ')",
         (er.energy_unit != unit.map({"kwh": "kWh", "wh": "Wh"}).fillna(er.energy_unit)).sum(),
         "Normalised to kWh / Wh.")
    note("Readings in Wh instead of kWh", (unit == "wh").sum(), "Divided by 1,000.")
    unknown_unit = ~unit.isin(["kwh", "wh"])
    note("Readings with an unknown unit", unknown_unit.sum(), "Kept as missing.")
    kwh = np.where(unit == "wh", val / 1000.0, val)
    kwh = pd.Series(kwh, index=er.index).mask(unknown_unit)

    neg = kwh < 0
    note("Negative readings", neg.sum(),
         "Marked invalid (missing). An appliance cannot use negative energy.")
    spike = kwh > MAX_KWH_PER_HOUR
    note(f"Single-hour spikes above {MAX_KWH_PER_HOUR} kWh (15-45 kWh seen)", spike.sum(),
         "Marked invalid (missing). One household circuit cannot draw that much; "
         "the hours either side are normal, so these are corrupt readings, not faults.")
    er["kwh"] = kwh.mask(neg | spike)

    key = ["appliance_id", "ts"]
    dup_any = er.duplicated(key, keep=False)
    groups = er[dup_any].groupby(key).kwh.nunique(dropna=False)
    conflicting = groups[groups > 1].index
    exact_removed = int(er.duplicated(key + ["kwh"]).sum())
    note("Exact duplicate rows (same appliance, hour and value)", exact_removed, "Kept one copy.")
    note("Same appliance and hour reported twice with different values", len(conflicting),
         "Marked missing - we cannot tell which value is right.")
    er = er.drop_duplicates(key + ["kwh"])
    er = er.set_index(key)
    er.loc[er.index.isin(conflicting), "kwh"] = np.nan
    er = er[~er.index.duplicated()].reset_index()

    # Full grid: every appliance x every hour. Missing hours become explicit NaN.
    hours = pd.date_range(START, END, freq="h", inclusive="left")
    appliances = sorted(er.appliance_id.unique())
    grid = pd.MultiIndex.from_product([appliances, hours], names=key).to_frame(index=False)
    readings = grid.merge(er[key + ["kwh"]], on=key, how="left")
    readings["flat_id"] = readings.appliance_id.str[:4]
    readings["channel"] = readings.appliance_id.str[5:]
    missing_hours = int(len(grid) - len(er))
    note("Appliance-hours with no reading at all (e.g. F006 lost ~7 hours)", missing_hours,
         "Kept as missing. Totals are reported with their coverage.")

    # ---------- context ----------
    ctx = _read(data_dir, "hourly_context.csv")
    ctx["flat_id"] = ctx.flat_id.str.strip().str.upper()
    ctx["ts"], _ = _parse_utc(ctx.timestamp_utc)
    for c in ["outdoor_temp_c", "indoor_temp_c", "occupants_home"]:
        ctx[c] = pd.to_numeric(ctx[c].str.strip().replace({"N/A": ""}), errors="coerce")
    sentinel = ctx.outdoor_temp_c < TEMP_SENTINEL_BELOW
    note("Outdoor temperature of -99 °C (a 'no reading' code)", sentinel.sum(), "Kept as missing.")
    ctx.loc[sentinel, "outdoor_temp_c"] = np.nan
    ctx = ctx.merge(flats[["flat_id", "residents"]], on="flat_id", how="left")
    too_many = ctx.occupants_home > ctx.residents
    note("Occupancy higher than the number of residents (9 people)", too_many.sum(),
         "Kept as missing.")
    ctx.loc[too_many, "occupants_home"] = np.nan
    note("Missing occupancy", int(ctx.occupants_home.isna().sum() - too_many.sum()),
         "Kept as missing. 'Nobody home' savings only count hours where we know the flat was empty.")
    ctx = ctx.drop(columns=["residents"])

    # ---------- prices ----------
    pr = _read(data_dir, "hourly_prices.csv")
    pr["ts"], _ = _parse_utc(pr.timestamp_utc)
    pr["price_area"] = pr.price_area.str.strip().str.upper()
    pr["spot_sek_per_kwh"] = pd.to_numeric(pr.spot_sek_per_kwh, errors="coerce")
    pr["carbon_gco2e_per_kwh"] = pd.to_numeric(pr.carbon_gco2e_per_kwh, errors="coerce")
    pr = pr.sort_values("ts")
    pr["price_imputed"] = pr.spot_sek_per_kwh.isna()
    note("Hours with no spot price", pr.price_imputed.sum(),
         "Filled from the neighbouring hours (linear) for cost estimates only, and flagged.")
    pr["spot_sek_per_kwh"] = pr.set_index("ts").spot_sek_per_kwh.interpolate("time").values
    note("Hours with a negative spot price", (pr.spot_sek_per_kwh < 0).sum(),
         "Kept: negative prices are valid in the Nordic market.")

    # ---------- join (check cardinality) ----------
    area = flats.set_index("flat_id").price_area
    readings["price_area"] = readings.flat_id.map(area)
    hourly = readings.merge(
        pr[["ts", "price_area", "spot_sek_per_kwh", "carbon_gco2e_per_kwh", "price_imputed"]],
        on=["ts", "price_area"], how="left", validate="m:1")
    hourly = hourly.merge(
        ctx[["flat_id", "ts", "outdoor_temp_c", "indoor_temp_c", "occupants_home"]],
        on=["flat_id", "ts"], how="left", validate="m:1")
    assert len(hourly) == len(readings), "join changed the row count"

    local = hourly.ts.dt.tz_convert(TZ)
    hourly["local"] = local
    hourly["hour"] = local.dt.hour
    hourly["date"] = local.dt.date
    hourly["sek"] = hourly.kwh * hourly.spot_sek_per_kwh
    hourly["kg"] = hourly.kwh * hourly.carbon_gco2e_per_kwh / 1000.0

    ctx["local"] = ctx.ts.dt.tz_convert(TZ)
    ctx["hour"] = ctx.local.dt.hour
    pr["local"] = pr.ts.dt.tz_convert(TZ)
    pr["hour"] = pr.local.dt.hour

    quality = pd.DataFrame(log)
    quality = quality[quality["Rows affected"] > 0].reset_index(drop=True)
    quality.attrs["raw_rows"] = raw_rows
    quality.attrs["coverage"] = float(hourly.kwh.notna().mean())

    return Dataset(flats=flats, hourly=hourly, context=ctx, prices=pr, quality=quality)
