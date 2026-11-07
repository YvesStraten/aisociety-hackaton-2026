"""Find energy waste in the cleaned data and put numbers on it.

Four detectors, each written so it works on any flat, not just this dataset:
  1. step_changes  - an always-on appliance suddenly uses much more and stays there (a fault)
  2. peer_excess   - an appliance uses power at hours when the same appliance in similar flats doesn't
  3. heaters       - a portable heater runs in a flat that is already warm, or compensates for a radiator
  4. peak_runs     - a dishwasher or washing machine runs in the expensive, high-carbon hours

Every finding carries kWh, SEK (spot price only) and kg CO2e, observed over the
4 weeks and scaled to a year with a stated basis and a low case.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .cleaning import Dataset

HEATING_SEASON_DAYS = 212  # 1 October - 30 April
YEAR_DAYS = 365
WATCH_W = 30               # ignore differences smaller than 30 W
MEAL_HOURS = {6, 7, 8, 11, 12, 13, 17, 18, 19}

LABELS = {
    "fridge": "Fridge / freezer",
    "cooking": "Cooking (stove, oven, kettle)",
    "laundry": "Washing machine",
    "timed": "Dishwasher or washing machine",
    "night": "Night circuit (chargers, bedroom)",
    "electronics": "Electronics & lighting",
    "heater": "Portable heater",
    "unused": "Not in use",
}
HOW_WE_GUESSED = {
    "fridge": "Uses power every hour of the day at a steady level.",
    "cooking": "Off most of the time; runs at breakfast, lunch and dinner.",
    "laundry": "Off most of the time; runs a few times a week at varied hours.",
    "timed": ("Off most of the time; runs every day or two at a regular hour (a timer or habit). "
              "Hourly data cannot tell a dishwasher from a washing machine."),
    "night": "Uses much more at night than during the day.",
    "electronics": "Always some standby use, rising in the evening.",
    "heater": "Uses more when it is colder outside (strong negative correlation with outdoor temperature).",
    "unused": "No consumption in the 4 weeks.",
}
ALWAYS_ON = {"fridge", "electronics", "night"}
SHIFTABLE = {"timed", "laundry"}


# ---------------------------------------------------------------- helpers
def _date(d) -> str:
    return f"{d.day} {d:%b}"


def hour_ranges(hours) -> str:
    """[7, 8, 9, 17, 18] -> '07-10 and 17-19'."""
    hours = sorted(int(h) for h in hours)
    if len(hours) == 24:
        return "around the clock"
    runs, start, prev = [], hours[0], hours[0]
    for h in hours[1:]:
        if h != prev + 1:
            runs.append((start, prev))
            start = h
        prev = h
    runs.append((start, prev))
    parts = [f"{a:02d}:00-{(b + 1) % 24:02d}:00" for a, b in runs]
    return " and ".join(parts)


def peak_hours(d: Dataset) -> list[int]:
    """Local hours whose average spot price is at least 1.5x the typical hour."""
    by_hour = d.prices.groupby("hour").spot_sek_per_kwh.mean()
    return sorted(by_hour[by_hour >= 1.5 * by_hour.median()].index.tolist())


def price_context(d: Dataset) -> dict:
    peak = peak_hours(d)
    p = d.prices
    is_peak = p.hour.isin(peak)
    return {
        "peak_hours": peak,
        "peak_label": hour_ranges(peak),
        "peak_price": p[is_peak].spot_sek_per_kwh.mean(),
        "off_price": p[~is_peak].spot_sek_per_kwh.mean(),
        "peak_carbon": p[is_peak].carbon_gco2e_per_kwh.mean(),
        "off_carbon": p[~is_peak].carbon_gco2e_per_kwh.mean(),
        "avg_price": p.spot_sek_per_kwh.mean(),
        "avg_carbon": p.carbon_gco2e_per_kwh.mean(),
    }


# ---------------------------------------------------------------- appliance labels
def label_appliances(d: Dataset) -> pd.DataFrame:
    """Guess what each appliance is from its load signature.

    Each appliance gets a guess from simple signature rules; then every channel
    position (A01..A07) takes the majority vote across the 8 flats, because the
    same position holds the same kind of appliance in every flat. The vote stops
    one odd flat (e.g. a faulty or left-on device) from being mislabelled.
    """
    h = d.hourly[d.hourly.kwh.notna()]
    rows = []
    for aid, x in h.groupby("appliance_id"):
        prof = x.groupby("hour").kwh.mean() * 1000  # watts by local hour
        on = x[x.kwh > 0]
        top = on.hour.value_counts(normalize=True)
        rows.append({
            "appliance_id": aid,
            "flat_id": aid[:4],
            "channel": aid[5:],
            "kwh_day": x.kwh.mean() * 24,
            "share_zero": (x.kwh == 0).mean(),
            "night_w": prof.loc[0:5].mean(),
            "day_w": prof.loc[9:16].mean(),
            "profile_cv": prof.std() / prof.mean() if prof.mean() > 0 else np.nan,
            "top_hour_share": top.iloc[0] if len(top) else np.nan,
            "meal_share": on.hour.isin(MEAL_HOURS).mean() if len(on) else np.nan,
            "temp_corr": x.kwh.corr(x.outdoor_temp_c) if x.kwh.std() > 0 else np.nan,
        })
    f = pd.DataFrame(rows)

    def guess(r) -> str:
        if r.kwh_day < 0.01:
            return "unused"
        if r.temp_corr <= -0.6 and r.kwh_day > 3:
            return "heater"
        if r.share_zero < 0.05 and r.profile_cv < 0.2:
            return "fridge"
        if r.share_zero > 0.8:
            if r.top_hour_share >= 0.8:
                return "timed"
            if r.meal_share >= 0.8:
                return "cooking"
            return "laundry"
        if r.night_w > 2 * r.day_w:
            return "night"
        return "electronics"

    f["guess"] = f.apply(guess, axis=1)
    used = f[f.guess != "unused"]
    vote = used.groupby("channel").guess.agg(lambda s: s.value_counts().index[0])
    f["kind"] = np.where(f.guess == "unused", "unused", f.channel.map(vote))
    f["label"] = f.kind.map(LABELS)
    f["how"] = f.kind.map(HOW_WE_GUESSED)
    return f.set_index("appliance_id")


# ---------------------------------------------------------------- findings
def _finding(**kw) -> dict:
    base = dict(kwh_year=0.0, kwh_year_low=0.0, net_kwh_year=0.0, net_kwh_year_low=0.0,
                sek_year=0.0, sek_year_low=0.0, kg_year=0.0, kg_year_low=0.0,
                kwh_28d=0.0, sek_28d=0.0, kg_28d=0.0, energy_saving=True, evidence={})
    base.update(kw)
    return base


def find_step_changes(d: Dataset, labels: pd.DataFrame) -> list[dict]:
    out = []
    h = d.hourly
    for aid, lab in labels[labels.kind.isin(ALWAYS_ON)].iterrows():
        x = h[(h.appliance_id == aid) & h.kwh.notna()]
        daily = x.groupby("date").kwh.mean() * 24
        vals, n = daily.values, len(daily)
        if n < 10:
            continue
        # best single split point (least squared error)
        best_k, best_sse = None, np.inf
        for k in range(4, n - 3):
            a, b = vals[:k], vals[k:]
            sse = ((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum()
            if sse < best_sse:
                best_k, best_sse = k, sse
        before, after = vals[:best_k].mean(), vals[best_k:].mean()
        jump = after - before
        noise = max(vals[:best_k].std(), vals[best_k:].std())
        if not (jump >= 0.3 and after >= 1.3 * before and noise < jump / 4):
            continue
        start = daily.index[best_k]
        days_after = n - best_k
        peers = labels[(labels.kind == lab.kind) & (labels.index != aid)].kwh_day.median()
        after_rows = x[x.date >= start]
        excess_rows = (after_rows.kwh - before / 24).clip(lower=0)
        kwh28 = excess_rows.sum()
        sek28 = (excess_rows * after_rows.spot_sek_per_kwh).sum()
        kg28 = (excess_rows * after_rows.carbon_gco2e_per_kwh).sum() / 1000
        price = sek28 / kwh28
        carbon = kg28 / kwh28
        central, low = jump * 182, jump * 91
        if lab.kind == "fridge":
            title = "Your fridge looks faulty"
            todo = ("Check the door seal (shut the door on a sheet of paper: it should not slide out) "
                    "and defrost the freezer if there is ice. Still high after that? Report it to your "
                    "housing company: a failing fridge wastes energy and can spoil food.")
        else:
            title = f"{lab.label}: use jumped on {_date(start)}"
            todo = f"Something changed on this circuit on {_date(start)}. Check what was plugged in or switched on that day."
        out.append(_finding(
            flat_id=lab.flat_id, appliance_id=aid, label=lab.label, kind="fault", icon="🛠️",
            title=title,
            saw=(f"Since {_date(start)} it uses {after:.2f} kWh a day instead of {before:.2f} "
                 f"(+{jump / before:.0%}), and it has stayed there for {days_after} days. "
                 f"Similar ones use {peers:.2f} kWh a day."),
            todo=todo,
            confidence="High",
            why_confident=("The jump lasted for days at a steady new level. One-hour glitches "
                           "were already removed in cleaning, so this is a real change, not bad data."),
            kwh_28d=kwh28, sek_28d=sek28, kg_28d=kg28,
            kwh_year=central, kwh_year_low=low, net_kwh_year=central, net_kwh_year_low=low,
            sek_year=central * price, sek_year_low=low * price,
            kg_year=central * carbon, kg_year_low=low * carbon,
            basis="A fault like this often goes unnoticed for months. We count 6 months of the extra use (low case: 3 months).",
            evidence={"type": "daily", "appliance_id": aid, "before": before, "after": after,
                      "start": str(start)},
        ))
    return out


def find_peer_excess(d: Dataset, labels: pd.DataFrame, skip: set[str]) -> list[dict]:
    out = []
    h = d.hourly
    valid = h[h.kwh.notna()]
    prof = valid.groupby(["appliance_id", "hour"]).kwh.mean().unstack() * 1000  # W
    for aid, lab in labels[labels.kind.isin(ALWAYS_ON)].iterrows():
        if aid in skip:
            continue
        peers = labels[(labels.kind == lab.kind) & (labels.index != aid) & ~labels.index.isin(skip)].index
        if len(peers) < 3:
            continue
        peer_w = prof.loc[peers].median()
        mine = prof.loc[aid]
        excess = mine - peer_w
        flagged = (excess > WATCH_W) & (mine > 2 * peer_w)
        if not flagged.any():
            continue
        hours = flagged[flagged].index.tolist()
        x = valid[(valid.appliance_id == aid) & valid.hour.isin(hours)]
        # Count only the steady extra load (median over the flagged hours), so a bigger
        # household's normal evening use is not counted as "left on".
        cap_w = excess[hours].median()
        extra = (x.kwh - x.hour.map(peer_w) / 1000).clip(lower=0, upper=cap_w / 1000)
        kwh28 = extra.sum()
        if kwh28 / d.days < 0.2:
            continue
        sek28 = (extra * x.spot_sek_per_kwh).sum()
        kg28 = (extra * x.carbon_gco2e_per_kwh).sum() / 1000
        known = x.occupants_home.notna()
        empty_share = (extra[x.occupants_home == 0].sum() / extra[known].sum()) if extra[known].sum() > 0 else np.nan
        per_day = kwh28 / d.days
        central, low = per_day * YEAR_DAYS, per_day * YEAR_DAYS * 0.5
        when = hour_ranges(hours)
        when_txt = "around the clock" if when == "around the clock" else f"between {when}"
        saw = (f"It never drops below {mine[hours].min():.0f} W {when_txt}; the same circuit in similar flats "
               f"drops to {peer_w[hours].min():.0f} W. That is about {per_day:.1f} kWh a day extra")
        saw += (f", {empty_share:.0%} of it while nobody is home." if empty_share and empty_share >= 0.1 else ".")
        title = ("Something is left on around the clock" if when == "around the clock"
                 else "Something is left on during the day" if min(hours) >= 8 and max(hours) <= 17
                 else f"Something is left on {when_txt}")
        out.append(_finding(
            flat_id=lab.flat_id, appliance_id=aid, label=lab.label, kind="left_on", icon="🔌",
            title=title, saw=saw,
            todo=("Find out what it is: a plug-in energy meter or a smart plug shows you. Then switch it off "
                  "at the wall at night and when you go out, or put it on a smart-plug schedule."),
            confidence="Medium",
            why_confident="We know when and how much, but the data cannot say which device it is.",
            kwh_28d=kwh28, sek_28d=sek28, kg_28d=kg28,
            kwh_year=central, kwh_year_low=low, net_kwh_year=central, net_kwh_year_low=low,
            sek_year=central * sek28 / kwh28, sek_year_low=low * sek28 / kwh28,
            kg_year=central * kg28 / kwh28, kg_year_low=low * kg28 / kwh28,
            basis="This use does not depend on the weather, so we scale the 4 weeks to a full year (low case: you cut only half of it).",
            evidence={"type": "profile", "appliance_id": aid, "peers": list(peers), "hours": hours},
        ))
    return out


def find_heaters(d: Dataset, labels: pd.DataFrame) -> list[dict]:
    out = []
    h, ctx = d.hourly, d.context
    heaters = labels[(labels.kind == "heater") & (labels.kwh_day > 0.01)]
    if heaters.empty:
        return out
    heater_flats = set(heaters.flat_id)
    peer_temp = ctx[~ctx.flat_id.isin(heater_flats)].indoor_temp_c.median()
    for aid, lab in heaters.iterrows():
        f = lab.flat_id
        x = h[(h.appliance_id == aid) & h.kwh.notna()]
        flat_temp = ctx[ctx.flat_id == f].indoor_temp_c.mean()
        total = x.kwh.sum()
        share = total / h[h.flat_id == f].kwh.sum()
        empty = x[x.occupants_home == 0]
        empty_hours = int((empty.kwh > 0).sum())
        price = x.sek.sum() / total
        carbon = x.kg.sum() / total
        scale = HEATING_SEASON_DAYS / d.days
        ev = {"type": "heater", "appliance_id": aid, "flat_id": f, "peer_temp": peer_temp}
        if flat_temp >= peer_temp + 1.0:
            warm = x[x.indoor_temp_c >= peer_temp + 0.5].kwh.sum()
            central, low = warm * scale, empty.kwh.sum() * scale
            saw = (f"It used {total:.0f} kWh in 4 weeks ({share:.0%} of your flat's electricity) while your "
                   f"flat averaged {flat_temp:.1f} °C. Flats without a heater stay at {peer_temp:.1f} °C on the "
                   f"building's heating alone.")
            if empty_hours:
                saw += f" It also ran for {empty_hours} hours with nobody home."
            out.append(_finding(
                flat_id=f, appliance_id=aid, label=lab.label, kind="heater_warm", icon="🔥",
                title="Your heater is heating a warm flat",
                saw=saw,
                todo=(f"Turn it off: the radiators already keep similar flats at {peer_temp:.1f} °C. If someone "
                      "feels cold, use the heater's thermostat and a timer instead of leaving it on, and never "
                      "leave it on when you go out."),
                confidence="High",
                why_confident=f"Your flat is {flat_temp - peer_temp:.1f} °C warmer than similar flats with no heater.",
                kwh_28d=warm, sek_28d=warm * price, kg_28d=warm * carbon,
                kwh_year=central, kwh_year_low=low, net_kwh_year=central, net_kwh_year_low=low,
                sek_year=central * price, sek_year_low=low * price,
                kg_year=central * carbon, kg_year_low=low * carbon,
                basis=("Heating season only (Oct-Apr, 212 days) at October's rate. Winter is colder, so this is "
                       "on the low side. Low case: only the hours nobody was home."),
                evidence=ev,
            ))
        else:
            central, low = total * scale, total * scale * 0.5
            out.append(_finding(
                flat_id=f, appliance_id=aid, label=lab.label, kind="heater_radiator", icon="🌡️",
                title="Your heater may be covering for a broken radiator",
                saw=(f"It used {total:.0f} kWh in 4 weeks ({share:.0%} of your flat's electricity), but your flat is "
                     f"no warmer ({flat_temp:.1f} °C) than similar flats that use no heater. That points to a radiator "
                     "that isn't working properly, or a draught."),
                todo=("Report the radiator or draught to your housing company. Heat from the building's district "
                      "heating is cheaper for you and lower-carbon. Until it's fixed, run the heater on its "
                      "thermostat, not flat out."),
                confidence="Medium",
                why_confident="We can see the heater and the room temperature, but not the radiator itself.",
                energy_saving=False,
                kwh_28d=total, sek_28d=total * price, kg_28d=0.0,
                kwh_year=central, kwh_year_low=low,
                sek_year=central * price, sek_year_low=low * price,
                basis=("Saves this electricity on your bill, but the heat then comes from district heating, so it "
                       "is not counted as energy or CO2e saved. Heating season (212 days); low case: half."),
                evidence=ev,
            ))
    return out


def find_peak_runs(d: Dataset, labels: pd.DataFrame, pc: dict) -> list[dict]:
    """One finding per flat: move its timed appliances out of the expensive hours."""
    out = []
    h = d.hourly
    peak = pc["peak_hours"]
    shiftable = labels[labels.kind.isin(SHIFTABLE)]
    for flat, labs in shiftable.groupby("flat_id"):
        ids = labs.index.tolist()
        x = h[h.appliance_id.isin(ids) & (h.kwh > 0)]
        xp = x[x.hour.isin(peak)]
        if x.empty or xp.kwh.sum() < 0.5:
            continue
        kwh_p = xp.kwh.sum()
        share = kwh_p / x.kwh.sum()
        sek28 = xp.sek.sum() - kwh_p * pc["off_price"]
        kg28 = xp.kg.sum() - kwh_p * pc["off_carbon"] / 1000
        scale = YEAR_DAYS / d.days
        starts = sorted({int(xx.hour.mode().iloc[0]) for _, xx in xp.groupby("appliance_id")})
        start_txt = " and ".join(f"{s:02d}:00" for s in starts)
        n = len(xp.appliance_id.unique())
        what = "Your dishwasher and washing machine usually start" if n > 1 else "Your dishwasher or washing machine usually starts"
        saw = (f"{what} at {start_txt}, so {share:.0%} of their energy falls in the expensive hours "
               f"({pc['peak_label']}). Power then costs about {pc['peak_price']:.2f} SEK/kWh and the grid is dirtiest "
               f"({pc['peak_carbon']:.0f} g CO2e/kWh). Other hours average {pc['off_price']:.2f} SEK/kWh and "
               f"{pc['off_carbon']:.0f} g.")
        out.append(_finding(
            flat_id=flat, appliance_id=", ".join(sorted(xp.appliance_id.unique())),
            label=LABELS["timed"], kind="shift", icon="🕘",
            title="Start the dishwasher and laundry later",
            saw=saw,
            todo=("Use delay-start or a plug timer so they run at 22:00 or later, or between 10:00 and 16:00 at "
                  "weekends. Same kWh, lower price, cleaner power. Check your laundry-room booking rules."),
            confidence="High",
            why_confident="Prices and timing are measured. Assumes the machines can start later (delay-start or timer).",
            energy_saving=False,
            sek_28d=sek28, kg_28d=kg28,
            sek_year=sek28 * scale, sek_year_low=sek28 * scale * 0.5,
            kg_year=kg28 * scale, kg_year_low=kg28 * scale * 0.5,
            basis="Moving a run saves money and CO2e, not kWh. Scaled to a year; low case: half the runs move.",
            evidence={"type": "timing", "appliance_ids": ids},
        ))
    return out


# ---------------------------------------------------------------- summaries
@dataclass
class Analysis:
    labels: pd.DataFrame    # one row per appliance: what we think it is (kind, label, how)
    findings: pd.DataFrame  # one row per action, all flats, best first (spot-price SEK)
    baseline: pd.DataFrame  # one row per flat: 4-week kWh, SEK, kg CO2e and per-student figures
    prices: dict            # expensive hours and average prices/carbon (see price_context)


def analyse(d: Dataset) -> Analysis:
    labels = label_appliances(d)
    pc = price_context(d)
    faults = find_step_changes(d, labels)
    skip = {f["appliance_id"] for f in faults}
    findings = faults + find_peer_excess(d, labels, skip) + find_heaters(d, labels) + find_peak_runs(d, labels, pc)
    fdf = pd.DataFrame(findings)
    if not fdf.empty:
        fdf = fdf.sort_values("sek_year", ascending=False).reset_index(drop=True)
    return Analysis(labels=labels, findings=fdf, baseline=baseline(d), prices=pc)


def baseline(d: Dataset) -> pd.DataFrame:
    g = d.hourly.groupby("flat_id").agg(
        kwh=("kwh", "sum"), sek=("sek", "sum"), kg=("kg", "sum"),
        coverage=("kwh", lambda s: s.notna().mean()))
    g = g.join(d.flats.set_index("flat_id")[["residents", "floor_area_m2"]])
    g["kwh_student_day"] = g.kwh / g.residents / d.days
    g["kwh_m2_day"] = g.kwh / g.floor_area_m2 / d.days
    g["sek_student"] = g.sek / g.residents
    g["kg_student"] = g.kg / g.residents
    return g


def savings_case(fdf: pd.DataFrame, flats: pd.DataFrame, extra_sek_per_kwh: float = 0.0) -> dict:
    """Per-student-per-year savings for the pitch slide (central and low case)."""
    students = int(flats.residents.sum())
    if fdf.empty:
        return {"students": students}
    res = {"students": students}
    for case, suf in [("central", ""), ("low", "_low")]:
        net_kwh = fdf[f"net_kwh_year{suf}"].sum()
        bill_kwh = fdf[f"kwh_year{suf}"].sum()
        sek = fdf[f"sek_year{suf}"].sum() + bill_kwh * extra_sek_per_kwh
        kg = fdf[f"kg_year{suf}"].sum()
        res[case] = {"net_kwh": net_kwh / students, "bill_kwh": bill_kwh / students,
                     "sek": sek / students, "kg": kg / students,
                     "total_net_kwh": net_kwh, "total_sek": sek, "total_kg": kg}
    affected = flats[flats.flat_id.isin(fdf[fdf.kind != "shift"].flat_id)].residents.sum()
    res["students_affected"] = int(affected)
    return res
