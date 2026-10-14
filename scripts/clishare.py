"""Run directly from a source checkout without installation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clishare.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
