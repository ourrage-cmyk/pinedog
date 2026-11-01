"""Long-term usual pattern for one dog, kept in Home Assistant.

Short-term usual comes from activity.compute_baseline over the last 14 days. This module
is the long-term one. It never resets. It keeps one exponentially weighted average per
hour of the week (168 buckets), so memory stays bounded however long the dog is tracked.

Each hour's value is learned in log space, which keeps one busy hour from dominating.
Only hours with enough worn time are learned, so a collar left on the charger teaches
nothing. Pure logic, no Home Assistant imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

HOURS_PER_WEEK = 168
HALF_LIFE_WEEKS = 8.0  # an hour learned eight weeks ago counts half as much as this week
ALPHA = 1.0 - 0.5 ** (1.0 / HALF_LIFE_WEEKS)
MIN_WORN_S_PER_HOUR = 30 * 60  # an hour needs this much wear to teach or compare
MIN_HOURS_FOR_LEARNED_DAY = 6  # worn hours in one day before that day counts as learned
MIN_LEARNED_DAYS = 7  # below this, no long-term comparison is shown


@dataclass
class LongTerm:
    mean: list[float] = field(default_factory=lambda: [0.0] * HOURS_PER_WEEK)  # log1p of hourly value
    weight: list[float] = field(default_factory=lambda: [0.0] * HOURS_PER_WEEK)
    days_learned: int = 0
    # The day in progress: {"date": key, "v": {hour: value}, "w": {hour: worn seconds}}.
    # Learning happens only when the day ends, so today never teaches itself.
    today: dict[str, Any] = field(default_factory=dict)

    def observe(self, local: datetime, value: float, worn_s: float) -> None:
        """Add activity and worn time at a local time. Times must not go backwards by day."""
        dk, h = local.date().isoformat(), str(local.hour)
        if not self.today:
            self.today = {"date": dk, "v": {}, "w": {}}
        if dk < self.today["date"]:
            return  # a day already learned; late data for it is not re-learned
        if dk > self.today["date"]:
            self._learn_day(self.today)
            self.today = {"date": dk, "v": {}, "w": {}}
        self.today["v"][h] = self.today["v"].get(h, 0.0) + value
        self.today["w"][h] = self.today["w"].get(h, 0.0) + worn_s

    def _learn_day(self, day: dict[str, Any]) -> None:
        """Fold a finished day into the hour-of-week buckets. Unworn hours teach nothing."""
        d = date.fromisoformat(day["date"])
        worn_hours = 0
        for h, worn in day["w"].items():
            if worn < MIN_WORN_S_PER_HOUR:
                continue
            worn_hours += 1
            bucket = d.weekday() * 24 + int(h)
            x = math.log1p(max(day["v"].get(h, 0.0), 0.0))
            if self.weight[bucket] == 0.0:
                self.mean[bucket] = x
            else:
                self.mean[bucket] += ALPHA * (x - self.mean[bucket])
            self.weight[bucket] += 1.0
        if worn_hours >= MIN_HOURS_FOR_LEARNED_DAY:
            self.days_learned += 1

    def comparison(self, local: datetime) -> float | None:
        """Today so far as a percent of the long-term usual at the same hours.

        Only hours that were worn today and have a learned bucket are compared.
        Returns None until MIN_LEARNED_DAYS days have been learned.
        """
        if self.days_learned < MIN_LEARNED_DAYS:
            return None
        day = self.today
        if not day or day.get("date") != local.date().isoformat():
            return None
        actual = expected = 0.0
        matched = 0
        for h in range(local.hour + 1):
            key = str(h)
            if day["w"].get(key, 0.0) < MIN_WORN_S_PER_HOUR:
                continue
            bucket = local.weekday() * 24 + h
            if self.weight[bucket] < 1.0:
                continue
            actual += day["v"].get(key, 0.0)
            expected += math.expm1(self.mean[bucket])
            matched += 1
        if matched == 0 or expected <= 0:
            return None
        return round(100.0 * actual / expected, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "weight": self.weight,
            "days_learned": self.days_learned,
            "today": self.today,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LongTerm:
        if not data:
            return cls()
        mean = list(data.get("mean", []))
        weight = list(data.get("weight", []))
        if len(mean) != HOURS_PER_WEEK or len(weight) != HOURS_PER_WEEK:
            return cls()  # corrupt shape: start over rather than mis-index buckets
        return cls(
            mean=mean,
            weight=weight,
            days_learned=int(data.get("days_learned", 0)),
            today=dict(data.get("today", {})),
        )
