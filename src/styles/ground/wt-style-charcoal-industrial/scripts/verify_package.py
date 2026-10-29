"""Verify the exact local candidate file set and current identity."""
from candidate_package import verify
import json

def main():
    report=verify()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 2

if __name__=="__main__":
    raise SystemExit(main())
