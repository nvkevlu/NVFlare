#!/usr/bin/env python3
"""Render F3 transport scenarios and rank completed sweep runs."""

import argparse
import json
import re
from pathlib import Path


PROFILES = {
    "default": {
        "streaming_chunk_size": 1024 * 1024,
        "streaming_window_size": 16 * 1024 * 1024,
        "streaming_ack_interval": 4 * 1024 * 1024,
    },
    "4m": {
        "streaming_chunk_size": 4 * 1024 * 1024,
        "streaming_window_size": 128 * 1024 * 1024,
        "streaming_ack_interval": 32 * 1024 * 1024,
    },
    "8m": {
        "streaming_chunk_size": 8 * 1024 * 1024,
        "streaming_window_size": 256 * 1024 * 1024,
        "streaming_ack_interval": 64 * 1024 * 1024,
    },
    "16m": {
        "streaming_chunk_size": 16 * 1024 * 1024,
        "streaming_window_size": 512 * 1024 * 1024,
        "streaming_ack_interval": 128 * 1024 * 1024,
    },
}

_DOWNLOAD_RE = re.compile(r"\[client\] download ref=.*?elapsed=([0-9.]+)s.*?\(([0-9,]+) bytes\)")


def render_scenario(base_path: Path, output_path: Path, profile_name: str, name: str, description: str) -> None:
    scenario = json.loads(base_path.read_text(encoding="utf-8"))
    scenario["name"] = name
    scenario["description"] = description
    scenario["federation"]["rounds"] = 1
    scenario["transport"].update(PROFILES[profile_name])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")


def _download_records(path: Path) -> list[dict]:
    records = []
    if not path.is_file():
        return records
    for match in _DOWNLOAD_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        duration_seconds = float(match.group(1))
        byte_count = int(match.group(2).replace(",", ""))
        records.append(
            {
                "duration_seconds": duration_seconds,
                "bytes": byte_count,
                "gbps": byte_count * 8 / duration_seconds / 1_000_000_000,
            }
        )
    return records


def summarize_run(profile_name: str, run_dir: Path) -> dict:
    downlinks = []
    for site in ("site-1", "site-2"):
        downlinks.extend(_download_records(run_dir / "logs" / f"service-{site}.log"))
    returns = _download_records(run_dir / "logs" / "service-server.log")
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    scenario = json.loads((run_dir / "scenario.json").read_text(encoding="utf-8"))
    valid = result.get("status") == "FINISHED:COMPLETED" and len(downlinks) == 2 and len(returns) == 2
    transfer_seconds = max((record["duration_seconds"] for record in downlinks), default=float("inf")) + max(
        (record["duration_seconds"] for record in returns), default=float("inf")
    )
    records = downlinks + returns
    return {
        "profile": profile_name,
        "run_dir": str(run_dir),
        "status": result.get("status"),
        "valid": valid,
        "transport": {
            name: scenario["transport"][name]
            for name in ("streaming_chunk_size", "streaming_window_size", "streaming_ack_interval")
        },
        "downlinks": downlinks,
        "returns": returns,
        "transfer_seconds": transfer_seconds,
        "mean_flow_gbps": sum(record["gbps"] for record in records) / len(records) if records else 0.0,
    }


def summarize_sweep(entries: list[str]) -> dict:
    runs = []
    for entry in entries:
        profile_name, separator, run_path = entry.partition("=")
        if not separator or profile_name not in PROFILES:
            raise ValueError(f"invalid run entry {entry!r}; expected PROFILE=RUN_DIR")
        runs.append(summarize_run(profile_name, Path(run_path)))
    valid_runs = [run for run in runs if run["valid"]]
    if not valid_runs:
        raise RuntimeError("no valid sweep runs were available")
    winner = min(valid_runs, key=lambda run: (run["transfer_seconds"], -run["mean_flow_gbps"]))
    default_run = next((run for run in valid_runs if run["profile"] == "default"), None)
    return {
        "winner": winner["profile"],
        "winner_transport": winner["transport"],
        "winner_transfer_seconds": winner["transfer_seconds"],
        "speedup_vs_default": (
            default_run["transfer_seconds"] / winner["transfer_seconds"] if default_run else None
        ),
        "runs": runs,
    }


def _write_markdown(summary: dict, path: Path) -> None:
    lines = [
        "# F3 Transport Sweep",
        "",
        "| Profile | Valid | Two-way critical path | Mean per-flow throughput |",
        "| --- | --- | ---: | ---: |",
    ]
    for run in summary["runs"]:
        transfer = f"{run['transfer_seconds']:.2f} s" if run["valid"] else "invalid"
        lines.append(
            f"| {run['profile']} | {run['valid']} | {transfer} | {run['mean_flow_gbps']:.3f} Gbps |"
        )
    lines.extend(
        [
            "",
            f"Winner: `{summary['winner']}`",
            f"Speedup versus default: `{summary['speedup_vs_default']:.2f}x`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--base", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--profile", choices=sorted(PROFILES), required=True)
    render.add_argument("--name", required=True)
    render.add_argument("--description", required=True)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--run", action="append", required=True)
    summarize.add_argument("--output-json", type=Path, required=True)
    summarize.add_argument("--output-markdown", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "render":
        render_scenario(args.base, args.output, args.profile, args.name, args.description)
        return 0

    summary = summarize_sweep(args.run)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(summary, args.output_markdown)
    print(summary["winner"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
