import json
import subprocess
import sys
from pathlib import Path

import pytest

from pyhcl import FileReport, Issue, _scan, format_summary, format_text, scan_paths


HCL = """
provider "aws" {
  region = "us-east-1"
}

resource "aws_instance" "web" {
  ami           = "ami-12345"
  instance_type = "t2.micro"
  tags = {
    Name = "web"
  }
}
"""

BAD_BLOCK = """
resource "aws_instance" "web" {
}
"""

SECRET = """
resource "aws_db_instance" "default" {
  password = "hunter2"
}
"""

TAB = 'resource "x" "y" {\n\tfoo = 1\n}\n'


def test_scan_valid_hcl(tmp_path: Path) -> None:
    p = tmp_path / "main.tf"
    p.write_text(HCL, encoding="utf-8")
    report = _scan(p)
    assert report.ok
    assert report.block_count == 2
    assert report.path == str(p)


def test_scan_unclosed_block(tmp_path: Path) -> None:
    p = tmp_path / "bad.tf"
    p.write_text(BAD_BLOCK, encoding="utf-8")
    report = _scan(p)
    kinds = [i.kind for i in report.issues]
    assert "empty_block" in kinds


def test_scan_secret_detection(tmp_path: Path) -> None:
    p = tmp_path / "secret.tf"
    p.write_text(SECRET, encoding="utf-8")
    report = _scan(p)
    assert any(i.kind == "secret" for i in report.issues)


def test_scan_style_tab_and_length(tmp_path: Path) -> None:
    long_line = "x = " + "a" * 210 + "\n"
    p = tmp_path / "style.tf"
    p.write_text(TAB + long_line, encoding="utf-8")
    report = _scan(p)
    assert any(i.kind == "style" and "tab" in i.message for i in report.issues)
    assert any(i.kind == "style" and "200 chars" in i.message for i in report.issues)


def test_scan_unsupported_extension(tmp_path: Path) -> None:
    p = tmp_path / "readme.txt"
    p.write_text("hello", encoding="utf-8")
    report = _scan(p)
    assert not report.ok
    assert any(i.kind == "extension" for i in report.issues)


def test_format_text() -> None:
    report = FileReport(path="ok.tf", ok=True, block_count=1)
    out = format_text(report)
    assert "OK" in out
    report2 = FileReport(path="bad.tf", ok=False, issues=[Issue("x", "msg", "bad.tf", 1)])
    out2 = format_text(report2)
    assert "ISSUES" in out2 and "msg" in out2


def test_format_summary() -> None:
    report = FileReport(path="a.tf", ok=False, issues=[Issue("syntax", "m", "a.tf", 1)])
    out = format_summary([report])
    assert "RESULT: FAIL" in out
    warn_report = FileReport(path="b.tf", ok=True, issues=[Issue("style", "m", "b.tf", 1, "warning")])
    out2 = format_summary([warn_report])
    assert "RESULT: WARN" in out2
    ok_report = FileReport(path="c.tf", ok=True)
    out3 = format_summary([ok_report])
    assert "RESULT: OK" in out3


def test_scan_directory(tmp_path: Path) -> None:
    d = tmp_path / "mod"
    d.mkdir()
    (d / "a.tf").write_text(HCL, encoding="utf-8")
    (d / "b.txt").write_text("ignore", encoding="utf-8")
    reports = scan_paths([str(d)])
    assert len(reports) == 1
    assert reports[0].path == str(d / "a.tf")


def test_cli_check_flag_returns_nonzero(tmp_path: Path) -> None:
    p = tmp_path / "unsupported.txt"
    p.write_text("hello", encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "pyhcl", "--check", str(p)], capture_output=True, text=True)
    assert proc.returncode == 1


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "main.tf"
    p.write_text(HCL, encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "pyhcl", "--json", str(p)], capture_output=True, text=True)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert len(payload["reports"]) == 1
    assert payload["reports"][0]["path"] == str(p)
