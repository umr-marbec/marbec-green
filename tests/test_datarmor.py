"""Unit tests for datarmor.py (run with: python -m pytest tests/)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import datarmor  # noqa: E402
from datarmor import (  # noqa: E402
    MachineStats,
    annual_core_hours,
    anonymize_users,
    counter_increase,
    cpu_hours_by_user,
    energy_kwh,
    footprint_tco2e,
    parse_mail_cpu_seconds,
    read_monthly_cpu_seconds,
    read_pbsacct_report,
)

MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
          "Aout", "Septembre", "Octobre", "Novembre", "Décembre"]
MACHINE_2023 = MachineStats(2023, energy_kwh=1.64e6,
                            core_hours=(2003 + 47780 + 17196) * 1000)


def _write_table(path, months, rows):
    lines = [",Bilan mensuel CPU (en seconde)", "user," + ",".join(months)]
    lines += [f"{user}," + ",".join(str(v) for v in values) for user, values in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_kwh_per_core_hour():
    assert MACHINE_2023.kwh_per_core_hour == pytest.approx(0.0244853, rel=1e-5)


def test_machine_stats_rejects_non_positive():
    with pytest.raises(ValueError):
        MachineStats(2024, energy_kwh=0, core_hours=1)


def test_one_core_hour_at_one_kw():
    machine = MachineStats(2024, energy_kwh=1.0, core_hours=1.0)
    assert energy_kwh(3600, machine) == pytest.approx(1.0)
    assert footprint_tco2e(3600, machine, kgco2e_per_kwh=1000.0) == pytest.approx(1.0)


def test_overhead_factor_is_linear():
    base = footprint_tco2e(1e9, MACHINE_2023, 0.052)
    assert footprint_tco2e(1e9, MACHINE_2023, 0.052, 1.42) == pytest.approx(1.42 * base)


def test_reproduces_previous_notebook_value():
    cpu_seconds = 31_748_743_199  # sum of marbec-datarmor-2024.csv
    assert footprint_tco2e(cpu_seconds, MACHINE_2023, 0.052, 1.42) == pytest.approx(
        15.94, abs=0.01)


def test_missing_month_is_detected(tmp_path):
    months = [m for m in MONTHS if m != "Mai"]  # same layout as the 2024 file
    path = _write_table(tmp_path / "cpu.csv", months, [("alice", [1] * 11)])
    with pytest.raises(ValueError, match="11 month columns"):
        read_monthly_cpu_seconds(path)
    assert read_monthly_cpu_seconds(path, strict=False).shape == (1, 11)


def test_full_year_and_whitespace_in_header(tmp_path):
    months = [m + " " if m == "Aout" else m for m in MONTHS]
    path = _write_table(tmp_path / "cpu.csv", months, [("alice", [3600] * 12)])
    df = read_monthly_cpu_seconds(path)
    assert "Aout" in df.columns
    assert df.to_numpy().sum() / 3600 == 12


def test_cpu_hours_by_user_drops_zero_and_sorts(tmp_path):
    rows = [("idle", [0] * 12), ("small", [3600] + [0] * 11), ("big", [7200] * 12)]
    path = _write_table(tmp_path / "cpu.csv", MONTHS, rows)
    hours = cpu_hours_by_user(read_monthly_cpu_seconds(path))
    assert list(hours.index) == ["big", "small"]
    assert hours["big"] == pytest.approx(24.0)


def test_parse_mail(tmp_path):
    path = tmp_path / "mail.txt"
    path.write_text("Bonjour,\n202301:adupaix : 478250353\n\n202312:dkaplan:8771535\n"
                    "not a data line\n", encoding="utf-8")
    df = parse_mail_cpu_seconds(path)
    assert len(df) == 2
    assert df.loc[0].tolist() == [2023, 1, "adupaix", 478250353]
    assert df["month"].tolist() == [1, 12]


PBSACCT_RAW = """\
user        count(jobid)  Ucput_s     EFWALCoreUsed
----------  ------------  ----------  -------------
alice       10            3600        7200.0
bob         5             36000       72000.0
carol       1             0           10.0
"""


def test_read_pbsacct_report_fixed_width(tmp_path):
    path = tmp_path / "marbec-2025.txt"
    path.write_text(PBSACCT_RAW, encoding="utf-8")
    table = read_pbsacct_report(path)
    assert list(table.index) == ["alice", "bob", "carol"]
    assert table.loc["bob", "Ucput_s"] == 36000
    assert table["count(jobid)"].sum() == 16


def test_anonymize_users_orders_by_usage_and_hides_logins(tmp_path):
    path = tmp_path / "marbec-2025.txt"
    path.write_text(PBSACCT_RAW, encoding="utf-8")
    table = read_pbsacct_report(path)
    anon, mapping = anonymize_users(table, sort_by="Ucput_s")
    assert mapping == {"bob": "user01", "alice": "user02", "carol": "user03"}
    assert list(anon.index) == ["user01", "user02", "user03"]
    assert anon["Ucput_s"].sum() == table["Ucput_s"].sum()
    # round trip through the anonymised CSV, no login left in the file
    out = tmp_path / "anon.csv"
    anon.to_csv(out)
    text = out.read_text(encoding="utf-8")
    assert not any(login in text for login in mapping)
    assert read_pbsacct_report(out).equals(anon)


def test_anonymize_users_rejects_duplicates():
    import pandas as pd
    table = pd.DataFrame({"Ucput_s": [1, 2]}, index=["x", "x"])
    with pytest.raises(ValueError):
        anonymize_users(table)


def test_all_users_sum_to_machine_electricity():
    # L1p5: attributing all the machine hours gives back E_machine * FE_elec
    machine = MachineStats(2024, energy_kwh=5e5, core_hours=2e6)
    users_hours = [1.5e6, 4e5, 1e5]
    total = sum(footprint_tco2e(h * 3600, machine, 0.05) for h in users_hours)
    assert total == pytest.approx(5e5 * 0.05 / 1000)


def _daily(values, start="2025-01-01"):
    import pandas as pd
    index = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def test_counter_increase_bridges_gaps_and_ignores_resets():
    nan = float("nan")
    # 100 -> 110 (+10), gap, -> 130 (+20), reset to 0 (ignored), -> 5 (+5)
    assert counter_increase(_daily([100, 110, nan, 130, 0, 5])) == pytest.approx(35)


def test_annual_core_hours_drops_gaps_and_spikes():
    nan = float("nan")
    hour = 3600.0
    # 2 cores all day = 48 core-hours/day; one missing day; one artefact
    # such as the 81 M core-hours booked on 2025-03-17.
    days = _daily([48 * hour, nan, 48 * hour, 1e6 * 48 * hour, 48 * hour])
    assert annual_core_hours(days) == pytest.approx(48 * 365)
    assert annual_core_hours(days, outlier_factor=float("inf")) > 1e6


def test_annual_core_hours_rejects_empty():
    with pytest.raises(ValueError):
        annual_core_hours(_daily([float("nan")] * 3))


def test_grafana_year_uses_full_year_and_cache(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(target, start, end):
        calls.append((target, start, end))
        if target.startswith("sumSeries(DIRIS"):
            return _daily(range(366), start="2025-01-01")  # +1 kWh per day
        return _daily([3600.0] * 365, start="2025-01-02")

    monkeypatch.setattr(datarmor, "fetch_graphite", fake_fetch)
    cache = tmp_path / "grafana-2025.csv"
    table = datarmor.grafana_year(2025, cache=cache)
    # energy counters start the day before so that 1 January 00:00 is kept
    assert calls[0][1:] == ("20241231", "20260101")
    assert counter_increase(table["diris_kwh"]) == pytest.approx(365)
    assert len(calls) == 2 + len(datarmor.PBS_CLUSTERS)
    assert table["EFWALCoreUsed_HPCSIMPLE"].sum() == pytest.approx(365 * 3600)
    # second call reads the cache, no network access
    again = datarmor.grafana_year(2025, cache=cache)
    assert len(calls) == 2 + len(datarmor.PBS_CLUSTERS)
    assert counter_increase(again["diris_kwh"]) == pytest.approx(365)
