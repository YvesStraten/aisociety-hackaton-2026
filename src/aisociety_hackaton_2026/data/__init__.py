"""Data layer: load and clean the CSV files, find energy waste, and prepare one flat for the views.

    cleaning.py  - read datasets/*.csv, fix the planted data problems, join readings to prices and context
    analysis.py  - label the appliances, run the waste detectors, put kWh / SEK / CO2e on each action
    context.py   - FlatContext: everything the tabs need about the selected flat
"""
from .analysis import LABELS, Analysis, analyse, savings_case
from .cleaning import Dataset, load
from .context import FlatContext, build_context

__all__ = ["LABELS", "Analysis", "Dataset", "FlatContext", "analyse", "build_context", "load", "savings_case"]
