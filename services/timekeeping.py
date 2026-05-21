"""In-game calendar and time helpers."""

MINUTES_PER_DAY = 24 * 60
DEFAULT_INGAME_MINUTE = 9 * 60

DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28
MONTHS_PER_YEAR = 13
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR
CAMPAIGN_START_YEAR = 1143
CAMPAIGN_START_MONTH = 6
CAMPAIGN_START_DAY_OF_MONTH = 12

MONTH_NAMES = [
    "Frostwane",
    "Thawmarch",
    "Seedfall",
    "Rainmoot",
    "Bloomtide",
    "Suncrest",
    "Highsun",
    "Goldleaf",
    "Harvestmere",
    "Duskwane",
    "Mistfall",
    "Deepfrost",
    "Starrest",
]

WEEKDAY_NAMES = [
    "Moonday",
    "Hearthday",
    "Bladeday",
    "Greenday",
    "Crownday",
    "Starday",
    "Solsday",
]

TIME_PHASES = [
    ("midnight", 0),
    ("late night", 180),
    ("early morning", 360),
    ("morning", 540),
    ("noon", 720),
    ("afternoon", 900),
    ("evening", 1080),
    ("night", 1260),
]
TIME_ORDER = [label for label, _start_minute in TIME_PHASES]
TIME_LABEL_START_MINUTES = {label: start_minute for label, start_minute in TIME_PHASES}


def normalize_time_label(value: str) -> str:
    """Normalize time labels to the current coarse MVP time scale."""

    if not value:
        return "morning"

    value = value.strip().lower()
    if value in TIME_ORDER:
        return value

    return "morning"


def normalize_ingame_minute(value) -> int:
    """Normalize an exact in-game minute into the current day."""

    try:
        minute = int(value)
    except (TypeError, ValueError):
        return DEFAULT_INGAME_MINUTE

    return minute % MINUTES_PER_DAY


def time_label_for_minute(minute: int) -> str:
    """Return the coarse fantasy time label for an exact minute."""

    minute = normalize_ingame_minute(minute)
    current_label = TIME_PHASES[0][0]

    for label, start_minute in TIME_PHASES:
        if minute >= start_minute:
            current_label = label
        else:
            break

    return current_label


def minute_for_time_label(label: str) -> int:
    """Return a stable representative minute for a coarse time label."""

    return TIME_LABEL_START_MINUTES.get(normalize_time_label(label), DEFAULT_INGAME_MINUTE)


def calendar_date_for_day(day) -> dict:
    """Return the fantasy calendar date for an absolute campaign day."""

    absolute_day = max(1, int(day or 1))
    campaign_start_day_of_year = (
        (CAMPAIGN_START_MONTH - 1) * DAYS_PER_MONTH
        + CAMPAIGN_START_DAY_OF_MONTH
        - 1
    )
    zero_based_day = (
        (CAMPAIGN_START_YEAR - 1) * DAYS_PER_YEAR
        + campaign_start_day_of_year
        + absolute_day
        - 1
    )
    year = zero_based_day // DAYS_PER_YEAR + 1
    day_of_year = zero_based_day % DAYS_PER_YEAR
    month_index = day_of_year // DAYS_PER_MONTH
    day_of_month = day_of_year % DAYS_PER_MONTH + 1
    weekday_index = zero_based_day % DAYS_PER_WEEK
    month_name = MONTH_NAMES[month_index]
    weekday_name = WEEKDAY_NAMES[weekday_index]

    return {
        "absolute_day": absolute_day,
        "year": year,
        "month": month_index + 1,
        "month_name": month_name,
        "day_of_month": day_of_month,
        "weekday": weekday_index + 1,
        "weekday_name": weekday_name,
        "date_label": f"{weekday_name}, {day_of_month}. {month_name}, Year {year}",
    }
