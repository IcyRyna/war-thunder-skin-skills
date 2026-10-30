"""Compatibility entry point: verify the installed Skill file set and identity."""
from pathlib import Path
from verify_release import verify as verify_release
import json

def verify(root=None):
    return verify_release(Path(__file__).resolve().parents[1] if root is None else root)

def main():
    report=verify()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 2

if __name__=="__main__":
    raise SystemExit(main())
