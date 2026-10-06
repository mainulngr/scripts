#!/usr/bin/env python3
"""brain-check — validate a project's Brain.

The Brain is the file-based memory: cores, marks, study, journal, handoff.
This checks that it is structurally sound and internally consistent, so drift
is caught before a session starts rather than during one.

Usage:
    brain-check [path] [options]

Options:
    --max-core-lines N      diet trigger for a core      (default 150)
    --max-handoff-lines N   size budget for the handoff  (default 60)
    --stale-days N          warn if the handoff is older (default 14)
    --quiet                 print only warnings and failures
    --no-references         skip reference resolution (slower on big repos)

Exit codes: 0 clean · 1 warnings · 2 failures
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

CORE_DIRS = (".windsurf/rules", ".devin/rules", ".agents/rules")
CORE_NAME = "core.md"
LAYERS = ("_marks", "_study", "_journal")
STALE_TERMS = ("workspace.md", "outbox")
REPORT_RE = re.compile(r"^- `\d{6}_", re.M)
REF_RE = re.compile(r"`([^`\s]+)`")
FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
# A bare filename counts as a path reference only for doc/data files — source
# files (lane-loop.sh) are usually named in prose, not pointed at.
DOC_END = (".md", ".yaml", ".yml", ".json")
SKIP_DIRS = {".git", "node_modules", ".next", "vendor", "__pycache__", ".venv"}

OK, WARN, FAIL = "ok", "warn", "fail"


class Result:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level: str, area: str, msg: str) -> None:
        self.rows.append((level, area, msg))

    @property
    def worst(self) -> int:
        if any(l == FAIL for l, _, _ in self.rows):
            return 2
        if any(l == WARN for l, _, _ in self.rows):
            return 1
        return 0


def frontmatter(text: str) -> dict:
    m = FRONT_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if line.startswith((" ", "\t", "#")) or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.split("#")[0].strip().strip("\"'")
    return out


def find_cores(root: str) -> list:
    found = []
    for base, dirs, _ in os.walk(root):
        rel = os.path.relpath(base, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and depth < 2]
        for cdir in CORE_DIRS:
            p = os.path.join(base, cdir, CORE_NAME)
            if os.path.isfile(p):
                found.append(os.path.relpath(p, root))
    return sorted(found)


def parse_age(value: str):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", value or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    try:
        stamp = dt.datetime(y, mo, d, hh, mm)
    except ValueError:
        return None
    return (dt.datetime.now() - stamp).total_seconds() / 86400


def resolve(ref: str, cdir: str, root: str, bases: list) -> bool:
    if ref.startswith(("http", "~/", "/", "var/", "tmp/", "srv/", "mailto:")):
        return True
    if not re.match(r"^[A-Za-z0-9_.\-/]+$", ref):
        return True
    if ref.startswith("."):
        return True
    if "/" not in ref and not ref.endswith(DOC_END):
        return True
    cands = [os.path.join(root, ref), os.path.join(cdir, ref)]
    cands += [os.path.join(b, ref) for b in bases]
    return any(os.path.exists(c) for c in cands)


def check(root: str, args, res: Result) -> None:
    cores = find_cores(root)
    if not cores:
        res.add(FAIL, "structure", "no core found (.windsurf/rules/core.md)")
        return
    res.add(OK, "structure", f"{len(cores)} core(s): {', '.join(cores)}")

    for core in cores:
        text = open(os.path.join(root, core), encoding="utf-8", errors="replace").read()
        lines = text.count("\n") + 1
        proj = os.path.dirname(os.path.dirname(os.path.dirname(core))) or "."

        fm = frontmatter(text)
        if not fm:
            res.add(FAIL, "frontmatter", f"{core}: no frontmatter block")
        else:
            missing = [k for k in ("description", "trigger") if k not in fm]
            if missing:
                res.add(WARN, "frontmatter", f"{core}: missing {', '.join(missing)}")
            else:
                res.add(OK, "frontmatter", f"{core} ok")

        if lines > args.max_core_lines:
            res.add(WARN, "diet", f"{core}: {lines} lines (>{args.max_core_lines}) — split into marks")
        else:
            res.add(OK, "diet", f"{core}: {lines} lines")

        is_root_core = proj in (".", "")
        if not os.path.isdir(os.path.join(root, proj, "_marks")):
            res.add(WARN, "structure", f"{core}: no _marks/ beside it")
        if is_root_core and not os.path.isdir(os.path.join(root, "_journal")):
            res.add(WARN, "structure", "root: no _journal/")
        if not is_root_core and os.path.isdir(os.path.join(root, proj, "_journal")):
            res.add(WARN, "structure", f"{core}: has its own _journal/ — the journal is repo-wide")

    jdir = os.path.join(root, "_journal")
    if not os.path.isdir(jdir):
        res.add(WARN, "journal", "_journal/ missing")
        return

    handoff = os.path.join(jdir, "handoff.md")
    if not os.path.isfile(handoff):
        if os.path.isfile(os.path.join(jdir, "handoff.yaml")):
            res.add(FAIL, "handoff", "handoff.yaml still present — should be handoff.md")
        else:
            res.add(FAIL, "handoff", "_journal/handoff.md missing")
    else:
        text = open(handoff, encoding="utf-8", errors="replace").read()
        n = text.count("\n") + 1
        if n > args.max_handoff_lines:
            res.add(WARN, "handoff", f"{n} lines (>{args.max_handoff_lines}) — logging, not snapshotting")
        else:
            res.add(OK, "handoff", f"{n} lines")
        age = parse_age(frontmatter(text).get("updated", ""))
        if age is None:
            res.add(WARN, "handoff", "no parseable `updated` in frontmatter")
        elif age > args.stale_days:
            res.add(WARN, "handoff", f"`updated` is {age:.0f} days old — verify before trusting")
        else:
            res.add(OK, "handoff", f"updated {age:.1f} days ago")
        if "## Open" not in text and not re.search(r"^- \[ \]", text, re.M):
            res.add(WARN, "handoff", "no open-items section — nothing to resume?")

    rdir = os.path.join(jdir, "reports")
    reports = [f for f in os.listdir(rdir) if f.endswith(".yaml")] if os.path.isdir(rdir) else []
    index = os.path.join(rdir, "INDEX.md")
    if len(reports) > 5 and not os.path.isfile(index):
        res.add(WARN, "journal", f"{len(reports)} reports with no INDEX.md")
    elif os.path.isfile(index):
        n_idx = len(REPORT_RE.findall(open(index, encoding="utf-8").read()))
        if n_idx != len(reports):
            res.add(WARN, "journal", f"index says {n_idx}, disk has {len(reports)} — regenerate")
        else:
            res.add(OK, "journal", f"{len(reports)} reports indexed")

    bases = [".", "_marks", "_study", "_journal", "_journal/reports"]
    for d1 in sorted(os.listdir(root)):
        p1 = os.path.join(root, d1)
        if not os.path.isdir(p1) or d1.startswith(".") or d1 in SKIP_DIRS:
            continue
        bases += [d1, f"{d1}/_marks", f"{d1}/_study"]
        for d2 in sorted(os.listdir(p1)):
            if os.path.isdir(os.path.join(p1, d2)) and d2 not in SKIP_DIRS:
                bases.append(f"{d1}/{d2}")
    ignore = []
    ipath = os.path.join(root, ".brain-check-ignore")
    if os.path.isfile(ipath):
        ignore = [l.strip() for l in open(ipath, encoding="utf-8")
                  if l.strip() and not l.startswith("#")]

    if not args.no_references:
        for target in cores + ["_journal/handoff.md"]:
            path = os.path.join(root, target)
            if not os.path.isfile(path):
                continue
            cdir = os.path.dirname(path)
            refs = sorted(set(REF_RE.findall(open(path, encoding="utf-8", errors="replace").read())))
            bad = [r for r in refs
                   if not resolve(r, cdir, root, bases)
                   and not any(pat in r for pat in ignore)]
            if bad:
                shown = ", ".join(bad[:3]) + ("…" if len(bad) > 3 else "")
                res.add(WARN, "references", f"{target}: {len(bad)} unresolved ({shown})")
            else:
                res.add(OK, "references", f"{target} resolves")

    hits = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith((".md", ".yaml", ".yml")):
                continue
            p = os.path.join(base, f)
            rel = os.path.relpath(p, root)
            if rel.startswith(("_journal/reports", "_journal/archive")):
                continue
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for term in STALE_TERMS:
                if term in text:
                    hits.append(f"{rel}: {term}")
    if hits:
        shown = ", ".join(hits[:3]) + ("…" if len(hits) > 3 else "")
        res.add(WARN, "vocabulary", f"{len(hits)} stale term(s): {shown}")
    else:
        res.add(OK, "vocabulary", "no retired terms")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a project's Brain.")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--max-core-lines", type=int, default=150)
    ap.add_argument("--max-handoff-lines", type=int, default=60)
    ap.add_argument("--stale-days", type=float, default=14)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-references", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"brain-check: not a directory: {root}", file=sys.stderr)
        return 2

    res = Result()
    check(root, args, res)

    mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}
    print(f"brain-check: {root}")
    for level, area, msg in res.rows:
        if args.quiet and level == OK:
            continue
        print(f"[{mark[level]}] {area:<11} {msg}")
    counts = {lvl: sum(1 for l, _, _ in res.rows if l == lvl) for lvl in (OK, WARN, FAIL)}
    print(f"\n{counts[OK]} ok · {counts[WARN]} warnings · {counts[FAIL]} failures")
    return res.worst


if __name__ == "__main__":
    sys.exit(main())
