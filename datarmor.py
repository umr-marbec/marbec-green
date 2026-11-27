"""Estimate the electricity carbon footprint of MARBEC usage on Datarmor (Ifremer).

Electricity term of the Labos 1point5 method (GT "Infrastructures de recherche :
calcul", January 2024, https://labos1point5.org/les-rapports/estimation-empreinte-calcul)::

    FE_core_hour = E_machine * FE_elec / H_machine      (kgCO2e per core-hour)
    footprint    = FE_core_hour * H_user

- ``E_machine``: annual electricity of the machine room (total DIRIS meter,
  cooling included, so no PUE is applied on top of it);
- ``FE_elec``: ADEME electricity emission factor (French average mix of the year);
- ``H_machine`` and ``H_user``: effective core-hours, i.e. hours *reserved* by
  jobs (report annex 2), so that the sum over all users equals the total.

Manufacturing, refrigerant leaks and generator fuel are NOT included.

References
----------
- Labos 1point5 GT Calcul (2024), report above.
- Berthoud et al. (2020), hal-02549565.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
import numpy as np

import pandas as pd

SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
KG_PER_TONNE = 1000.0
EXPECTED_MONTHS = 12

# Graphite datasource behind https://grafana.ifremer.fr (anonymous read access).
GRAPHITE_RENDER_URL = (
    "https://grafana.ifremer.fr/api/datasources/proxy/uid/000000001/render"
)
# Cumulative kWh counter of the "Compteur Energie Datarmor" panel of the
# "Datarmor Diris" dashboard (uid 000000022): whole machine, cooling included.
DIRIS_DATARMOR_TARGET = (
    "sumSeries(DIRISDATARMOR.TOTAL_RP_POS_3,DIRISDATARMOR.TOTAL_RP_POS_4)"
)
# Cumulative kWh counter of the "Compteur Energie Datarmor IT" panel (IT
# equipment only). The PUE of the dashboard is DIRIS_DATARMOR / DIRIS_DATARMOR_IT.
DIRIS_DATARMOR_IT_TARGET = (
    "sumSeries(DIRISDATARMOR.TOTAL_RP_POS_4,scale(DIRISDATARMOR.TOTAL_RP_POS_5,-1))"
)
# Daily reserved core-seconds (cores x walltime) summed over all users of one
# PBS cluster ("*" = all clusters), as in the EFWALCoreUsed panel of the
# "DATARMOR pbsacctsql Total" dashboard (uid 000000028).
PBS_CLUSTERS = ("HPCSIMPLE", "HPCHYPERTHREAD", "SMP", "VISU")
PBS_TARGET = "sumSeries(DATARMORPBS.USERS.*.{cluster}.{metric})"
PBS_EFWALCOREUSED_TARGET = PBS_TARGET.format(cluster="*", metric="EFWALCoreUsed")

# Lines such as "202301:adupaix : 478250353" (YYYYMM:user:cpu_seconds)
_MAIL_LINE = re.compile(r"^\s*(\d{4})(\d{2})\s*:\s*([A-Za-z0-9_]+)\s*:\s*(\d+)\s*$")


@dataclass(frozen=True)
class MachineStats:
    """Machine-wide Datarmor statistics for one year (Grafana dashboards)."""

    year: int
    energy_kwh: float  # total electricity measured by the DIRIS meters
    core_hours: float  # total core-hours delivered by the machine

    def __post_init__(self) -> None:
        if self.energy_kwh <= 0 or self.core_hours <= 0:
            raise ValueError("energy_kwh and core_hours must be strictly positive")

    @property
    def kwh_per_core_hour(self) -> float:
        """Mean energy per core-hour (kWh), i.e. mean power per core (kW)."""
        return self.energy_kwh / self.core_hours


def read_monthly_cpu_seconds(path: str | Path, strict: bool = True) -> pd.DataFrame:
    """Read the per-user x per-month CPU-seconds table (one row per user).

    The file has one title line, then a header ``user,<month>,<month>...``.
    With ``strict=True`` a ValueError is raised if the file does not contain
    exactly 12 month columns (e.g. the 2024 file, where "Mai" is missing).
    """
    df = pd.read_csv(path, skiprows=1, index_col=0)
    df.columns = df.columns.str.strip()
    if strict and df.shape[1] != EXPECTED_MONTHS:
        raise ValueError(
            f"{path}: {df.shape[1]} month columns found, expected "
            f"{EXPECTED_MONTHS}: {list(df.columns)}"
        )
    return df


def read_pbsacct_report(path: str | Path) -> pd.DataFrame:
    """Read a per-user ``pbsacct`` report (one row per user, annual totals).

    Two layouts are accepted:

    * the raw fixed-width export sent by Ifremer: a whitespace-separated
      header, a line of dashes, then one row per user;
    * the anonymised CSV written by :func:`anonymize_users`.

    The ``user`` column becomes the index. ``Ucput_s`` holds the CPU seconds
    actually consumed by the user's jobs.
    """
    path = Path(path)
    if path.suffix == ".csv":
        return pd.read_csv(path, index_col="user")
    df = pd.read_csv(path, sep=r"\s+", skiprows=[1])  # row 1 = "-----" ruler
    return df.set_index("user")


def anonymize_users(table: pd.DataFrame, sort_by: str | None = None,
                    prefix: str = "user") -> tuple[pd.DataFrame, dict[str, str]]:
    """Replace the logins of the index by ``user01``, ``user02``...

    Rows are first sorted by ``sort_by`` (descending), so that the new
    labels follow the usage ranking and leak nothing about the original
    (alphabetical or arbitrary) order. Returns the anonymised table and the
    ``{login: alias}`` mapping, which must NOT be committed.
    """
    if not table.index.is_unique:
        raise ValueError("user index contains duplicates")
    if sort_by is not None:
        table = table.sort_values(sort_by, ascending=False, kind="stable")
    width = max(2, len(str(len(table))))
    mapping = {login: f"{prefix}{i:0{width}d}"
               for i, login in enumerate(table.index, start=1)}
    anonymised = table.rename(index=mapping)
    anonymised.index.name = "user"
    return anonymised, mapping


def parse_mail_cpu_seconds(path: str | Path) -> pd.DataFrame:
    """Parse the e-mail format ``YYYYMM:user : seconds`` into a long DataFrame.

    Returns columns ``year``, ``month``, ``user``, ``cpu_seconds``.
    """
    records = []
    with open(path, encoding="utf-8") as fin:
        for line in fin:
            match = _MAIL_LINE.match(line)
            if match:
                year, month, user, seconds = match.groups()
                records.append((int(year), int(month), user, int(seconds)))
    return pd.DataFrame(records, columns=["year", "month", "user", "cpu_seconds"])


def cpu_hours_by_user(monthly_seconds: pd.DataFrame) -> pd.Series:
    """Total core-hours per user (non-zero users only), sorted descending."""
    hours = monthly_seconds.sum(axis=1) / SECONDS_PER_HOUR
    return hours[hours > 0].sort_values(ascending=False)


def energy_kwh(cpu_seconds: float, machine: MachineStats,
               overhead_factor: float = 1.0) -> float:
    """Convert CPU-seconds to electricity (kWh)."""
    core_hours = cpu_seconds / SECONDS_PER_HOUR
    return core_hours * machine.kwh_per_core_hour * overhead_factor


def footprint_tco2e(cpu_seconds: float, machine: MachineStats,
                    kgco2e_per_kwh: float, overhead_factor: float = 1.0) -> float:
    """Electricity footprint of core-seconds (tCO2e).

    ``overhead_factor`` should be a PUE only if the machine energy does not
    already include cooling; keep 1.0 otherwise to avoid double counting.
    """
    kwh = energy_kwh(cpu_seconds, machine, overhead_factor)
    return kwh * kgco2e_per_kwh / KG_PER_TONNE


def fetch_graphite(target: str, start: str, end: str,
                   url: str = GRAPHITE_RENDER_URL, timeout: float = 120.0) -> pd.Series:
    """Download one Graphite series (``start``/``end`` as ``YYYYMMDD``, UTC).

    Returns a Series indexed by UTC timestamps; missing points are NaN.
    Only the first series is returned, so ``target`` should aggregate
    (e.g. ``sumSeries``).
    """
    query = urllib.parse.urlencode({"target": target, "from": start, "until": end,
                                    "format": "json", "maxDataPoints": 100_000})
    with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as response:
        payload = json.load(response)
    if not payload:
        raise ValueError(f"no data returned for {target!r}")
    values, stamps = zip(*payload[0]["datapoints"])
    index = pd.to_datetime(stamps, unit="s", utc=True)
    return pd.Series(values, index=index, dtype=float, name=payload[0]["target"])


def counter_increase(counter: pd.Series) -> float:
    """Total increase of a cumulative meter (e.g. DIRIS kWh index).

    Equivalent to summing Graphite's ``nonNegativeDerivative``: NaN gaps are
    bridged and negative steps (meter reset) are ignored.
    """
    steps = counter.dropna().diff()
    return float(steps[steps > 0].sum())


def annual_core_hours(daily_core_seconds: pd.Series, outlier_factor: float = 2.0,
                      days_in_year: int = 365) -> float:
    """Extrapolate daily accounting (core-seconds per day) to one full year.

    Days missing from the accounting (NaN) and days above
    ``outlier_factor`` x the median (accounting artefacts, or backlogs that
    re-book the jobs of a preceding gap) are dropped; the mean of the
    remaining days is then multiplied by ``days_in_year``.
    """
    days = daily_core_seconds.dropna()
    if days.empty:
        raise ValueError("no accounting data")
    clean = days[days <= outlier_factor * days.median()]
    return float(clean.mean() * days_in_year / SECONDS_PER_HOUR)


def grafana_year(year: int, cache: str | Path | None = None) -> pd.DataFrame:
    """Daily Datarmor series of one calendar year, from Grafana (Graphite).

    Columns:

    * ``diris_kwh`` / ``diris_it_kwh``: cumulative kWh indexes of the total
      (cooling included) and IT-only meters. The first row (1 January 00:00
      UTC) is the starting index, so :func:`counter_increase` covers the
      whole year;
    * ``EFWALCoreUsed_<cluster>`` for each of :data:`PBS_CLUSTERS`: reserved
      core-seconds booked each day (NaN on days missing from the accounting).

    If ``cache`` is given and exists, it is read instead of querying the
    server; otherwise the downloaded table is written there.
    """
    if cache is not None and Path(cache).exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    # One day before 1 January so that the 1 January 00:00 index is included.
    start = (pd.Timestamp(year=year, month=1, day=1) - pd.Timedelta(days=1)).strftime("%Y%m%d")
    end = f"{year + 1}0101"
    columns = {
        "diris_kwh": fetch_graphite(DIRIS_DATARMOR_TARGET, start, end),
        "diris_it_kwh": fetch_graphite(DIRIS_DATARMOR_IT_TARGET, start, end),
    }
    for cluster in PBS_CLUSTERS:
        target = PBS_TARGET.format(cluster=cluster, metric="EFWALCoreUsed")
        columns[f"EFWALCoreUsed_{cluster}"] = fetch_graphite(target, f"{year}0101", end)
    table = pd.DataFrame(columns)
    # Keep the extra 1 January 00:00 point only for the cumulative meters;
    # accounting columns must not include the first day of the next year.
    next_year = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    pbs_columns = [c for c in table if c.startswith("EFWALCoreUsed_")]
    table.loc[table.index >= next_year, pbs_columns] = np.nan

    table.index.name = "time_utc"
    if cache is not None:
        table.to_csv(cache)

    return table
