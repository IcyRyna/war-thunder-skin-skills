"""Run charcoal development tests; tests and fixtures are outside the Skill ZIP."""
from pathlib import Path
import os,sys,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
os.environ.setdefault('WT_CHARCOAL_ASSETS',str(ROOT/'assets/charcoal-industrial'))
sys.path.insert(0,str(ROOT/'src/styles/ground/wt-style-charcoal-industrial/scripts'))
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests/charcoal_industrial'))
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
