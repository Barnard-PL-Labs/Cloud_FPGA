import sys
from pathlib import Path

# Make design.py / client.py importable from the example root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
