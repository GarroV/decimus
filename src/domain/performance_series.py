"""Calendar-aligned daily series from recorded observations, including explicit gaps."""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from .performance import CORE_METRICS, Observation, Window, observation_json


def daily_json(
    country: str, windows: Mapping[str, Window], rows: Sequence[Observation]
) -> dict[str, list[dict[str, Any]]]:
    lookup = {
        (row.period.start, row.metric): row
        for row in rows
        if row.country == country
        and row.subject_id == country
        and row.period.start == row.period.end
    }
    result = {}
    for key, window in windows.items():
        points = []
        day = window.start
        while day <= window.end:
            points.append(
                {
                    "date": day.isoformat(),
                    "metrics": {
                        metric: observation_json(lookup.get((day, metric)))
                        for metric in CORE_METRICS
                    },
                }
            )
            day += timedelta(days=1)
        result[key] = points
    return result
