"""Analyzers: turn raw Git facts into dashboard metrics and health insights."""

from .branch_health import branch_health_summary, classify_branch, classify_branches
from .health import (
    dashboard_insights,
    recommendations,
    repository_health,
    repository_staleness,
    working_tree_warnings,
)
from .metrics import (
    activity_metrics,
    activity_series,
    change_metrics,
    contributor_trends,
    heatmap,
    repository_comparison,
    repository_metrics,
    summarize_series,
)

__all__ = [
    "activity_metrics",
    "activity_series",
    "branch_health_summary",
    "change_metrics",
    "classify_branch",
    "classify_branches",
    "contributor_trends",
    "dashboard_insights",
    "heatmap",
    "recommendations",
    "repository_comparison",
    "repository_health",
    "repository_metrics",
    "repository_staleness",
    "summarize_series",
    "working_tree_warnings",
]
