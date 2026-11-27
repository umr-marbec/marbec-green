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

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SECONDS_PER_HOUR = 3600.0
KG_PER_TONNE = 1000.0
EXPECTED_MONTHS = 12

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
