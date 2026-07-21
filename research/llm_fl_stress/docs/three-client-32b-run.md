# Three-Client 32B Follow-Up

## Purpose

Run this immediately after the two-client 32B trim probe to measure realistic
server fan-out with one server and three independent client machines. The
scenario keeps the 32.5B BF16 payload, two rounds, 256 MiB tensor shards, 2 MiB
transport chunks, disk offload, and pre-contribution trim diagnostic. The main
workload change is client count from two to three.

Scenario: `configs/qwen25-32b-3client-trim-probe.json`

Success requires all three clients in both rounds:

- six passing sentinel events;
- three aggregated contributions in round zero;
- three aggregated contributions in round one;
- no cgroup OOM or unplanned peer loss;
- complete server tensor-attribution and trim-probe events.

## Expected Load

One BF16 model payload is 65.0 GB, or 60.54 GiB.

| Quantity | Two clients | Three clients |
| --- | ---: | ---: |
| Logical wire per round | 260 GB / 242.14 GiB | 390 GB / 363.22 GiB |
| Logical wire for two rounds | 520 GB / 484.29 GiB | 780 GB / 726.43 GiB |
| Expected client RSS | 66--70 GiB each | 66--70 GiB each |
| Expected client machines | 2 × 128 GiB | 3 × 128 GiB |
| Expected completed job time | 55--70 minutes | 80--105 minutes |

In-time aggregation creates one full weighted accumulator for the first
contribution and adds later clients in place. The third client therefore should
not add another full model-sized accumulator. It can still increase server
transport serialization, socket buffers, transaction concurrency, pressure,
and elapsed time. Those are the reasons for running this fan-out test.

## Go/No-Go After The Two-Client Probe

Proceed on the same 256 GiB server only when the two-client trim probe:

1. releases substantial RSS before the first round-one contribution;
2. completes both rounds without OOM;
3. stays comfortably below the 235 GiB server cgroup hard limit after trim.

If the two-client probe releases little memory or still stalls, do not spend
another 80--105 minutes repeating the same boundary with a third client. Move
the three-client run to a 384 GiB boundary server or a 512 GiB qualification
server while retaining 128 GiB per client.

## Four-Host Setup

Provision the federation from `ops/project-3-clients.yml.template`. It creates
startup kits for `flare-server`, `site-1`, `site-2`, `site-3`, and the admin.
The local SSH configuration must provide these aliases:

- `flare-server`
- `flare-site-1`
- `flare-site-2`
- `flare-site-3`

Collect intake facts from all four machines explicitly:

```bash
research/llm_fl_stress/ops/collect-host-facts.sh \
  flare-server flare-site-1 flare-site-2 flare-site-3
```

The deployment helper already accepts repeated clients:

```bash
python3 research/llm_fl_stress/ops/deploy_services.py \
  --ssh-config research/llm_fl_stress/.local/ssh_config \
  --kit-root <provisioned-kit-root> \
  --server flare-server=flare-server \
  --client flare-site-1=site-1 \
  --client flare-site-2=site-2 \
  --client flare-site-3=site-3 \
  --remote-source-root /opt/nvflare-stress/local-kevlu/source \
  --remote-kit-root /opt/nvflare-stress/local-kevlu/kit
```

### High-throughput F3 comparison

F3 stream settings are process-startup settings, not job-level tensor chunk
settings. Restart every server and client service with the following options
before running `qwen25-32b-f3-tuned-1r.json`:

```bash
python3 research/llm_fl_stress/ops/deploy_services.py \
  --ssh-config research/llm_fl_stress/.local/ssh_config \
  --kit-root <provisioned-kit-root> \
  --server flare-server=flare-server \
  --client flare-site-1=site-1 \
  --client flare-site-2=site-2 \
  --client flare-site-3=site-3 \
  --remote-source-root /opt/nvflare-stress/local-kevlu/source \
  --remote-kit-root /opt/nvflare-stress/local-kevlu/kit \
  --streaming-chunk-size 4194304 \
  --streaming-window-size 134217728 \
  --streaming-ack-interval 33554432 \
  --streaming-max-out-seq-chunks 64
```

The production runner verifies these inherited environment variables on every
participating service and fails before submission if they do not match the
scenario. The profile is a high-throughput candidate, not a claim of universal
optimality; compare it against the existing 1 MiB frame, 16 MiB window, and
4 MiB ACK defaults.

The 64-chunk reorder allowance is required with this profile. A full-scale
three-client fan-in using the default limit of 16 encountered repeated
`Too many out-of-sequence chunks: 16` stream failures and eventually exhausted
the download retries. With 4 MiB chunks, the 128 MiB window can contain 32
chunks; 64 provides a two-window allowance while bounding this queue to at most
256 MiB per active stream.

## Production Command

Use the same server cgroup settings as the two-client trim probe and do not
lower the limit during the run:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-32b-3client-trim-probe.json \
  --production \
  --startup-kit-location <admin-startup-kit> \
  --ssh-config research/llm_fl_stress/.local/ssh_config \
  --remote-source-root /opt/nvflare-stress/local-kevlu/source \
  --remote-service-root /opt/nvflare-stress/local-kevlu/kit \
  --remote-output-root /opt/nvflare-stress/local-kevlu/runs \
  --skip-result-download \
  --allow-capacity-risk \
  --cgroup-memory-max-gib server=235 \
  --cgroup-memory-high-ratio 0.95 \
  --result-timeout 7200
```

The production runner automatically maps `site-3` to `flare-site-3`. Use
`--client-ssh-alias site-3=<alias>` only if the local alias differs.

Budget at least two additional hours after the two-client probe when the
runtime, source checkout, kits, and services are already staged. Budget three
hours for this run alone if the fourth client needs dependency installation and
kit deployment.
