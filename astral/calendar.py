"""Calendar, solar-term, and historical civil-time calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import astronomy
from korean_lunar_calendar import KoreanLunarCalendar

from .constants import BRANCHES, MONTH_TERMS, STEMS, TIMEZONE_NAME

UTC = timezone.utc
SEOUL = ZoneInfo(TIMEZONE_NAME)


@dataclass(frozen=True)
class SolarTerm:
    name: str
    longitude: float
    month_offset: int
    instant_utc: datetime


def lunar_to_solar(year: int, month: int, day: int, is_leap_month: bool) -> date:
    calendar = KoreanLunarCalendar()
    if not calendar.setLunarDate(year, month, day, is_leap_month):
        raise ValueError("존재하지 않거나 지원 범위를 벗어난 음력 날짜입니다.")
    return date(calendar.solarYear, calendar.solarMonth, calendar.solarDay)


def day_pillar(local_date: date) -> tuple[str, str]:
    """Return the KARI-aligned sexagenary day for a local civil date."""
    calendar = KoreanLunarCalendar()
    if not calendar.setSolarDate(local_date.year, local_date.month, local_date.day):
        raise ValueError("지원 범위를 벗어난 양력 날짜입니다.")
    day_text = calendar.getGapJaString().split()[2]
    return day_text[0], day_text[1]


@lru_cache(maxsize=16)
def solar_terms_for_year(year: int) -> tuple[SolarTerm, ...]:
    terms: list[SolarTerm] = []
    for month, name, longitude, month_offset in MONTH_TERMS:
        start = astronomy.Time.Make(year, month, 1, 0, 0, 0)
        result = astronomy.SearchSunLongitude(longitude, start, 14.0)
        if result is None:
            raise RuntimeError(f"{year}년 {name} 계산에 실패했습니다.")
        instant = result.Utc().replace(tzinfo=UTC)
        terms.append(SolarTerm(name, longitude, month_offset, instant))
    return tuple(terms)


def surrounding_terms(year: int) -> tuple[SolarTerm, ...]:
    terms = (
        solar_terms_for_year(year - 1)
        + solar_terms_for_year(year)
        + solar_terms_for_year(year + 1)
    )
    return tuple(sorted(terms, key=lambda term: term.instant_utc))


def pillars_at_instant(instant_utc: datetime, local_date: date) -> dict:
    terms = surrounding_terms(local_date.year)
    latest_term = max(
        (term for term in terms if term.instant_utc <= instant_utc),
        key=lambda term: term.instant_utc,
    )
    lichun = next(
        term for term in solar_terms_for_year(local_date.year) if term.name == "입춘"
    )

    pillar_year = local_date.year if instant_utc >= lichun.instant_utc else local_date.year - 1
    year_cycle_index = (pillar_year - 4) % 60
    year_stem_index = year_cycle_index % 10
    year_branch_index = year_cycle_index % 12

    month_branch_index = (2 + latest_term.month_offset) % 12
    first_month_stem_index = ((year_stem_index % 5) * 2 + 2) % 10
    month_stem_index = (first_month_stem_index + latest_term.month_offset) % 10

    day_stem, day_branch = day_pillar(local_date)

    return {
        "year": {"stem": STEMS[year_stem_index], "branch": BRANCHES[year_branch_index]},
        "month": {"stem": STEMS[month_stem_index], "branch": BRANCHES[month_branch_index]},
        "day": {"stem": day_stem, "branch": day_branch},
        "month_term": {
            "name": latest_term.name,
            "instant": latest_term.instant_utc.astimezone(SEOUL).isoformat(timespec="seconds"),
        },
    }


def attach_hour_pillar(pillars: dict, hour: int) -> dict:
    result = {key: dict(value) for key, value in pillars.items()}
    hour_branch_index = ((hour + 1) // 2) % 12
    day_stem_index = STEMS.index(result["day"]["stem"])
    hour_stem_index = ((day_stem_index % 5) * 2 + hour_branch_index) % 10
    result["hour"] = {
        "stem": STEMS[hour_stem_index],
        "branch": BRANCHES[hour_branch_index],
    }
    return result


def resolve_local_time(local_datetime: datetime) -> list[datetime]:
    """Resolve a Seoul wall time, retaining both sides of a historical DST fold."""
    resolved: list[datetime] = []
    seen: set[datetime] = set()
    for fold in (0, 1):
        aware = local_datetime.replace(tzinfo=SEOUL, fold=fold)
        instant = aware.astimezone(UTC)
        round_trip = instant.astimezone(SEOUL)
        if round_trip.replace(tzinfo=None) != local_datetime:
            continue
        if instant not in seen:
            seen.add(instant)
            resolved.append(instant)
    return sorted(resolved)


def local_day_bounds(local_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(local_date, time.min).replace(tzinfo=SEOUL).astimezone(UTC)
    end = datetime.combine(local_date, time.max).replace(tzinfo=SEOUL).astimezone(UTC)
    return start, end
