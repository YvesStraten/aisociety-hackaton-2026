# aisociety-hackaton-2026

**Flat Energy Coach** finds the energy waste in a student flat and tells the students what to do about it, with the kWh, SEK and CO2e each action saves. It runs on the organisers' synthetic dataset in `datasets/`.

## Run it

You need [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv run aisociety-hackaton-2026
```

The app opens at http://localhost:8501. Pick a flat in the sidebar, then use the tabs:

- **My flat**: this week's numbers, the top actions with their evidence, and a coach message
- **Savings case**: expected savings per student per year, every action found, assumptions and sources
- **My usage**: electricity by appliance, week by week, the average day, and the comparison with similar flats

Behind a corporate proxy, add `--system-certs` after `uv run`.

## Code layout

```
src/aisociety_hackaton_2026/
├── app.py           entry point: sidebar, build the flat's data, three tabs
├── coach.py         weekly coach message (Claude writes it if `anthropic` and ANTHROPIC_API_KEY are set up)
├── data/
│   ├── cleaning.py  read datasets/*.csv, fix the data problems, join prices and context
│   ├── analysis.py  label the appliances, find waste, put kWh / SEK / CO2e on each action
│   └── context.py   FlatContext: everything the tabs need about the selected flat
└── views/
    ├── sidebar.py   flat picker and extra cost per kWh
    ├── my_flat.py, savings_case.py, my_usage.py   one file per tab, split into numbered blocks
    └── charts.py    shared charts and colours
```

To show new data on a tab: add a field to `FlatContext` in `data/context.py`, fill it in `build_context()`, and read it in the view as `ctx.<field>`.
