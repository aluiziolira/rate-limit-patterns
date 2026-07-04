from __future__ import annotations

from benchmarks.formatter import BenchmarkFormatter


def test_fairness_formatter_reports_global_cap_enforced() -> None:
    formatter = BenchmarkFormatter(use_colors=False)

    data = {
        "scenario": "fairness",
        "metadata": {
            "timestamp": "2026-01-22T00:00:00+00:00",
            "platform": "test",
            "python_version": "3.12.1",
        },
        "config": {"limit": 100, "period": 60},
        "users": 10,
        "requests_per_user": 500,
        "concurrency": 100,
        "shared_key": "fairness:shared",
        "results": [
            {
                "algorithm": "token_bucket",
                "total_requests": 5000,
                "total_accepted": 100,
                "per_user_accepted": [100, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                "std_deviation": 30.0,
                "coefficient_of_variation": 3.0,
            },
            {
                "algorithm": "sliding_window",
                "total_requests": 5000,
                "total_accepted": 100,
                "per_user_accepted": [100, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                "std_deviation": 30.0,
                "coefficient_of_variation": 3.0,
            },
            {
                "algorithm": "leaky_bucket",
                "total_requests": 5000,
                "total_accepted": 100,
                "per_user_accepted": [100, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                "std_deviation": 30.0,
                "coefficient_of_variation": 3.0,
            },
        ],
    }

    output = formatter.format_fairness_results(data)

    assert "Poor" in output
    assert "Global cap enforced" in output
    assert "requests per user" not in output
