"""pyhcl - Validate and lint HCL/Terraform files from Python."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Block:
    type: str
    labels: List[str]
    start_line: int
    end_line: int
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class Issue:
    kind: str
    message: str
    path: str
    line: int
    severity: str = "error"


@dataclass
class FileReport:
    path: str
    ok: bool
    issues: List[Issue] = field(default_factory=list)
    block_count: int = 0


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

_BLOCK_RE = re.compile(
    r"^(?P<indent>\s*)(?P<type>[A-Za-z_][A-Za-z0-9_]*)(?P<labels>(\s+\"[^\"]*\")*)\s*\{",
    re.MULTILINE,
)
_ATTR_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(?P<value>.+)$",
    re.MULTILINE,
)
_CLOSE_RE = re.compile(r"^\s*\}")
_HCL_EXT_RE = re.compile(r"\.(tf|tfvars|hcl)$", re.IGNORECASE)


def _is_hcl(path: Path) -> bool:
    return path.is_file() and bool(_HCL_EXT_RE.search(path.suffix))


def _attr_value(raw: str) -> Optional[str]:
    v = raw.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    return None


def _extract_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _block_end(lines: List[str], start_idx: int, base_indent: str) -> int:
    i = start_idx
    while i < len(lines):
        line = lines[i]
        if line.strip() == "" or line.lstrip().startswith("#"):
            i += 1
            continue
        indent = _extract_indent(line)
        if len(indent) < len(base_indent):
            return i - 1
        if indent == base_indent and _CLOSE_RE.match(line):
            return i
        i += 1
    return len(lines) - 1


def _scan(path: Path) -> FileReport:
    rel = str(path)
    if not _is_hcl(path):
        return FileReport(path=rel, ok=False, issues=[Issue("extension", "unsupported file type", rel, 0)])

    issues: List[Issue] = []
    blocks = 0

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - environment error
        return FileReport(path=rel, ok=False, issues=[Issue("read", str(exc), rel, 0)])

    lines = text.splitlines()

    # 1) Block parsing
    block_spans: List[Tuple[str, int, int]] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for m in _BLOCK_RE.finditer(line):
            blocks += 1
            btype = m.group("type")
            labels = [l.strip().strip('"') for l in m.group("labels").split('"') if l.strip()]
            start = idx
            end = _block_end(lines, idx - 1, m.group("indent"))
            block_spans.append((btype, start, end))
            inner = lines[idx:end]
            non_blank = [l for l in inner if l.strip() and not l.lstrip().startswith("#")]
            if not non_blank:
                issues.append(Issue("empty_block", f"empty {btype} block", rel, idx, "warning"))

    # 1b) Brace balance
    open_count = sum(line.count("{") for line in lines)
    close_count = sum(line.count("}") for line in lines)
    if open_count != close_count:
        issues.append(Issue("unclosed_block", "unbalanced braces in file", rel, block_spans[-1][1] if block_spans else 1))

    # 2) Attribute checks
    for am in _ATTR_RE.finditer(text):
        line_idx = text[: am.start()].count("\n") + 1
        key = am.group("key")
        raw_value = am.group("value")
        val = _attr_value(raw_value)
        if val is None:
            continue
        if "password" in key.lower() and val:
            issues.append(Issue("secret", f"possible secret in attribute {key}", rel, line_idx, "warning"))
        if key.endswith(".count") and val.isdigit() and int(val) == 0:
            issues.append(Issue("zero_count", f"{key} = 0 may be unintended", rel, line_idx, "warning"))

    # 3) HCL syntax/style rules
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            left, right = stripped.split("=", 1)
            if not left.strip() or not right.strip():
                issues.append(Issue("syntax", "attribute has empty left/right side", rel, idx))
        if "\t" in line:
            issues.append(Issue("style", "tab character detected; use spaces for indentation", rel, idx, "warning"))

    # 4) Line-length check
    for idx, line in enumerate(lines, start=1):
        if len(line) > 200:
            issues.append(Issue("style", f"line exceeds 200 chars ({len(line)})", rel, idx, "warning"))

    return FileReport(path=rel, ok=not any(i.severity == "error" for i in issues), issues=issues, block_count=blocks)


def scan_paths(paths: List[str]) -> List[FileReport]:
    reports: List[FileReport] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if _is_hcl(child):
                    reports.append(_scan(child))
        elif _is_hcl(p):
            reports.append(_scan(p))
        else:
            reports.append(FileReport(path=raw, ok=False, issues=[Issue("extension", "unsupported file type", raw, 0)]))
    return reports


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_text(report: FileReport) -> str:
    lines: List[str] = [f"file: {report.path}  blocks={report.block_count}"]
    if report.ok:
        lines.append("  OK")
    else:
        lines.append("  ISSUES")
        for iss in report.issues:
            lines.append(f"  {iss.severity.upper()}: {iss.kind}: {iss.message} (line {iss.line})")
    return "\n".join(lines)


def format_summary(reports: List[FileReport]) -> str:
    issues = [i for r in reports for i in r.issues]
    errs = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warning"]
    lines = [
        f"files={len(reports)}",
        f"errors={len(errs)}",
        f"warnings={len(warns)}",
    ]
    if errs:
        lines.append("RESULT: FAIL")
    elif warns:
        lines.append("RESULT: WARN")
    else:
        lines.append("RESULT: OK")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pyhcl", description="Validate and lint HCL/Terraform files")
    parser.add_argument("paths", nargs="+", help="HCL files or directories to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON report instead of text")
    parser.add_argument("--check", action="store_true", help="exit non-zero if any error is found")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    reports = scan_paths(args.paths)

    if args.json:
        payload = []
        for r in reports:
            payload.append(
                {
                    "path": r.path,
                    "ok": r.ok,
                    "blocks": r.block_count,
                    "issues": [
                        {
                            "kind": i.kind,
                            "message": i.message,
                            "line": i.line,
                            "severity": i.severity,
                        }
                        for i in r.issues
                    ],
                }
            )
        summary = format_summary(reports)
        out = {"reports": payload, "summary": summary}
        print(json.dumps(out, indent=2))
    else:
        for r in reports:
            print(format_text(r))
        print(format_summary(reports))

    if args.check and not all(r.ok for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
