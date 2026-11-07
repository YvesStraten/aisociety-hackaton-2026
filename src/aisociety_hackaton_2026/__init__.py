from pathlib import Path


def main() -> None:
    """Start the Streamlit app: `uv run aisociety-hackaton-2026`."""
    import sys

    from streamlit.web import cli

    app = Path(__file__).with_name("app.py")
    sys.argv = ["streamlit", "run", str(app), *sys.argv[1:]]
    sys.exit(cli.main())
