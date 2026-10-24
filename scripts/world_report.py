"""Thin wrapper: print the OKÚ world readout (P-008). Same logic as `python -m oku_slack.world.report`."""
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from oku_slack.world.report import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
