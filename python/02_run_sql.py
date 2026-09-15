"""
02_run_sql.py
=============
Executes every .sql file in sql/ against data/lending.duckdb, prints each
result set, and saves it to outputs/tables/ as CSV so the findings are
reproducible without a database.

Run:  python python/02_run_sql.py
      python python/02_run_sql.py 02          # just the hypothesis tests
"""

from pathlib import Path
import re
import sys
import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lending.duckdb"
SQL_DIR = ROOT / "sql"
OUT = ROOT / "outputs" / "tables"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def split_statements(text: str) -> list[str]:
    """Split a script into statements, dropping comment-only fragments."""
    parts, buf = [], []
    in_str = in_comment = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_comment:
            if ch == "\n":
                in_comment = False
            buf.append(ch)
        elif in_str:
            if ch == "'":
                in_str = False
            buf.append(ch)
        elif ch == "-" and i + 1 < n and text[i + 1] == "-":
            in_comment = True
            buf.append(ch)
        elif ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == ";":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf))

    out = []
    for p in parts:
        stripped = re.sub(r"--[^\n]*", "", p).strip()
        if stripped:
            out.append(p.strip())
    return out


def title_of(stmt: str) -> str:
    """Pull the '-- Qn. ...' banner comment above a statement, for labelling."""
    for line in stmt.splitlines():
        m = re.match(r"--\s*((?:Q|H)\d+\w*\.\s*.+)", line.strip())
        if m:
            return m.group(1).strip()
    return ""


def main() -> None:
    if not DB.exists():
        raise SystemExit("Database missing. Run: python python/01_build_db.py")

    only = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(SQL_DIR.glob("*.sql"))
    if only:
        files = [f for f in files if f.name.startswith(only)]

    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))

    for path in files:
        print("\n" + "=" * 78)
        print(f"  {path.name}")
        print("=" * 78)

        statements = split_statements(path.read_text())
        q = 0
        for stmt in statements:
            # strip leading comment lines before deciding if this is DDL
            head = re.sub(r"^(?:\s*--[^\n]*\n)+", "", stmt).lstrip().upper()
            # DDL: run it, nothing to display
            if head.startswith(("CREATE", "DROP", "SET", "INSTALL", "LOAD")):
                con.execute(stmt)
                continue

            q += 1
            label = title_of(stmt) or f"query {q}"
            print(f"\n--- {label} ---")
            df = con.execute(stmt).fetchdf()
            print(df.to_string(index=False))

            slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60]
            df.to_csv(OUT / f"{path.stem}__{slug}.csv", index=False)

    con.close()
    print(f"\nResult tables written to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
