from __future__ import annotations

import logging
from datetime import date
from typing import Any

import yaml

from family_newsletter.app.config import resolve_project_path


logger = logging.getLogger(__name__)


def _load_chores_yaml(path: str) -> dict[str, Any]:
    chores_path = resolve_project_path(path)
    if not chores_path.exists():
        logger.warning(
            "CHORES FILE NOT FOUND: %s (requested %r). Chores will render as a "
            "placeholder. Check chores.file_path in the config.",
            chores_path,
            path,
        )
        return {}
    with chores_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in chores file: {chores_path}")
    return loaded


def _group_by_id(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any]:
    for group in groups:
        if group.get("id") == group_id:
            return group
    return {}


def _task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": task.get("name", ""),
        "theme": task.get("theme"),
        "pick_one": bool(task.get("pick_one")),
    }


def _empty_result(status: str) -> dict[str, Any]:
    return {"status": status, "today": [], "this_month": [], "this_quarter": []}


def fetch_chores(config: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    data_source = config.get("data_source", "sample")
    file_path = config.get("file_path", "")

    if data_source != "file" or not file_path:
        return _empty_result("placeholder")

    try:
        raw = _load_chores_yaml(file_path)
    except (yaml.YAMLError, ValueError):
        return _empty_result("failed")

    groups = raw.get("cadence_groups", [])
    if not groups:
        return _empty_result("empty")

    run_date = today or date.today()
    weekday_name = run_date.strftime("%A")

    daily_group = _group_by_id(groups, "daily")
    weekly_group = _group_by_id(groups, "weekly")
    monthly_group = _group_by_id(groups, "monthly")
    quarterly_group = _group_by_id(groups, "quarterly")

    today_tasks = [_task(task) for task in daily_group.get("tasks", [])]
    today_tasks += [
        _task(task)
        for task in weekly_group.get("tasks", [])
        if task.get("day_of_week") == weekday_name
    ]

    month_tasks = [_task(task) for task in monthly_group.get("tasks", [])]
    quarter_tasks = [_task(task) for task in quarterly_group.get("tasks", [])]

    return {
        "status": "ok",
        "weekday": weekday_name,
        "today": today_tasks,
        "this_month": month_tasks,
        "this_quarter": quarter_tasks,
    }
