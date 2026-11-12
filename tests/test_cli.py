from pathlib import Path

from kabu.cli import main


def test_judge_demo_end_to_end(tmp_path: Path, capsys):
    out = tmp_path / "reports"
    rc = main(["judge", "--config", "config", "--as-of", "2026-11-12", "--source", "demo", "--out", str(out), "--notify"])
    assert rc == 0
    report = (out / "latest.md").read_text(encoding="utf-8")
    assert "# 株式判定レポート 2026-11-12" in report
    assert "9861" in report
    assert (out / "report_20261112.md").exists()
    captured = capsys.readouterr()
    assert "株式判定 2026-11-12" in captured.out  # stdout 通知


def test_income_command(capsys):
    assert main(["income", "--as-of", "2026-11-12"]) == 0
    out = capsys.readouterr().out
    assert "9861" in out and "権利付き最終日" in out
