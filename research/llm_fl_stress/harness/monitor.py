# Copyright (c) 2026, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Process-tree, cgroup, and GPU telemetry sampling."""

import argparse
import csv
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import psutil


_PROCESS_FIELDS = [
    "host",
    "sample_index",
    "timestamp_utc",
    "elapsed_seconds",
    "root_pid",
    "pid",
    "ppid",
    "role",
    "process_name",
    "status",
    "rss_bytes",
    "vms_bytes",
    "cpu_percent",
    "num_threads",
    "read_bytes",
    "write_bytes",
    "system_available_bytes",
    "system_memory_percent",
    "swap_used_bytes",
    "swap_memory_percent",
    "disk_free_bytes",
    "disk_used_bytes",
    "cgroup_memory_current_bytes",
    "cgroup_memory_peak_bytes",
    "cgroup_memory_max_bytes",
    "cgroup_oom_events",
    "cgroup_oom_kill_events",
]
_GPU_FIELDS = [
    "host",
    "sample_index",
    "timestamp_utc",
    "elapsed_seconds",
    "gpu_index",
    "gpu_uuid",
    "memory_used_mib",
    "memory_total_mib",
    "gpu_utilization_percent",
    "memory_utilization_percent",
]
_CGROUP_FIELDS = [
    "host",
    "sample_index",
    "timestamp_utc",
    "elapsed_seconds",
    "cgroup_path",
    "memory_current_bytes",
    "memory_peak_bytes",
    "memory_max_bytes",
    "memory_high_bytes",
    "memory_swap_current_bytes",
    "memory_swap_max_bytes",
    "memory_stat_anon_bytes",
    "memory_stat_file_bytes",
    "memory_stat_kernel_bytes",
    "memory_stat_sock_bytes",
    "memory_stat_shmem_bytes",
    "memory_stat_file_mapped_bytes",
    "memory_stat_file_dirty_bytes",
    "memory_stat_file_writeback_bytes",
    "memory_stat_inactive_file_bytes",
    "memory_stat_active_file_bytes",
    "memory_stat_kernel_stack_bytes",
    "memory_stat_pagetables_bytes",
    "memory_stat_slab_bytes",
    "memory_stat_slab_reclaimable_bytes",
    "memory_stat_slab_unreclaimable_bytes",
    "memory_stat_pgfault",
    "memory_stat_pgmajfault",
    "memory_events_low",
    "memory_events_high",
    "memory_events_max",
    "memory_events_oom",
    "memory_events_oom_kill",
    "memory_events_oom_group_kill",
    "pressure_some_avg10",
    "pressure_some_avg60",
    "pressure_some_avg300",
    "pressure_some_total_usec",
    "pressure_full_avg10",
    "pressure_full_avg60",
    "pressure_full_avg300",
    "pressure_full_total_usec",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_key_values(path: Path) -> Dict[str, int]:
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, value = line.split()
            values[key] = int(value)
    except (OSError, ValueError):
        pass
    return values


def _read_pressure(path: Path) -> Dict[str, float | int]:
    values: Dict[str, float | int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            category = parts[0]
            for item in parts[1:]:
                key, value = item.split("=", 1)
                field = f"pressure_{category}_{key if key != 'total' else 'total_usec'}"
                values[field] = int(value) if key == "total" else float(value)
    except (OSError, ValueError, IndexError):
        pass
    return values


def _resolve_cgroup_root(pid: int) -> Path | None:
    cgroup_file = Path(f"/proc/{pid}/cgroup")
    if not cgroup_file.is_file():
        return None
    try:
        entries = cgroup_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    relative_path = None
    for entry in entries:
        parts = entry.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            relative_path = parts[2].lstrip("/")
            break
    if relative_path is None:
        return None
    return Path("/sys/fs/cgroup") / relative_path


def _read_cgroup_root(cgroup_root: Path | None) -> Dict[str, Any]:
    if cgroup_root is None:
        return {}
    events = _read_key_values(cgroup_root / "memory.events")
    stat = _read_key_values(cgroup_root / "memory.stat")
    result = {
        "cgroup_path": str(cgroup_root),
        "cgroup_memory_current_bytes": _read_int(cgroup_root / "memory.current"),
        "cgroup_memory_peak_bytes": _read_int(cgroup_root / "memory.peak"),
        "cgroup_memory_max_bytes": _read_int(cgroup_root / "memory.max"),
        "memory_current_bytes": _read_int(cgroup_root / "memory.current"),
        "memory_peak_bytes": _read_int(cgroup_root / "memory.peak"),
        "memory_max_bytes": _read_int(cgroup_root / "memory.max"),
        "memory_high_bytes": _read_int(cgroup_root / "memory.high"),
        "memory_swap_current_bytes": _read_int(cgroup_root / "memory.swap.current"),
        "memory_swap_max_bytes": _read_int(cgroup_root / "memory.swap.max"),
        "memory_stat_anon_bytes": stat.get("anon"),
        "memory_stat_file_bytes": stat.get("file"),
        "memory_stat_kernel_bytes": stat.get("kernel"),
        "memory_stat_sock_bytes": stat.get("sock"),
        "memory_stat_shmem_bytes": stat.get("shmem"),
        "memory_stat_file_mapped_bytes": stat.get("file_mapped"),
        "memory_stat_file_dirty_bytes": stat.get("file_dirty"),
        "memory_stat_file_writeback_bytes": stat.get("file_writeback"),
        "memory_stat_inactive_file_bytes": stat.get("inactive_file"),
        "memory_stat_active_file_bytes": stat.get("active_file"),
        "memory_stat_kernel_stack_bytes": stat.get("kernel_stack"),
        "memory_stat_pagetables_bytes": stat.get("pagetables"),
        "memory_stat_slab_bytes": stat.get("slab"),
        "memory_stat_slab_reclaimable_bytes": stat.get("slab_reclaimable"),
        "memory_stat_slab_unreclaimable_bytes": stat.get("slab_unreclaimable"),
        "memory_stat_pgfault": stat.get("pgfault"),
        "memory_stat_pgmajfault": stat.get("pgmajfault"),
        "memory_events_low": events.get("low"),
        "memory_events_high": events.get("high"),
        "memory_events_max": events.get("max"),
        "memory_events_oom": events.get("oom"),
        "memory_events_oom_kill": events.get("oom_kill"),
        "memory_events_oom_group_kill": events.get("oom_group_kill"),
        "cgroup_oom_events": events.get("oom"),
        "cgroup_oom_kill_events": events.get("oom_kill"),
    }
    result.update(_read_pressure(cgroup_root / "memory.pressure"))
    return result


def read_cgroup_memory(pid: int) -> Dict[str, Any]:
    return _read_cgroup_root(_resolve_cgroup_root(pid))


def _swap_snapshot() -> tuple[int | None, float | None]:
    try:
        swap_memory = psutil.swap_memory()
        return swap_memory.used, swap_memory.percent
    except (OSError, RuntimeError):
        return None, None


def _process_io_bytes(process: psutil.Process) -> tuple[int | None, int | None]:
    try:
        io_counters = process.io_counters()
        return io_counters.read_bytes, io_counters.write_bytes
    except (AttributeError, OSError, psutil.Error):
        return None, None


def classify_process(root_pid: int, process: psutil.Process) -> str:
    if process.pid == root_pid:
        return "launcher"
    try:
        command = " ".join(process.cmdline()).lower()
        name = process.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "unknown"
    if "server/simulate_job" in command or "fed_server" in command or "server_train" in command:
        return "server"
    if "simulator" in command or "simulator" in name:
        return "simulator"
    if "client.py" in command or "fed_client" in command or "client_train" in command:
        return "client"
    return "other"


class ProcessTreeMonitor:
    def __init__(
        self,
        root_pid: int,
        output_dir: Path,
        sample_interval_seconds: float = 0.5,
        gpu_sample_interval_seconds: float = 1.0,
        host_label: str = "local",
        cgroup_root: Path | None = None,
    ):
        self.root_pid = root_pid
        self.output_dir = output_dir
        self.sample_interval_seconds = sample_interval_seconds
        self.gpu_sample_interval_seconds = gpu_sample_interval_seconds
        self.host_label = host_label
        self.process_path = output_dir / "process_samples.csv"
        self.gpu_path = output_dir / "gpu_samples.csv"
        self.cgroup_path = output_dir / "cgroup_samples.csv"
        self.error_path = output_dir / "monitor_errors.jsonl"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_cache: Dict[int, psutil.Process] = {}
        self._cgroup_root = cgroup_root or _resolve_cgroup_root(root_pid)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("monitor is already running")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="llm-stress-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.sample_interval_seconds * 4))

    def _record_error(self, operation: str, error: Exception) -> None:
        record = {
            "timestamp_utc": _utc_now(),
            "operation": operation,
            "error_type": type(error).__name__,
            "message": str(error),
        }
        with self.error_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, sort_keys=True) + "\n")

    def _processes(self) -> Iterable[psutil.Process]:
        try:
            root = self._process_cache.setdefault(self.root_pid, psutil.Process(self.root_pid))
            candidates = [root, *root.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []
        live_pids = {process.pid for process in candidates}
        for pid in list(self._process_cache):
            if pid not in live_pids:
                self._process_cache.pop(pid, None)
        result = []
        for candidate in candidates:
            process = self._process_cache.setdefault(candidate.pid, candidate)
            result.append(process)
        return result

    def _sample_processes(self, sample_index: int, timestamp: str, elapsed: float) -> list[Dict[str, Any]]:
        virtual_memory = psutil.virtual_memory()
        swap_used_bytes, swap_memory_percent = _swap_snapshot()
        disk_usage = psutil.disk_usage(self.output_dir)
        cgroup = _read_cgroup_root(self._cgroup_root)
        records = []
        for process in self._processes():
            try:
                memory = process.memory_info()
                read_bytes, write_bytes = _process_io_bytes(process)
                records.append(
                    {
                        "host": self.host_label,
                        "sample_index": sample_index,
                        "timestamp_utc": timestamp,
                        "elapsed_seconds": f"{elapsed:.6f}",
                        "root_pid": self.root_pid,
                        "pid": process.pid,
                        "ppid": process.ppid(),
                        "role": classify_process(self.root_pid, process),
                        "process_name": process.name(),
                        "status": process.status(),
                        "rss_bytes": memory.rss,
                        "vms_bytes": memory.vms,
                        "cpu_percent": process.cpu_percent(interval=None),
                        "num_threads": process.num_threads(),
                        "read_bytes": read_bytes,
                        "write_bytes": write_bytes,
                        "system_available_bytes": virtual_memory.available,
                        "system_memory_percent": virtual_memory.percent,
                        "swap_used_bytes": swap_used_bytes,
                        "swap_memory_percent": swap_memory_percent,
                        "disk_free_bytes": disk_usage.free,
                        "disk_used_bytes": disk_usage.used,
                        "cgroup_memory_current_bytes": cgroup.get("cgroup_memory_current_bytes"),
                        "cgroup_memory_peak_bytes": cgroup.get("cgroup_memory_peak_bytes"),
                        "cgroup_memory_max_bytes": cgroup.get("cgroup_memory_max_bytes"),
                        "cgroup_oom_events": cgroup.get("cgroup_oom_events"),
                        "cgroup_oom_kill_events": cgroup.get("cgroup_oom_kill_events"),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        if not records:
            records.append(
                {
                    "host": self.host_label,
                    "sample_index": sample_index,
                    "timestamp_utc": timestamp,
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "root_pid": self.root_pid,
                    "pid": 0,
                    "ppid": 0,
                    "role": "system",
                    "process_name": "root-exited",
                    "status": "unavailable",
                    "rss_bytes": 0,
                    "vms_bytes": 0,
                    "cpu_percent": 0,
                    "num_threads": 0,
                    "read_bytes": 0,
                    "write_bytes": 0,
                    "system_available_bytes": virtual_memory.available,
                    "system_memory_percent": virtual_memory.percent,
                    "swap_used_bytes": swap_used_bytes,
                    "swap_memory_percent": swap_memory_percent,
                    "disk_free_bytes": disk_usage.free,
                    "disk_used_bytes": disk_usage.used,
                    "cgroup_memory_current_bytes": cgroup.get("cgroup_memory_current_bytes"),
                    "cgroup_memory_peak_bytes": cgroup.get("cgroup_memory_peak_bytes"),
                    "cgroup_memory_max_bytes": cgroup.get("cgroup_memory_max_bytes"),
                    "cgroup_oom_events": cgroup.get("cgroup_oom_events"),
                    "cgroup_oom_kill_events": cgroup.get("cgroup_oom_kill_events"),
                }
            )
        return records

    def _sample_gpus(self, sample_index: int, timestamp: str, elapsed: float) -> list[Dict[str, Any]]:
        if shutil.which("nvidia-smi") is None:
            return []
        query = "index,uuid,memory.used,memory.total,utilization.gpu,utilization.memory"
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            self._record_error("nvidia-smi", error)
            return []
        records = []
        for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            if len(row) != 6:
                continue
            records.append(
                {
                    "host": self.host_label,
                    "sample_index": sample_index,
                    "timestamp_utc": timestamp,
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "gpu_index": row[0],
                    "gpu_uuid": row[1],
                    "memory_used_mib": row[2],
                    "memory_total_mib": row[3],
                    "gpu_utilization_percent": row[4],
                    "memory_utilization_percent": row[5],
                }
            )
        return records

    def _sample_cgroup(self, sample_index: int, timestamp: str, elapsed: float) -> Dict[str, Any]:
        return {
            "host": self.host_label,
            "sample_index": sample_index,
            "timestamp_utc": timestamp,
            "elapsed_seconds": f"{elapsed:.6f}",
            **{field: None for field in _CGROUP_FIELDS[4:]},
            **_read_cgroup_root(self._cgroup_root),
        }

    def _run(self) -> None:
        started = time.monotonic()
        next_gpu_sample = started
        sample_index = 0
        try:
            with self.process_path.open("w", encoding="utf-8", newline="") as process_file, self.gpu_path.open(
                "w", encoding="utf-8", newline=""
            ) as gpu_file, self.cgroup_path.open("w", encoding="utf-8", newline="") as cgroup_file:
                process_writer = csv.DictWriter(process_file, fieldnames=_PROCESS_FIELDS)
                gpu_writer = csv.DictWriter(gpu_file, fieldnames=_GPU_FIELDS)
                cgroup_writer = csv.DictWriter(cgroup_file, fieldnames=_CGROUP_FIELDS, extrasaction="ignore")
                process_writer.writeheader()
                gpu_writer.writeheader()
                cgroup_writer.writeheader()
                while not self._stop_event.is_set():
                    now = time.monotonic()
                    elapsed = now - started
                    timestamp = _utc_now()
                    for record in self._sample_processes(sample_index, timestamp, elapsed):
                        process_writer.writerow(record)
                    process_file.flush()
                    cgroup_writer.writerow(self._sample_cgroup(sample_index, timestamp, elapsed))
                    cgroup_file.flush()
                    if now >= next_gpu_sample:
                        for record in self._sample_gpus(sample_index, timestamp, elapsed):
                            gpu_writer.writerow(record)
                        gpu_file.flush()
                        next_gpu_sample = now + self.gpu_sample_interval_seconds
                    sample_index += 1
                    self._stop_event.wait(self.sample_interval_seconds)
        except Exception as error:
            self._record_error("monitor_loop", error)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample a process tree for an LLM stress run.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--gpu-interval", type=float, default=1.0)
    parser.add_argument("--host-label", default="local")
    parser.add_argument("--cgroup-root", type=Path)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    monitor = ProcessTreeMonitor(
        args.pid,
        args.output_dir,
        args.interval,
        args.gpu_interval,
        args.host_label,
        args.cgroup_root,
    )
    monitor.start()
    root_exited = False
    try:
        root_process = psutil.Process(args.pid)
        root_create_time = root_process.create_time()
        while psutil.pid_exists(args.pid):
            if args.stop_file and args.stop_file.exists():
                break
            try:
                if psutil.Process(args.pid).create_time() != root_create_time:
                    root_exited = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                root_exited = True
                break
            time.sleep(0.5)
        if not psutil.pid_exists(args.pid):
            root_exited = True
    except (KeyboardInterrupt, psutil.NoSuchProcess):
        root_exited = True
    finally:
        if root_exited:
            time.sleep(args.interval * 1.5)
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
