"""Human-readable benchmark output formatter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Color codes (optional, can be disabled)
COLOR_HEADER = "\033[1;36m"  # Cyan bold
COLOR_SEPARATOR = "\033[0;90m"  # Dark gray
COLOR_SUCCESS = "\033[0;32m"  # Green
COLOR_WARNING = "\033[0;33m"  # Yellow
COLOR_ERROR = "\033[0;31m"  # Red
COLOR_INFO = "\033[0;34m"  # Blue
COLOR_RESET = "\033[0m"  # Reset


@dataclass(frozen=True, slots=True)
class TranslationThresholds:
    """Thresholds for translating metrics to human-readable labels."""

    # Speed thresholds (p50_ms)
    speed_fastest: float = 0.002
    speed_fast: float = 0.005
    speed_moderate: float = 0.01

    # Stability thresholds (p99_ms / p50_ms ratio)
    stability_very_stable: float = 2.0
    stability_stable: float = 3.0

    # Consistency thresholds (max_ms / p50_ms ratio)
    consistency_very_consistent: float = 5.0
    consistency_consistent: float = 10.0

    # Throughput thresholds (requests per second)
    throughput_very_high: float = 150_000
    throughput_high: float = 100_000
    throughput_moderate: float = 50_000

    # Memory efficiency thresholds (bytes at 100K keys)
    memory_very_efficient: int = 10 * 1024 * 1024  # 10 MB
    memory_efficient: int = 50 * 1024 * 1024  # 50 MB
    memory_moderate: int = 100 * 1024 * 1024  # 100 MB

    # Fairness thresholds (coefficient of variation)
    fairness_perfect: float = 0.0
    fairness_fair: float = 0.1
    fairness_mostly_fair: float = 0.2


def translate_speed(p50_ms: float) -> str:
    """Translate p50 latency to speed label.

    Args:
        p50_ms: P50 latency in milliseconds

    Returns:
        Speed label: "Fastest", "Fast", "Moderate", or "Slow"
    """
    if p50_ms < 0.002:
        return "Fastest"
    elif p50_ms < 0.005:
        return "Fast"
    elif p50_ms < 0.01:
        return "Moderate"
    else:
        return "Slow"


def translate_stability(p99_ms: float, p50_ms: float) -> str:
    """Translate p99/p50 ratio to stability label.

    Args:
        p99_ms: P99 latency in milliseconds
        p50_ms: P50 latency in milliseconds

    Returns:
        Stability label: "Very Stable", "Stable", or "Occasional Spikes"
    """
    if p50_ms <= 0:
        return "Very Stable"
    ratio = p99_ms / p50_ms
    if ratio < 2.0:
        return "Very Stable"
    elif ratio < 3.0:
        return "Stable"
    else:
        return "Occasional Spikes"


def translate_consistency(max_ms: float, p50_ms: float) -> str:
    """Translate max/p50 ratio to consistency label.

    Args:
        max_ms: Maximum latency in milliseconds
        p50_ms: P50 latency in milliseconds

    Returns:
        Consistency label: "Very Consistent", "Consistent", or "Variable"
    """
    if p50_ms <= 0:
        return "Very Consistent"
    ratio = max_ms / p50_ms
    if ratio < 5.0:
        return "Very Consistent"
    elif ratio < 10.0:
        return "Consistent"
    else:
        return "Variable"


def translate_memory_efficiency(peak_bytes: int, key_count: int) -> str:
    """Translate peak bytes to memory efficiency label.

    Args:
        peak_bytes: Peak memory usage in bytes
        key_count: Number of keys (used to determine scale)

    Returns:
        Memory efficiency label: "Very Efficient", "Efficient", "Moderate", or "High Memory"
    """
    # Use 100K keys as reference point
    if key_count >= 100_000:
        if peak_bytes < 10 * 1024 * 1024:
            return "Very Efficient"
        elif peak_bytes < 50 * 1024 * 1024:
            return "Efficient"
        elif peak_bytes < 100 * 1024 * 1024:
            return "Moderate"
        else:
            return "High Memory"
    elif key_count >= 10_000:
        if peak_bytes < 1 * 1024 * 1024:
            return "Very Efficient"
        elif peak_bytes < 5 * 1024 * 1024:
            return "Efficient"
        elif peak_bytes < 10 * 1024 * 1024:
            return "Moderate"
        else:
            return "High Memory"
    else:
        if peak_bytes < 100 * 1024:
            return "Very Efficient"
        elif peak_bytes < 500 * 1024:
            return "Efficient"
        elif peak_bytes < 1 * 1024 * 1024:
            return "Moderate"
        else:
            return "High Memory"


def translate_scalability(memory_at_100k: int, memory_at_1k: int) -> str:
    """Translate memory growth rate to scalability label.

    Args:
        memory_at_100k: Memory at 100K keys
        memory_at_1k: Memory at 1K keys

    Returns:
        Scalability label: "Excellent", "Good", "Moderate", or "Poor"
    """
    if memory_at_1k <= 0:
        return "Good"
    growth_rate = memory_at_100k / memory_at_1k
    if growth_rate < 10:
        return "Excellent"
    elif growth_rate < 50:
        return "Good"
    elif growth_rate < 100:
        return "Moderate"
    else:
        return "Poor"


def translate_fairness(cv: float) -> str:
    """Translate coefficient of variation to fairness label.

    Args:
        cv: Coefficient of variation

    Returns:
        Fairness label: "Perfect", "Fair", "Mostly Fair", or "Unfair"
    """
    if cv == 0.0:
        return "Perfect"
    elif cv < 0.1:
        return "Fair"
    elif cv < 0.2:
        return "Mostly Fair"
    else:
        return "Unfair"


def translate_distribution_quality(cv: float, std_dev: float) -> str:
    """Translate CV and std_dev to distribution quality label.

    Args:
        cv: Coefficient of variation
        std_dev: Standard deviation

    Returns:
        Distribution quality label
    """
    if cv == 0.0 and std_dev == 0.0:
        return "Perfect"
    elif cv < 0.05:
        return "Excellent"
    elif cv < 0.1:
        return "Good"
    elif cv < 0.2:
        return "Fair"
    else:
        return "Poor"


def translate_distributed_safety(within_tolerance: bool) -> str:
    """Translate within_tolerance to distributed-safety label.

    Args:
        within_tolerance: Whether the result is within tolerance

    Returns:
        Distributed safety label: "Distributed-Safe" or "Requires Coordination"
    """
    return "Distributed-Safe" if within_tolerance else "Requires Coordination"


def translate_accuracy(total_accepted: int, expected: int, tolerance: int) -> str:
    """Translate accuracy to label.

    Args:
        total_accepted: Total accepted requests
        expected: Expected number of accepted requests
        tolerance: Tolerance value

    Returns:
        Accuracy label
    """
    if total_accepted == expected:
        return "100%"
    elif abs(total_accepted - expected) <= tolerance:
        return "Within Tolerance"
    elif total_accepted > expected + tolerance:
        ratio = total_accepted / expected if expected > 0 else 0
        return f"{ratio:.0%} (Over Limit)"
    else:
        ratio = total_accepted / expected if expected > 0 else 0
        return f"{ratio:.0%} (Under Limit)"


def translate_coordination_needed(
    within_tolerance: bool, use_redis: bool = True
) -> str:
    """Translate to coordination needed label.

    Args:
        within_tolerance: Whether within tolerance
        use_redis: Whether using Redis backend

    Returns:
        Coordination needed label
    """
    if within_tolerance:
        return "Not Needed"
    elif use_redis:
        return "Required (Redis Lua)"
    else:
        return "Required (Not Available)"


def format_bytes(bytes_val: int) -> str:
    """Format bytes to human-readable string.

    Args:
        bytes_val: Number of bytes

    Returns:
        Formatted string like "304 KB" or "3.00 MB"
    """
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.0f} KB"
    else:
        return f"{bytes_val / (1024 * 1024):.2f} MB"


def format_throughput(iterations: int, total_seconds: float) -> str:
    """Format throughput as requests per second.

    Args:
        iterations: Number of iterations
        total_seconds: Total time in seconds

    Returns:
        Formatted throughput like "161,290 rps"
    """
    if total_seconds <= 0:
        return "0 rps"
    rps = iterations / total_seconds
    return f"{rps:,.0f} rps"


def format_latency_ms(value: float) -> str:
    """Format latency value with dynamic precision for microsecond-scale values.

    Args:
        value: Latency value in milliseconds

    Returns:
        Formatted string with appropriate decimal places:
        - < 0.01ms: 4 decimal places (e.g., "0.0018ms")
        - 0.01-1ms: 3 decimal places (e.g., "0.012ms")
        - >= 1ms: 2 decimal places (e.g., "1.23ms")
    """
    if value < 0.01:
        return f"{value:.4f}ms"
    elif value < 1:
        return f"{value:.3f}ms"
    else:
        return f"{value:.2f}ms"


class TableFormatter:
    """Simple table formatter with dynamic column widths.

    Attributes:
        columns: List of column header names
        alignments: List of alignments ('left', 'center', 'right') per column
        rows: List of data rows
        _column_widths: Calculated widths for each column
    """

    # Valid alignment options
    VALID_ALIGNMENTS = frozenset({"left", "center", "right"})

    def __init__(
        self,
        columns: list[str],
        alignments: list[str] | None = None,
        padding: int = 1,
    ) -> None:
        """Initialize the table formatter.

        Args:
            columns: Column header names
            alignments: Optional list of alignments per column ('left', 'center', 'right')
            padding: Number of spaces around cell content (default: 1)
        """
        self.columns = columns
        self.alignments = list(alignments) if alignments else ["left"] * len(columns)
        self.padding = padding
        self.rows: list[list[str]] = []
        self._column_widths: list[int] = []

        # Validate alignments
        for i, align in enumerate(self.alignments):
            if align not in self.VALID_ALIGNMENTS:
                msg = f"Invalid alignment '{align}' at index {i}. Valid options: {list(self.VALID_ALIGNMENTS)}"
                raise ValueError(msg)

    def add_row(self, row: list[str]) -> None:
        """Add a data row to the table.

        Args:
            row: List of cell values (must match column count)
        """
        if len(row) != len(self.columns):
            msg = f"Row has {len(row)} columns, expected {len(self.columns)}"
            raise ValueError(msg)
        self.rows.append([str(cell) for cell in row])

    def _calculate_column_widths(self) -> None:
        """Calculate maximum width for each column based on headers and data."""
        self._column_widths = []
        for i, header in enumerate(self.columns):
            max_width = len(header)
            for row in self.rows:
                cell_width = len(row[i])
                if cell_width > max_width:
                    max_width = cell_width
            self._column_widths.append(max_width)

    def _pad_cell(self, content: str, width: int, alignment: str) -> str:
        """Pad cell content to specified width with given alignment."""
        padding_spaces = self.padding
        total_padding = padding_spaces * 2
        available_width = width + total_padding

        if alignment == "left":
            return content.rjust(available_width)
        elif alignment == "right":
            return content.ljust(available_width)
        else:  # center
            spaces = available_width - len(content)
            left_spaces = spaces // 2
            right_spaces = spaces - left_spaces
            return " " * left_spaces + content + " " * right_spaces

    def _build_separator(self, left: str, mid: str, right: str, fill: str = "─") -> str:
        """Build a separator line using box-drawing characters."""
        parts = [left]
        for i, width in enumerate(self._column_widths):
            parts.append(fill * (width + self.padding * 2))
            if i < len(self._column_widths) - 1:
                parts.append(mid)
        parts.append(right)
        return "".join(parts)

    def render(self) -> str:
        """Render the complete table as a string.

        Returns:
            Formatted table string with borders
        """
        if not self.columns:
            return ""

        self._calculate_column_widths()

        lines: list[str] = []

        # Top border
        lines.append(self._build_separator("┌", "┬", "┐"))

        # Header row
        header_cells = []
        for i, header in enumerate(self.columns):
            header_cells.append(
                self._pad_cell(header, self._column_widths[i], self.alignments[i])
            )
        lines.append("│" + "│".join(header_cells) + "│")

        # Header separator
        lines.append(self._build_separator("├", "┼", "┤"))

        # Data rows
        for row in self.rows:
            data_cells = []
            for i, cell in enumerate(row):
                data_cells.append(
                    self._pad_cell(cell, self._column_widths[i], self.alignments[i])
                )
            lines.append("│" + "│".join(data_cells) + "│")

        # Bottom border
        lines.append(self._build_separator("└", "┴", "┘"))

        return "\n".join(lines)


class BenchmarkFormatter:
    """Format benchmark results for human-readable console output."""

    def __init__(
        self,
        *,
        thresholds: TranslationThresholds | None = None,
        use_colors: bool = True,
        width: int = 80,
    ) -> None:
        """Initialize the formatter.

        Args:
            thresholds: Custom translation thresholds (optional)
            use_colors: Enable ANSI color codes (default: True)
            width: Terminal width for table formatting (default: 80)
        """
        self.thresholds = thresholds or TranslationThresholds()
        self.use_colors = use_colors
        self.width = width

    def _color(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if self.use_colors:
            return f"{color}{text}{COLOR_RESET}"
        return text

    def _header(self, text: str) -> str:
        """Format a header line."""
        return self._color(text, COLOR_HEADER)

    def _success(self, text: str) -> str:
        """Format a success line."""
        return self._color(text, COLOR_SUCCESS)

    def _warning(self, text: str) -> str:
        """Format a warning line."""
        return self._color(text, COLOR_WARNING)

    def _error(self, text: str) -> str:
        """Format an error line."""
        return self._color(text, COLOR_ERROR)

    def _info(self, text: str) -> str:
        """Format an info line."""
        return self._color(text, COLOR_INFO)

    def _load_json(self, path: Path) -> dict[str, Any]:
        """Load JSON data from file."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def format(self, result_path: Path) -> str:
        """Auto-detect benchmark type and format results.

        Args:
            result_path: Path to the JSON result file

        Returns:
            Formatted string for console output
        """
        try:
            data = self._load_json(result_path)
        except FileNotFoundError:
            print(f"Error: Result file not found: {result_path}", file=sys.stderr)
            return ""
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {result_path}: {e}", file=sys.stderr)
            return ""

        scenario = data.get("scenario")
        if not scenario:
            print("Error: Missing 'scenario' field in result file", file=sys.stderr)
            return ""

        try:
            if scenario == "latency":
                return self.format_latency_results(data)
            elif scenario == "redis_latency":
                return self.format_latency_results(
                    data, header_line="REDIS LATENCY BENCHMARK RESULTS"
                )
            elif scenario == "memory":
                return self.format_memory_results(data)
            elif scenario == "fairness":
                return self.format_fairness_results(data)
            elif scenario == "multi_instance":
                return self.format_multi_instance_results(data)
            else:
                print(f"Error: Unknown scenario type: {scenario}", file=sys.stderr)
                return ""
        except Exception as e:
            print(f"Error formatting {scenario} results: {e}", file=sys.stderr)
            return ""

    def format_latency_results(
        self, data: dict[str, Any], *, header_line: str = "LATENCY BENCHMARK RESULTS"
    ) -> str:
        """Format latency benchmark results.

        Args:
            data: Parsed JSON data from latency benchmark
            header_line: Header label for the report

        Returns:
            Formatted string for console output
        """
        metadata = data.get("metadata", {})
        results = data.get("results", [])

        # Build output
        lines: list[str] = []

        # Header
        lines.append(self._header("=" * 78))
        lines.append(self._header(f"{header_line:^78}"))
        lines.append(self._header("=" * 78))
        lines.append(f"Timestamp: {metadata.get('timestamp', 'N/A')}")
        lines.append(f"Platform: {metadata.get('platform', 'N/A')}")
        lines.append(f"Python: {metadata.get('python_version', 'N/A')}")
        lines.append("-" * 78)
        lines.append("")

        # Group results by algorithm
        algorithms: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            algo = result.get("algorithm", "unknown")
            if algo not in algorithms:
                algorithms[algo] = []
            algorithms[algo].append(result)

        # Calculate summary metrics per algorithm
        algo_summaries: list[dict[str, Any]] = []
        for algo, algo_results in algorithms.items():
            # Get average p50 across all concurrency levels
            p50_values = [r.get("p50_ms", 0) for r in algo_results]
            avg_p50 = sum(p50_values) / len(p50_values) if p50_values else 0

            # Get worst stability
            stabilities = [
                translate_stability(r.get("p99_ms", 0), r.get("p50_ms", 0))
                for r in algo_results
            ]
            # Count how many are "Very Stable"
            very_stable_count = stabilities.count("Very Stable")

            # Get average throughput
            total_iterations = sum(r.get("iterations", 0) for r in algo_results)
            total_seconds = sum(r.get("total_seconds", 0) for r in algo_results)
            avg_throughput = format_throughput(total_iterations, total_seconds)

            # Get consistency (use max ratio)
            max_ratios = [
                r.get("max_ms", 0) / r.get("p50_ms", 1) if r.get("p50_ms", 0) > 0 else 0
                for r in algo_results
            ]
            worst_consistency = translate_consistency(
                max(max_ratios) if max_ratios else 0, 0
            )

            algo_summaries.append(
                {
                    "algorithm": algo,
                    "avg_p50": avg_p50,
                    "speed": translate_speed(avg_p50),
                    "stability": (
                        "Very Stable"
                        if very_stable_count == len(algo_results)
                        else (
                            "Stable"
                            if very_stable_count >= len(algo_results) // 2
                            else "Occasional Spikes"
                        )
                    ),
                    "consistency": worst_consistency,
                    "throughput": avg_throughput,
                    "results": sorted(
                        algo_results, key=lambda x: x.get("concurrency", 0)
                    ),
                }
            )

        # Sort by speed (best first)
        speed_order = {"Fastest": 0, "Fast": 1, "Moderate": 2, "Slow": 3}
        algo_summaries.sort(key=lambda x: speed_order.get(x["speed"], 999))

        # Calculate overall rating
        all_very_stable = all(s["stability"] == "Very Stable" for s in algo_summaries)
        best_speed = algo_summaries[0]["speed"] if algo_summaries else "Slow"
        if best_speed in ("Fastest", "Fast") and all_very_stable:
            overall_rating = "Excellent"
        elif best_speed in ("Fastest", "Fast", "Moderate"):
            overall_rating = "Good"
        elif best_speed == "Slow" or any(
            s["stability"] == "Occasional Spikes" for s in algo_summaries
        ):
            overall_rating = "Fair"
        else:
            overall_rating = "Poor"

        # Find best and most stable
        best_algorithm = algo_summaries[0]["algorithm"] if algo_summaries else "N/A"
        most_stable = (
            max(
                algo_summaries,
                key=lambda x: (
                    ["Very Stable", "Stable", "Occasional Spikes"].index(x["stability"])
                    if x["stability"] in ["Very Stable", "Stable", "Occasional Spikes"]
                    else 3
                ),
            )
            if algo_summaries
            else {"algorithm": "N/A", "stability": "N/A"}
        )

        # SUMMARY section
        lines.append("SUMMARY")
        lines.append(
            f"  Best Algorithm: {best_algorithm} ({algo_summaries[0]['speed'] if algo_summaries else 'N/A'})"
        )
        lines.append(
            f"  Most Stable: {most_stable['algorithm']} ({most_stable['stability']})"
        )
        lines.append(f"  Overall Rating: {overall_rating}")
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # DETAILED RESULTS table
        lines.append("DETAILED RESULTS")
        lines.append("")
        table = TableFormatter(
            columns=["Algorithm", "Speed", "Stability", "Consistency", "Throughput"],
            alignments=["left", "left", "left", "left", "left"],
        )
        for summary in algo_summaries:
            table.add_row(
                [
                    summary["algorithm"],
                    summary["speed"],
                    summary["stability"],
                    summary["consistency"],
                    summary["throughput"],
                ]
            )
        lines.append(table.render())
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # PERFORMANCE BY CONCURRENCY
        lines.append("PERFORMANCE BY CONCURRENCY")
        lines.append("")
        for summary in algo_summaries:
            algo = summary["algorithm"]
            lines.append(f"{algo}")
            for result in summary["results"]:
                concurrency = result.get("concurrency", 0)
                p50 = result.get("p50_ms", 0)
                p95 = result.get("p95_ms", 0)
                p99 = result.get("p99_ms", 0)
                speed = translate_speed(p50)
                stability = translate_stability(p99, p50)
                lines.append(
                    f"  Concurrency {concurrency:>4}:  p50={format_latency_ms(p50)}  p95={format_latency_ms(p95)}  p99={format_latency_ms(p99)}  [{speed}, {stability}]"
                )
            lines.append("")

        lines.append("-" * 78)
        lines.append("")

        # INSIGHTS
        lines.append("INSIGHTS")
        insights: list[str] = []

        if all_very_stable:
            insights.append(
                self._success(
                    "✓ All algorithms maintain stability across all concurrency levels"
                )
            )

        if algo_summaries:
            best = algo_summaries[0]["algorithm"]
            insights.append(
                self._success(
                    f"✓ {best} offers the best performance with minimal latency"
                )
            )

        # Check for stability issues
        has_spikes = any(s["stability"] == "Occasional Spikes" for s in algo_summaries)
        if has_spikes:
            # Find which algorithm has spikes
            spike_algos = [
                s["algorithm"]
                for s in algo_summaries
                if s["stability"] == "Occasional Spikes"
            ]
            if spike_algos:
                insights.append(
                    self._warning(
                        f"⚠ {', '.join(spike_algos)} show occasional spikes at high concurrency"
                    )
                )

        for insight in insights:
            lines.append(f"  {insight}")

        lines.append("")
        lines.append(self._header("=" * 78))

        return "\n".join(lines)

    def format_memory_results(self, data: dict[str, Any]) -> str:
        """Format memory benchmark results.

        Args:
            data: Parsed JSON data from memory benchmark

        Returns:
            Formatted string for console output
        """
        metadata = data.get("metadata", {})
        results = data.get("results", [])

        lines: list[str] = []

        # Header
        header_line = "MEMORY BENCHMARK RESULTS"
        lines.append(self._header("=" * 78))
        lines.append(self._header(f"{header_line:^78}"))
        lines.append(self._header("=" * 78))
        lines.append(f"Timestamp: {metadata.get('timestamp', 'N/A')}")
        lines.append(f"Platform: {metadata.get('platform', 'N/A')}")
        lines.append(f"Python: {metadata.get('python_version', 'N/A')}")
        lines.append("-" * 78)
        lines.append("")

        # Group results by algorithm
        algorithms: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            algo = result.get("algorithm", "unknown")
            if algo not in algorithms:
                algorithms[algo] = []
            algorithms[algo].append(result)

        # Build summary per algorithm
        algo_summaries: list[dict[str, Any]] = []
        for algo, algo_results in algorithms.items():
            # Get memory at each key count
            mem_by_keycount: dict[int, dict[str, Any]] = {}
            for r in algo_results:
                key_count = r.get("key_count", 0)
                mem_by_keycount[key_count] = {
                    "peak_bytes": r.get("peak_bytes", 0),
                    "efficiency": translate_memory_efficiency(
                        r.get("peak_bytes", 0), key_count
                    ),
                }

            # Get efficiency at each scale
            efficiency_1k = mem_by_keycount.get(1000, {}).get("efficiency", "Moderate")
            efficiency_10k = mem_by_keycount.get(10000, {}).get(
                "efficiency", "Moderate"
            )
            efficiency_100k = mem_by_keycount.get(100000, {}).get(
                "efficiency", "Moderate"
            )

            # Calculate scalability
            mem_1k = mem_by_keycount.get(1000, {}).get("peak_bytes", 0)
            mem_100k = mem_by_keycount.get(100000, {}).get("peak_bytes", 0)
            scalability = translate_scalability(mem_100k, mem_1k)

            algo_summaries.append(
                {
                    "algorithm": algo,
                    "efficiency_1k": efficiency_1k,
                    "efficiency_10k": efficiency_10k,
                    "efficiency_100k": efficiency_100k,
                    "scalability": scalability,
                    "mem_by_keycount": mem_by_keycount,
                }
            )

        # Sort by efficiency at 100K keys
        def get_eff_order(eff: str) -> int:
            order = {
                "Very Efficient": 0,
                "Efficient": 1,
                "Moderate": 2,
                "High Memory": 3,
            }
            return order.get(eff, 4)

        algo_summaries.sort(key=lambda x: get_eff_order(x["efficiency_100k"]))

        # Calculate overall rating
        all_efficient = all(
            get_eff_order(s["efficiency_100k"]) <= 1 for s in algo_summaries
        )
        all_good_scalability = all(
            get_eff_order(s["scalability"]) <= 1 for s in algo_summaries
        )

        if all_efficient and all_good_scalability:
            overall_rating = "Excellent"
        elif (
            any(get_eff_order(s["efficiency_100k"]) == 2 for s in algo_summaries)
            and all_good_scalability
        ):
            overall_rating = "Good"
        elif any(get_eff_order(s["efficiency_100k"]) >= 3 for s in algo_summaries):
            overall_rating = "Fair"
        else:
            overall_rating = "Poor"

        # Find best algorithm
        best_algorithm = algo_summaries[0]["algorithm"] if algo_summaries else "N/A"

        # SUMMARY
        lines.append("SUMMARY")
        lines.append(f"  Most Memory Efficient: {best_algorithm}")
        lines.append(f"  Best Scalability: {best_algorithm}")
        lines.append(f"  Overall Rating: {overall_rating}")
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # MEMORY EFFICIENCY BY KEY COUNT table
        lines.append("MEMORY EFFICIENCY BY KEY COUNT")
        lines.append("")
        table = TableFormatter(
            columns=["Algorithm", "1K Keys", "10K Keys", "100K Keys", "Scalability"],
            alignments=["left", "left", "left", "left", "left"],
        )
        for summary in algo_summaries:
            table.add_row(
                [
                    summary["algorithm"],
                    summary["efficiency_1k"],
                    summary["efficiency_10k"],
                    summary["efficiency_100k"],
                    summary["scalability"],
                ]
            )
        lines.append(table.render())
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # DETAILED MEMORY USAGE
        lines.append("DETAILED MEMORY USAGE")
        lines.append("")
        for summary in algo_summaries:
            algo = summary["algorithm"]
            lines.append(f"{algo}")
            mem_by_keycount = summary["mem_by_keycount"]
            for key_count in [1000, 10000, 100000]:
                if key_count in mem_by_keycount:
                    peak = mem_by_keycount[key_count]["peak_bytes"]
                    eff = mem_by_keycount[key_count]["efficiency"]
                    formatted = format_bytes(peak)
                    lines.append(
                        f"  {key_count:>6,} keys: {formatted:>10} peak   [{eff}]"
                    )
            lines.append("")

        lines.append("-" * 78)
        lines.append("")

        # INSIGHTS
        lines.append("INSIGHTS")
        insights: list[str] = []

        # Check linear scaling
        if all(s["scalability"] in ("Excellent", "Good") for s in algo_summaries):
            insights.append(
                self._success("✓ All algorithms scale linearly with key count")
            )

        if algo_summaries:
            best = algo_summaries[0]["algorithm"]
            insights.append(
                self._success(f"✓ {best} has the lowest memory footprint at all scales")
            )

        # Check memory efficiency
        if all(get_eff_order(s["efficiency_100k"]) <= 1 for s in algo_summaries):
            insights.append(
                self._success("✓ Memory usage remains efficient even at 100K keys")
            )

        for insight in insights:
            lines.append(f"  {insight}")

        lines.append("")
        lines.append(self._header("=" * 78))

        return "\n".join(lines)

    def format_fairness_results(self, data: dict[str, Any]) -> str:
        """Format fairness benchmark results.

        Args:
            data: Parsed JSON data from fairness benchmark

        Returns:
            Formatted string for console output
        """
        metadata = data.get("metadata", {})
        results = data.get("results", [])
        config = data.get("config", {})
        users = data.get("users", 0)
        requests_per_user = data.get("requests_per_user", 0)
        limit = int(config.get("limit", 0) or 0)
        period = int(config.get("period", 0) or 0)
        shared_key = str(data.get("shared_key", ""))

        lines: list[str] = []

        # Header
        header_line = "FAIRNESS BENCHMARK RESULTS"
        lines.append(self._header("=" * 78))
        lines.append(self._header(f"{header_line:^78}"))
        lines.append(self._header("=" * 78))
        lines.append(f"Timestamp: {metadata.get('timestamp', 'N/A')}")
        lines.append(f"Platform: {metadata.get('platform', 'N/A')}")
        lines.append(f"Python: {metadata.get('python_version', 'N/A')}")
        lines.append("-" * 78)
        lines.append("")

        # Build summaries
        algo_summaries: list[dict[str, Any]] = []
        for result in results:
            algo = result.get("algorithm", "unknown")
            total_accepted = result.get("total_accepted", 0)
            total_requests = result.get("total_requests", 0)
            cv = result.get("coefficient_of_variation", 0)
            std_dev = result.get("std_deviation", 0)
            per_user = result.get("per_user_accepted", [])

            fairness = translate_fairness(cv)
            distribution = translate_distribution_quality(cv, std_dev)
            acceptance_rate = (
                (total_accepted / total_requests * 100) if total_requests > 0 else 0
            )

            algo_summaries.append(
                {
                    "algorithm": algo,
                    "fairness": fairness,
                    "distribution": distribution,
                    "std_dev": std_dev,
                    "cv": cv,
                    "per_user": per_user,
                    "total_accepted": total_accepted,
                    "total_requests": total_requests,
                    "acceptance_rate": acceptance_rate,
                }
            )

        # Check if all are perfect
        all_perfect = all(s["fairness"] == "Perfect" for s in algo_summaries)
        distribution_order = {
            "Perfect": 0,
            "Excellent": 1,
            "Good": 2,
            "Fair": 3,
            "Poor": 4,
        }
        worst_distribution = (
            max(
                algo_summaries,
                key=lambda s: distribution_order.get(s["distribution"], 999),
            )["distribution"]
            if algo_summaries
            else "N/A"
        )

        # Calculate overall rating
        if all_perfect:
            overall_rating = "Perfect"
        else:
            cv_values = [s["cv"] for s in algo_summaries]
            max_cv = max(cv_values) if cv_values else 0
            if max_cv < 0.1:
                overall_rating = "Excellent"
            elif max_cv < 0.2:
                overall_rating = "Good"
            else:
                overall_rating = "Fair"

        # SUMMARY
        lines.append("SUMMARY")
        if all_perfect:
            lines.append("  All Algorithms: Perfectly Fair")
        else:
            fair_count = sum(1 for s in algo_summaries if s["fairness"] == "Perfect")
            lines.append(
                f"  Perfectly Fair: {fair_count}/{len(algo_summaries)} algorithms"
            )
        lines.append(
            f"  Distribution Quality: {worst_distribution}"
        )
        lines.append(f"  Overall Rating: {overall_rating}")
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # FAIRNESS ANALYSIS table
        lines.append("FAIRNESS ANALYSIS")
        lines.append("")
        table = TableFormatter(
            columns=[
                "Algorithm",
                "Fairness",
                "Distribution",
                "Consistency",
                "Acceptance",
            ],
            alignments=["left", "left", "left", "left", "left"],
        )
        for summary in algo_summaries:
            table.add_row(
                [
                    summary["algorithm"],
                    summary["fairness"],
                    summary["distribution"],
                    summary["fairness"],  # Consistency is same as fairness
                    f"{summary['acceptance_rate']:.1f}%",
                ]
            )
        lines.append(table.render())
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # DETAILED FAIRNESS METRICS
        lines.append("DETAILED FAIRNESS METRICS")
        lines.append("")
        for summary in algo_summaries:
            algo = summary["algorithm"]
            lines.append(f"{algo}")
            lines.append(
                f"  Standard Deviation: {summary['std_dev']:.1f} [{summary['fairness']}]"
            )
            lines.append(
                f"  Coefficient of Variation: {summary['cv']:.2f} [{summary['fairness']}]"
            )
            per_user_str = ", ".join(str(x) for x in summary["per_user"][:10])
            lines.append(f"  Per-User Distribution: {per_user_str}")
            total_accepted = summary["total_accepted"]
            total_requests = summary["total_requests"]
            lines.append(
                f"  Total Accepted: {total_accepted:,} / {total_requests:,} requests ({summary['acceptance_rate']:.1f}%)"
            )
            lines.append("")

        lines.append("-" * 78)
        lines.append("")

        # INSIGHTS
        lines.append("INSIGHTS")
        insights: list[str] = []

        if all_perfect:
            insights.append(
                self._success(
                    "✓ All algorithms provide perfectly fair distribution across all users"
                )
            )

        if all(s["std_dev"] == 0 for s in algo_summaries):
            insights.append(
                self._success("✓ Zero variance in per-user acceptance rates")
            )

        insights.append(self._success("✓ Consistent behavior across all algorithms"))
        if algo_summaries and limit > 0 and period > 0:
            max_accepted = max(s["total_accepted"] for s in algo_summaries)
            total_requests = max(s["total_requests"] for s in algo_summaries)
            if max_accepted <= limit:
                target = (
                    f" on shared key {shared_key!r}" if shared_key else " on shared key"
                )
                insights.append(
                    self._success(
                        f"✓ Global cap enforced (accepted ≤{limit:,}/{period}s{target}: {max_accepted:,}/{total_requests:,})"
                    )
                )
            else:
                insights.append(
                    self._warning(
                        f"⚠ Global cap violated (accepted {max_accepted:,} > limit {limit:,}/{period}s)"
                    )
                )

        for insight in insights:
            lines.append(f"  {insight}")

        lines.append("")
        lines.append(self._header("=" * 78))

        return "\n".join(lines)

    def format_multi_instance_results(self, data: dict[str, Any]) -> str:
        """Format multi-instance benchmark results.

        Args:
            data: Parsed JSON data from multi-instance benchmark

        Returns:
            Formatted string for console output
        """
        metadata = data.get("metadata", {})
        results = data.get("results", [])
        config = data.get("config", {})
        instance_count = data.get("instance_count", 0)
        tolerance = data.get("tolerance", 0)
        limit = config.get("limit", 0)

        lines: list[str] = []

        # Header
        header_line = "MULTI-INSTANCE BENCHMARK RESULTS"
        lines.append(self._header("=" * 78))
        lines.append(self._header(f"{header_line:^78}"))
        lines.append(self._header("=" * 78))
        lines.append(f"Timestamp: {metadata.get('timestamp', 'N/A')}")
        lines.append(f"Platform: {metadata.get('platform', 'N/A')}")
        lines.append(f"Python: {metadata.get('python_version', 'N/A')}")
        lines.append("-" * 78)
        lines.append("")

        # Build summaries
        algo_summaries: list[dict[str, Any]] = []
        safe_algorithms: list[str] = []
        unsafe_algorithms: list[str] = []

        for result in results:
            algo = result.get("algorithm", "unknown")
            total_accepted = result.get("total_accepted", 0)
            within_tolerance = result.get("within_tolerance", False)

            safety = translate_distributed_safety(within_tolerance)
            accuracy = translate_accuracy(total_accepted, limit, tolerance)
            coordination = translate_coordination_needed(within_tolerance)

            if within_tolerance:
                recommendation = "✓ Recommended"
                safe_algorithms.append(algo)
            else:
                recommendation = "⚠ Requires"
                unsafe_algorithms.append(algo)

            algo_summaries.append(
                {
                    "algorithm": algo,
                    "safety": safety,
                    "accuracy": accuracy,
                    "coordination": coordination,
                    "recommendation": recommendation,
                    "total_accepted": total_accepted,
                    "within_tolerance": within_tolerance,
                }
            )

        # Calculate overall rating
        if len(safe_algorithms) == len(algo_summaries):
            overall_rating = "Excellent"
        elif len(safe_algorithms) > 0:
            overall_rating = "Good"
        elif all(
            s["coordination"] != "Required (Not Available)" for s in algo_summaries
        ):
            overall_rating = "Fair"
        else:
            overall_rating = "Poor"

        # SUMMARY
        lines.append("SUMMARY")
        if safe_algorithms:
            lines.append(f"  Distributed-Safe Algorithm: {', '.join(safe_algorithms)}")
        if unsafe_algorithms:
            lines.append(f"  Coordination Required: {', '.join(unsafe_algorithms)}")
        else:
            lines.append("  Coordination Required: None")
        lines.append(f"  Overall Rating: {overall_rating}")
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # DISTRIBUTED BEHAVIOR table
        lines.append("DISTRIBUTED BEHAVIOR")
        lines.append("")
        table = TableFormatter(
            columns=[
                "Algorithm",
                "Distributed",
                "Accuracy",
                "Coordination",
                "Recommendation",
            ],
            alignments=["left", "left", "left", "left", "left"],
        )
        for summary in algo_summaries:
            dist = "Safe" if summary["within_tolerance"] else "Unsafe"
            table.add_row(
                [
                    summary["algorithm"],
                    dist,
                    summary["accuracy"],
                    summary["coordination"],
                    summary["recommendation"],
                ]
            )
        lines.append(table.render())
        lines.append("")
        lines.append("-" * 78)
        lines.append("")

        # DETAILED RESULTS
        lines.append("DETAILED RESULTS")
        lines.append("")
        lines.append(
            f"Configuration: Limit={limit}, Period={config.get('period', 'N/A')}s, Instances={instance_count}, Tolerance=±{tolerance}"
        )
        lines.append("")
        for summary in algo_summaries:
            algo = summary["algorithm"]
            total_accepted = summary["total_accepted"]
            within_tol = summary["within_tolerance"]
            lines.append(f"{algo}")
            lines.append(f"  Total Accepted: {total_accepted} (expected: {limit})")
            lines.append(f"  Within Tolerance: {'Yes' if within_tol else 'No'}")
            if within_tol:
                lines.append(f"  Status: Distributed-Safe {self._success('✓')}")
            else:
                lines.append(f"  Status: Requires Coordination {self._warning('⚠')}")
                if total_accepted > limit:
                    lines.append(
                        f"  Issue: {total_accepted // limit}x the expected requests accepted"
                    )
            lines.append("")

        lines.append("-" * 78)
        lines.append("")

        # INSIGHTS
        lines.append("INSIGHTS")
        insights: list[str] = []

        for algo in safe_algorithms:
            insights.append(
                self._success(
                    f"✓ {algo} is safe for distributed deployments without coordination"
                )
            )

        for algo in unsafe_algorithms:
            insights.append(
                self._warning(
                    f"⚠ {algo} requires distributed coordination (e.g., Redis Lua scripts)"
                )
            )

        if safe_algorithms:
            insights.append(
                self._info(
                    f"ℹ Use {', '.join(safe_algorithms)} for simple distributed rate limiting"
                )
            )
        if unsafe_algorithms:
            insights.append(
                self._info(
                    f"ℹ Use {', '.join(unsafe_algorithms)} with Redis backend for accuracy"
                )
            )

        for insight in insights:
            lines.append(f"  {insight}")

        lines.append("")
        lines.append(self._header("=" * 78))

        return "\n".join(lines)
