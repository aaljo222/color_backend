"""Deterministic Four Pillars and MaC color calculation engine."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
from importlib.metadata import version
from math import cos, pi

from .calendar import (
    SEOUL,
    attach_hour_pillar,
    day_pillar,
    local_day_bounds,
    lunar_to_solar,
    pillars_at_instant,
    resolve_local_time,
)
from .constants import (
    BALANCE_COLORS,
    BALANCE_COLOR_SOLUTIONS,
    BALANCE_TIE_ORDER,
    BRANCHES,
    BRANCH_MAIN_STEM,
    DAY_STEM_DETAILS,
    ENGINE_VERSION,
    ELEMENT_THEMES,
    ELEMENT_WATCH,
    FORTUNE_SCORE_MAX,
    FORTUNE_SCORE_MIN,
    FREE_DESCRIPTIONS,
    PATTERN_FAMILIES,
    REPORT_VERSION,
    SIX_CLASH_PAIRS,
    SIX_HARMONY_PAIRS,
    STEMS,
    STEM_META,
    SUPPORTED_END_YEAR,
    SUPPORTED_START_YEAR,
    TEN_GOD_COLORS,
    TEN_GOD_DETAILS,
    TEN_GOD_THEMES,
    TIMEZONE_NAME,
    UNIQUE_COLORS,
)


class AstralInputError(ValueError):
    """Safe validation error that can be shown to the user."""


def _parse_date_parts(raw: object) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in str(raw).split("-"))
        if len(parts) != 3:
            raise ValueError
        year, month, day = parts
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError
        return year, month, day
    except (TypeError, ValueError) as exc:
        raise AstralInputError("생년월일을 확인해 주세요.") from exc


def _normalize_input(data: dict) -> dict:
    calendar_type = str(data.get("calendar_type", "solar")).lower()
    if calendar_type not in {"solar", "lunar"}:
        raise AstralInputError("양력 또는 음력을 선택해 주세요.")

    input_year, input_month, input_day = _parse_date_parts(data.get("birth_date", ""))
    input_date_iso = f"{input_year:04d}-{input_month:02d}-{input_day:02d}"
    if not SUPPORTED_START_YEAR <= input_year <= SUPPORTED_END_YEAR:
        raise AstralInputError(
            f"첫 버전은 {SUPPORTED_START_YEAR}년부터 {SUPPORTED_END_YEAR}년까지 지원합니다."
        )

    # Korea uses one civil time zone. The city is collected as the user's
    # recorded birthplace, but is not used as a true-solar-time correction.
    # Accept any Korean city/county instead of maintaining an incomplete list.
    city = " ".join(str(data.get("birth_city", "")).split())
    if not city:
        raise AstralInputError("대한민국 내 출생 시·군을 입력해 주세요.")
    if len(city) > 40:
        raise AstralInputError("출생 지역은 40자 이내로 입력해 주세요.")

    gender = str(data.get("gender", "")).strip().lower()
    if gender not in {"male", "female"}:
        raise AstralInputError("성별을 선택해 주세요.")

    time_unknown = bool(data.get("time_unknown", False))
    hour = minute = None
    if not time_unknown:
        raw_time = str(data.get("birth_time", ""))
        try:
            parsed_time = datetime.strptime(raw_time, "%H:%M").time()
        except ValueError as exc:
            raise AstralInputError("출생 시각을 시와 분까지 입력해 주세요.") from exc
        hour, minute = parsed_time.hour, parsed_time.minute

    is_leap_month = bool(data.get("is_leap_month", False)) if calendar_type == "lunar" else False
    if calendar_type == "lunar":
        try:
            solar_date = lunar_to_solar(
                input_year, input_month, input_day, is_leap_month
            )
        except ValueError as exc:
            raise AstralInputError(str(exc)) from exc
    else:
        try:
            solar_date = date(input_year, input_month, input_day)
        except ValueError as exc:
            raise AstralInputError("존재하지 않는 양력 날짜입니다.") from exc

    if not SUPPORTED_START_YEAR <= solar_date.year <= SUPPORTED_END_YEAR:
        raise AstralInputError("변환된 양력 날짜가 현재 지원 범위를 벗어납니다.")

    return {
        "calendar_type": calendar_type,
        "input_date": input_date_iso,
        "solar_date": solar_date,
        "is_leap_month": is_leap_month,
        "birth_city": city,
        "gender": gender,
        "time_unknown": time_unknown,
        "hour": hour,
        "minute": minute,
    }


def ten_god(day_stem: str, other_stem: str) -> str:
    day_element, day_polarity = STEM_META[day_stem]
    other_element, other_polarity = STEM_META[other_stem]
    same_polarity = day_polarity == other_polarity
    produces = {"목": "화", "화": "토", "토": "금", "금": "수", "수": "목"}
    controls = {"목": "토", "화": "금", "토": "수", "금": "목", "수": "화"}

    if other_element == day_element:
        return "비견" if same_polarity else "겁재"
    if produces[day_element] == other_element:
        return "식신" if same_polarity else "상관"
    if controls[day_element] == other_element:
        return "편재" if same_polarity else "정재"
    if controls[other_element] == day_element:
        return "편관" if same_polarity else "정관"
    return "편인" if same_polarity else "정인"


def _talent_topic(pillars: dict) -> str:
    day_stem = pillars["day"]["stem"]
    positions = [("month", 2), ("year", 1)]
    if "hour" in pillars:
        positions.append(("hour", 1))
    scored = Counter()
    position_topics: dict[str, str] = {}
    for position, weight in positions:
        topic = ten_god(day_stem, pillars[position]["stem"])
        scored[topic] += weight
        position_topics[position] = topic
    best_score = max(scored.values())
    tied = {topic for topic, score in scored.items() if score == best_score}
    for position in ("month", "hour", "year"):
        topic = position_topics.get(position)
        if topic in tied:
            return topic
    raise RuntimeError("재능색을 선택할 수 없습니다.")


def _balance_element(pillars: dict) -> tuple[str, dict[str, int]]:
    counts = Counter({element: 0 for element in BALANCE_TIE_ORDER})
    for position in ("year", "month", "day", "hour"):
        if position not in pillars:
            continue
        stem = pillars[position]["stem"]
        branch_main_stem = BRANCH_MAIN_STEM[pillars[position]["branch"]]
        counts[STEM_META[stem][0]] += 1
        counts[STEM_META[branch_main_stem][0]] += 1
    minimum = min(counts.values())
    selected = next(element for element in BALANCE_TIE_ORDER if counts[element] == minimum)
    return selected, dict(counts)


def _colors_for_pillars(pillars: dict) -> dict:
    day_stem = pillars["day"]["stem"]
    talent_topic = _talent_topic(pillars)
    relationship_topic = ten_god(day_stem, BRANCH_MAIN_STEM[pillars["day"]["branch"]])
    balance_element, composition = _balance_element(pillars)
    return {
        "unique": {"basis": day_stem, **UNIQUE_COLORS[day_stem]},
        "talent": {"basis": talent_topic, **TEN_GOD_COLORS[talent_topic]},
        "relationship": {"basis": relationship_topic, **TEN_GOD_COLORS[relationship_topic]},
        "balance": {"basis": balance_element, **BALANCE_COLORS[balance_element]},
        "visual_composition": composition,
        "visual_slot_count": 8 if "hour" in pillars else 6,
    }


def _pillar_signature(pillars: dict) -> tuple:
    return tuple(
        (position, pillars[position]["stem"], pillars[position]["branch"])
        for position in ("year", "month", "day", "hour")
        if position in pillars
    )


def _candidate(label: str, instant, solar_date: date, hour: int | None) -> dict:
    pillars = pillars_at_instant(instant, solar_date)
    if hour is not None:
        pillars = attach_hour_pillar(pillars, hour)
    return {
        "label": label,
        "instant_utc": instant.isoformat(),
        "local_time": instant.astimezone(SEOUL).isoformat(),
        "pillars": pillars,
    }


def _calculate_candidates(normalized: dict) -> tuple[list[dict], list[str]]:
    solar_date = normalized["solar_date"]
    notices: list[str] = []

    if normalized["time_unknown"]:
        start, end = local_day_bounds(solar_date)
        candidates = [
            _candidate("해당 날짜의 시작 기준", start, solar_date, None),
            _candidate("해당 날짜의 끝 기준", end, solar_date, None),
        ]
        notices.append("출생시간을 몰라 시주는 만들지 않았습니다.")
    else:
        local_datetime = datetime(
            solar_date.year,
            solar_date.month,
            solar_date.day,
            normalized["hour"],
            normalized["minute"],
        )
        instants = resolve_local_time(local_datetime)
        if not instants:
            raise AstralInputError(
                "당시 표준시 변경으로 존재하지 않았던 시각입니다. 출생 기록을 확인해 주세요."
            )
        candidates = [
            _candidate(
                "입력 시각 기준" if len(instants) == 1 else f"당시 시각 후보 {index + 1}",
                instant,
                solar_date,
                normalized["hour"],
            )
            for index, instant in enumerate(instants)
        ]
        if len(instants) > 1:
            notices.append("서머타임 종료로 같은 시각이 두 번 존재하여 두 후보를 계산했습니다.")

        # Birth input has minute precision. Keep both sides if a solar term falls inside it.
        end_local = local_datetime + timedelta(seconds=59, microseconds=999999)
        end_instants = resolve_local_time(end_local)
        for instant in end_instants:
            candidate = _candidate("입력한 분의 끝 기준", instant, solar_date, normalized["hour"])
            if all(
                _pillar_signature(existing["pillars"]) != _pillar_signature(candidate["pillars"])
                for existing in candidates
            ):
                candidates.append(candidate)
                notices.append("입력한 1분 안에 절입 경계가 있어 두 후보를 표시합니다.")

        if normalized["hour"] in {23, 0}:
            notices.append(
                "23:00~01:00는 자시이며, 현재 초안은 23시대 시주 천간도 출생일 일간으로 계산합니다."
            )

    unique_candidates: list[dict] = []
    seen: set[tuple] = set()
    for candidate in candidates:
        signature = _pillar_signature(candidate["pillars"])
        if signature not in seen:
            seen.add(signature)
            unique_candidates.append(candidate)
    return unique_candidates, notices


def _display_pillars(pillars: dict) -> dict:
    return {
        position: f"{pillars[position]['stem']}{pillars[position]['branch']}"
        for position in ("year", "month", "day", "hour")
        if position in pillars
    }


def calculate_astral_profile(data: dict) -> dict:
    normalized = _normalize_input(data)
    candidates, notices = _calculate_candidates(normalized)
    primary = candidates[0]
    colors = _colors_for_pillars(primary["pillars"])
    day_stem = primary["pillars"]["day"]["stem"]

    boundary_candidates = []
    if len(candidates) > 1:
        boundary_candidates = [
            {"label": item["label"], "pillars": _display_pillars(item["pillars"])}
            for item in candidates
        ]

    return {
        "status": "success",
        "service": "Astral Color",
        "engine_version": ENGINE_VERSION,
        "free_result": {
            "day_master": day_stem,
            "day_pillar": _display_pillars(primary["pillars"])["day"],
            "color": deepcopy(colors["unique"]),
            "description": FREE_DESCRIPTIONS[day_stem],
        },
        "calculation_basis": {
            "input_calendar": normalized["calendar_type"],
            "input_date": normalized["input_date"],
            "solar_date": normalized["solar_date"].isoformat(),
            "leap_month": normalized["is_leap_month"],
            "birth_city": normalized["birth_city"],
            "gender": normalized["gender"],
            "timezone": TIMEZONE_NAME,
            "resolved_local_time": primary["local_time"],
            "time_unknown": normalized["time_unknown"],
            "calendar_data": "KARI-aligned Korean lunar calendar table",
            "solar_term_engine": f"astronomy-engine {version('astronomy-engine')}",
            "timezone_data": f"tzdata {version('tzdata')}",
        },
        "notices": notices,
        "boundary_candidates": boundary_candidates,
        "disclaimer": (
            "Astral Color는 전통 명리 계산 원리를 바탕으로 만든 MaC의 콘텐츠입니다. "
            "성격이나 미래를 확정하거나 의료·투자 판단을 대신하지 않습니다."
        ),
    }


def _basic_reading(pillars: dict, colors: dict) -> list[dict]:
    day_stem = pillars["day"]["stem"]
    month_main_stem = BRANCH_MAIN_STEM[pillars["month"]["branch"]]
    month_element = STEM_META[month_main_stem][0]
    month_theme = ELEMENT_THEMES[month_element]
    talent_topic = colors["talent"]["basis"]
    relationship_topic = colors["relationship"]["basis"]
    talent_name, talent_check = TEN_GOD_THEMES[talent_topic]
    relationship_name, relationship_check = TEN_GOD_THEMES[relationship_topic]
    day_strength, day_watch = DAY_STEM_DETAILS[day_stem]
    talent_strength, talent_watch = TEN_GOD_DETAILS[talent_topic]
    relationship_strength, relationship_watch = TEN_GOD_DETAILS[relationship_topic]

    vote_parts = []
    for position, weight, label in (("month", 2, "월간"), ("hour", 1, "시간"), ("year", 1, "연간")):
        if position not in pillars:
            continue
        stem = pillars[position]["stem"]
        topic = ten_god(day_stem, stem)
        vote_parts.append(f"{label} {stem}·{topic} {weight}표")

    composition = colors["visual_composition"]
    composition_text = " · ".join(f"{element} {composition[element]}" for element in BALANCE_TIE_ORDER)
    balance_element = colors["balance"]["basis"]

    return [
        {
            "key": "day_master",
            "title": "나를 보는 기준 · 일간",
            "evidence": f"출생일의 일간은 {day_stem}으로 계산되었습니다.",
            "possibility": FREE_DESCRIPTIONS[day_stem].split(". ")[1] + ".",
            "strength": day_strength,
            "watch": day_watch,
            "action": FREE_DESCRIPTIONS[day_stem].split(". ")[-1],
            "color_role": "고유색",
        },
        {
            "key": "month_command",
            "title": "태어난 계절의 조건 · 월령",
            "evidence": f"월지 {pillars['month']['branch']}의 본기는 {month_main_stem}이며 {month_element}의 조건으로 읽습니다.",
            "possibility": f"{month_theme['condition']}이 생활의 배경으로 나타날 가능성을 살펴볼 수 있습니다.",
            "strength": f"{month_theme['condition']}을 일상의 리듬으로 활용할 수 있습니다.",
            "watch": ELEMENT_WATCH[month_element],
            "action": month_theme["action"],
            "color_role": "균형색",
        },
        {
            "key": "talent",
            "title": f"일과 활동의 방식 · {talent_topic}",
            "evidence": f"{' / '.join(vote_parts)}로 계산되어 {talent_topic}({talent_name})이 재능 주제로 선택되었습니다.",
            "possibility": talent_strength,
            "strength": "반복해서 쓰기 쉬운 방식이므로 일·공부·프로젝트의 시작점으로 활용할 수 있습니다.",
            "watch": talent_watch,
            "action": talent_check,
            "color_role": "재능색",
        },
        {
            "key": "relationship",
            "title": f"가까운 관계의 방식 · {relationship_topic}",
            "evidence": f"일지 {pillars['day']['branch']}의 본기와 일간의 관계는 {relationship_topic}({relationship_name})입니다.",
            "possibility": relationship_strength,
            "strength": "친밀한 관계에서 반복될 수 있는 반응을 관찰하는 기준으로 사용할 수 있습니다.",
            "watch": relationship_watch,
            "action": relationship_check,
            "color_role": "관계색",
        },
        {
            "key": "color_balance",
            "title": f"이미지 균형의 방향 · {balance_element}",
            "evidence": f"천간과 지지 본기를 한 칸씩 센 구성은 {composition_text}이며, 가장 적은 항목 중 규칙 순서에 따라 {balance_element}을 선택했습니다.",
            "possibility": "이 값은 사주의 강약이나 용신이 아니라 패턴과 화면의 색 면적을 정하기 위한 시각화 기준입니다.",
            "strength": f"{colors['balance']['name']}을 넓은 배경 면에 두면 네 가지 색의 대비를 부드럽게 연결할 수 있습니다.",
            "watch": "행운을 높이거나 부족한 운을 보충하는 색으로 단정하지 않습니다.",
            "action": "균형색은 배경에, 고유색·재능색·관계색은 작은 포인트에 사용해 보세요.",
            "color_role": "균형색",
        },
    ]


def _report_overview(pillars: dict, colors: dict) -> dict:
    day_stem = pillars["day"]["stem"]
    month_main_stem = BRANCH_MAIN_STEM[pillars["month"]["branch"]]
    month_element = STEM_META[month_main_stem][0]
    talent_topic = colors["talent"]["basis"]
    relationship_topic = colors["relationship"]["basis"]
    talent_name = TEN_GOD_THEMES[talent_topic][0]
    relationship_name = TEN_GOD_THEMES[relationship_topic][0]
    return {
        "headline": f"{UNIQUE_COLORS[day_stem]['name']}을 중심으로 읽는 {talent_name}의 흐름",
        "summary": (
            f"일간 {day_stem}을 중심에 두고, 월령의 {month_element} 조건을 생활의 배경으로 봅니다. "
            f"활동에서는 {talent_topic}({talent_name}), 가까운 관계에서는 "
            f"{relationship_topic}({relationship_name})의 주제를 함께 살펴봅니다."
        ),
        "keywords": [
            DAY_STEM_DETAILS[day_stem][0],
            ELEMENT_THEMES[month_element]["condition"],
            f"{talent_topic} · {talent_name}",
            f"{relationship_topic} · {relationship_name}",
        ],
    }


def _element_profile(colors: dict) -> dict:
    composition = colors["visual_composition"]
    maximum = max(composition.values())
    minimum = min(composition.values())
    dominant = [element for element in BALANCE_TIE_ORDER if composition[element] == maximum]
    least = [element for element in BALANCE_TIE_ORDER if composition[element] == minimum]
    balance_element = colors["balance"]["basis"]
    solution = deepcopy(BALANCE_COLOR_SOLUTIONS[balance_element])
    solution.update({
        "element": balance_element,
        "color_name": colors["balance"]["name"],
        "hex": colors["balance"]["hex"],
        "context": (
            f"이미지용 {colors['visual_slot_count']}칸 중 {balance_element}은 "
            f"{composition[balance_element]}칸으로 나타났습니다."
        ),
    })
    return {
        "counts": deepcopy(composition),
        "dominant": dominant,
        "least": least,
        "balance_element": balance_element,
        "slot_count": colors["visual_slot_count"],
        "element_colors": {element: BALANCE_COLORS[element]["hex"] for element in BALANCE_TIE_ORDER},
        "color_solution": solution,
        "note": "천간 1칸과 지지 본기 1칸을 합산한 이미지용 구성입니다. 적게 나타난 항목은 색채 활용 제안에만 쓰며 강약·용신·행운 판단에 사용하지 않습니다.",
    }


def _color_guide(role: str, color: dict) -> dict:
    if role == "고유색":
        return {"use": "나의 기준을 다시 확인하고 싶은 날, 가장 작은 개인 소품이나 화면의 중심 포인트", "avoid": "고유색이 성격이나 운명을 확정한다고 설명하지 않습니다."}
    if role == "재능색":
        return {"use": "일·공부·프로젝트를 시작할 때 노트, 폴더, 작업 도구의 포인트", "avoid": "능력의 우열이 아니라 자주 꺼내 쓰는 활동 주제로 봅니다."}
    if role == "관계색":
        return {"use": "대화와 만남이 있는 날 카드, 스카프, 메시지 배경처럼 시야에 들어오는 작은 면", "avoid": "상대와의 궁합이나 관계 결과를 보장하는 색이 아닙니다."}
    return {"use": f"{color['basis']}의 시각적 면적이 적을 때 배경, 패브릭, 잠금화면처럼 넓은 면", "avoid": "용신색이나 운을 개선하는 색으로 설명하지 않습니다."}


def _today_fortune(pillars: dict, colors: dict, fortune_date: date) -> dict:
    today_stem, today_branch = day_pillar(fortune_date)
    day_stem = pillars["day"]["stem"]
    talent_topic = colors["talent"]["basis"]
    relationship_topic = colors["relationship"]["basis"]
    today_stem_topic = ten_god(day_stem, today_stem)
    today_branch_topic = ten_god(day_stem, BRANCH_MAIN_STEM[today_branch])
    components = {
        "base": 72,
        "cycle_rhythm": 0,
        "element_familiarity": 0,
        "talent_match": 0,
        "relationship_match": 0,
        "branch_relation": 0,
    }

    def sexagenary_index(stem: str, branch: str) -> int:
        return next(
            index for index in range(60)
            if STEMS[index % 10] == stem and BRANCHES[index % 12] == branch
        )

    birth_index = sexagenary_index(day_stem, pillars["day"]["branch"])
    today_index = sexagenary_index(today_stem, today_branch)
    forward_distance = (today_index - birth_index) % 60
    components["cycle_rhythm"] = round(10 * cos(2 * pi * forward_distance / 60))

    today_elements = (
        STEM_META[today_stem][0],
        STEM_META[BRANCH_MAIN_STEM[today_branch]][0],
    )
    observed_elements = sum(colors["visual_composition"][element] for element in today_elements)
    expected_elements = colors["visual_slot_count"] * len(today_elements) / 5
    components["element_familiarity"] = max(
        -5,
        min(5, round((observed_elements - expected_elements) * 2)),
    )

    if today_stem_topic == talent_topic:
        components["talent_match"] = 8
    if today_branch_topic == relationship_topic:
        components["relationship_match"] = 6

    birth_day_branch = pillars["day"]["branch"]
    relation_label = "특별한 합·충 없음"
    pair = frozenset((today_branch, birth_day_branch))
    if today_branch == birth_day_branch:
        components["branch_relation"] = 4
        relation_label = "출생 일지와 동일"
    elif pair in SIX_HARMONY_PAIRS:
        components["branch_relation"] = 6
        relation_label = "출생 일지와 육합"
    elif pair in SIX_CLASH_PAIRS:
        components["branch_relation"] = -6
        relation_label = "출생 일지와 육충"

    raw_score = sum(components.values())
    score = min(FORTUNE_SCORE_MAX, max(FORTUNE_SCORE_MIN, raw_score))
    theme, check = TEN_GOD_THEMES[today_stem_topic]
    today_color = {"basis": today_stem_topic, **TEN_GOD_COLORS[today_stem_topic]}
    match_sentence = (
        "평소의 재능 주제와 오늘의 활동 주제가 겹칩니다."
        if components["talent_match"]
        else "평소와 다른 방식으로 접근할 여지가 있습니다."
    )

    return {
        "date_kst": fortune_date.isoformat(),
        "score": score,
        "score_components": components,
        "score_policy": "100점 만점 MaC 콘텐츠 규칙 적용(가능 범위 45~100)",
        "theme": theme,
        "reading": f"오늘 천간의 십신은 {today_stem_topic}입니다. {match_sentence} {relation_label}은 좋고 나쁨보다 오늘의 관계 리듬을 확인하는 참고 지표입니다.",
        "recommended_action": ELEMENT_THEMES[STEM_META[today_stem][0]]["action"],
        "check_point": check,
        "today_color": today_color,
        "notice": "60일 순환 거리와 이미지용 오행 구성을 포함한 MaC 콘텐츠 지표이며 미래를 확정하지 않습니다.",
    }


def calculate_paid_report(data: dict, fortune_date: date | None = None) -> dict:
    """Build the deterministic paid report. Payment authorization is handled elsewhere."""
    normalized = _normalize_input(data)
    candidates, notices = _calculate_candidates(normalized)
    primary = candidates[0]
    pillars = primary["pillars"]
    colors = _colors_for_pillars(pillars)
    target_date = fortune_date or datetime.now(SEOUL).date()
    seed_source = "|".join(
        (
            ENGINE_VERSION,
            REPORT_VERSION,
            repr(_pillar_signature(pillars)),
        )
    )
    pattern_seed = sha256(seed_source.encode("utf-8")).hexdigest()[:16]

    ordered_colors = []
    for role, key in (("고유색", "unique"), ("재능색", "talent"), ("관계색", "relationship"), ("균형색", "balance")):
        color = {"role": role, **deepcopy(colors[key])}
        color["guide"] = _color_guide(role, color)
        ordered_colors.append(color)
    pattern_family = deepcopy(PATTERN_FAMILIES[int(pattern_seed[:8], 16) % len(PATTERN_FAMILIES)])
    return {
        "status": "success",
        "service": "Astral Color Paid Report",
        "engine_version": ENGINE_VERSION,
        "report_version": REPORT_VERSION,
        "profile": {
            "gender": normalized["gender"],
            "birth_city": normalized["birth_city"],
            "solar_date": normalized["solar_date"].isoformat(),
            "time_unknown": normalized["time_unknown"],
        },
        "pillars": _display_pillars(pillars),
        "overview": _report_overview(pillars, colors),
        "reading": _basic_reading(pillars, colors),
        "colors": ordered_colors,
        "visual_composition": colors["visual_composition"],
        "visual_slot_count": colors["visual_slot_count"],
        "element_profile": _element_profile(colors),
        "pattern_seed": pattern_seed,
        "pattern_family": pattern_family,
        "today_fortune": _today_fortune(pillars, colors, target_date),
        "notices": notices,
        "boundary_candidates": [
            {"label": item["label"], "pillars": _display_pillars(item["pillars"])}
            for item in candidates
        ] if len(candidates) > 1 else [],
        "disclaimer": (
            "이 보고서는 전통 명리 계산과 MaC 자체 색상 규칙으로 만든 콘텐츠입니다. "
            "용신·기신·격국·대운을 확정하지 않으며 의료·수명·임신·투자 결과를 예측하지 않습니다."
        ),
    }
