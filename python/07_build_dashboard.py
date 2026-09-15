"""
07_build_dashboard.py
=====================
Inlines dashboard/data.json into dashboard/template.html to produce a single
self-contained dashboard/index.html.

Inlining rather than fetching is deliberate: the file then opens from disk, from
a static host, or as a published artifact with no server and no CORS, and it can
never render stale numbers against a moved data file.

Run:  python python/07_build_dashboard.py
Writes: dashboard/index.html
"""

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
TEMPLATE = DASH / "template.html"
DATA = DASH / "data.json"
OUT = DASH / "index.html"

PLACEHOLDER = "__PAYLOAD__"


def main() -> None:
    for p in (TEMPLATE, DATA):
        if not p.exists():
            raise SystemExit(f"Missing {p}. Run python/06_dashboard_data.py first.")

    template = TEMPLATE.read_text()
    if PLACEHOLDER not in template:
        raise SystemExit(f"{PLACEHOLDER} not found in template.html")

    payload = json.loads(DATA.read_text())

    # compact, and escaped so the JSON can never terminate its own script tag
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    OUT.write_text(template.replace(PLACEHOLDER, blob))
    kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.relative_to(ROOT)}  ({kb:.0f} KB, self-contained)")


if __name__ == "__main__":
    main()
