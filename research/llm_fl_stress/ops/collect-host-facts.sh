#!/usr/bin/env bash

set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${script_dir}/.." && pwd)"
ssh_config="${SSH_CONFIG:-${project_dir}/.local/ssh_config}"
output_dir="${HOST_FACTS_DIR:-${project_dir}/.local/host-facts}"

if [[ ! -f "${ssh_config}" ]]; then
    echo "SSH config not found: ${ssh_config}" >&2
    echo "Copy ops/ssh_config.example to .local/ssh_config and edit it first." >&2
    exit 2
fi

if (( $# > 0 )); then
    hosts=("$@")
else
    hosts=(flare-server flare-site-1 flare-site-2)
fi

umask 077
mkdir -p "${output_dir}"
status=0

for host in "${hosts[@]}"; do
    if [[ ! "${host}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        echo "Invalid SSH alias: ${host}" >&2
        status=2
        continue
    fi

    output_path="${output_dir}/${host}.txt"
    echo "Collecting read-only facts from ${host} -> ${output_path}"
    if ! ssh -F "${ssh_config}" -o BatchMode=yes "${host}" 'bash -s' >"${output_path}" 2>&1 <<'REMOTE'
printf '%s\n' '[identity]'
hostname -f 2>/dev/null || hostname
id

printf '%s\n' '[operating-system]'
uname -a
if [[ -r /etc/os-release ]]; then
    cat /etc/os-release
fi

printf '%s\n' '[cpu]'
getconf _NPROCESSORS_ONLN 2>/dev/null || true
lscpu 2>/dev/null || true

printf '%s\n' '[memory]'
grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo 2>/dev/null || true
free -h 2>/dev/null || true
for path in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak; do
    if [[ -r "${path}" ]]; then
        printf '%s=' "${path}"
        cat "${path}"
    fi
done

printf '%s\n' '[storage]'
df -hT 2>/dev/null || df -h
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS 2>/dev/null || true

printf '%s\n' '[network-buffers]'
sysctl net.core.rmem_default net.core.rmem_max \
    net.core.wmem_default net.core.wmem_max \
    net.core.netdev_max_backlog 2>/dev/null || true
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem 2>/dev/null || true
ss -s 2>/dev/null || true

printf '%s\n' '[software]'
python3 --version 2>&1 || true
python3 -c 'import torch; print("torch=" + torch.__version__)' 2>/dev/null || true
python3 -c 'import nvflare; print("nvflare=" + nvflare.__version__)' 2>/dev/null || true
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version \
        --format=csv,noheader 2>/dev/null || nvidia-smi
fi

printf '%s\n' '[limits]'
ulimit -a
REMOTE
    then
        echo "Failed to collect facts from ${host}; review ${output_path}." >&2
        status=1
    fi
done

exit "${status}"
