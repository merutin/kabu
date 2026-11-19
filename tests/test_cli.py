from pathlib import Path

from kabu.cli import main


def test_judge_demo_end_to_end(tmp_path: Path, capsys):
    out = tmp_path / "reports"
    rc = main(["judge", "--config", "config", "--as-of", "2026-11-12", "--source", "demo", "--out", str(out), "--notify"])
    assert rc == 0
    report = (out / "latest.md").read_text(encoding="utf-8")
    assert "# 株式判定レポート 2026-11-12" in report
    assert "9434" in report and "7203" in report
    assert (out / "report_20261112.md").exists()
    captured = capsys.readouterr()
    assert "株式判定 2026-11-12" in captured.out  # stdout 通知


def test_income_command(capsys):
    assert main(["income", "--as-of", "2026-11-12"]) == 0
    out = capsys.readouterr().out
    assert "8267" in out and "権利付き最終日" in out


def test_judge_compares_with_backdated_run(tmp_path: Path):
    from datetime import date

    from kabu.cli import run_judge
    from kabu.config import load_config

    cfg = load_config("config")
    js, data_date, prev = run_judge(cfg, date(2026, 11, 12), "demo", compare_days=7)
    assert set(prev) == {j.stock.code for j in js}
    assert all(p.as_of == date(2026, 11, 5) for p in prev.values())
    assert all(p.metrics.last_close != j.metrics.last_close for p, j in zip(prev.values(), js))
    out = tmp_path / "r"
    assert main(["judge", "--as-of", "2026-11-12", "--source", "demo", "--out", str(out)]) == 0
    report = (out / "latest.md").read_text(encoding="utf-8")
    assert "7日前" in report


def test_truncate_market_data():
    from datetime import date

    from kabu.data.demo import make_market_data

    d = make_market_data()
    t = d.truncate(date(2025, 6, 30))
    assert t.last_date <= date(2025, 6, 30)
    assert (t.dividends.index <= "2025-06-30").all()
