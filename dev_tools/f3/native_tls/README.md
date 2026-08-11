# Native TLS lane-pool prototype

This profile replaces the gRPC transport with F3's native TLS transport on one
server port. Lane 0 carries F3 control traffic. Two additional client-initiated
TLS connections carry `ByteStreamer` data frames. All three connections target
the same listener; clients use normal ephemeral source ports, so the profile
does not require an additional server port.

The prototype is opt-in. Both endpoints must run the same implementation and
use compatible `tcp_bulk_lanes` settings. It does not support a rolling mix of
the lane-pool implementation and an older STCP peer.

Use `stcp://` URLs and transport mTLS for production-shaped testing. The
benchmark credentials and hostname-verification requirements are documented in
`dev_tools/f3/cellnet_bench.py`.

The independently measurable settings are:

- Legacy native TLS: `tcp_async_send: false`, `tcp_bulk_lanes: 0`.
- One asynchronous physical lane: `tcp_async_send: true`, `tcp_bulk_lanes: 0`.
- Dedicated control plus one bulk lane: `tcp_async_send: true`,
  `tcp_bulk_lanes: 1`.
- Dedicated control plus two bulk lanes (this profile):
  `tcp_async_send: true`, `tcp_bulk_lanes: 2`.

Keep the aggregate `streaming_window_size` fixed while changing lane count so
lane scaling is not confounded by extra in-flight application data.

This is a transport prototype, not the final production hardening. It still
uses F3's existing contiguous SFM frame assembly and receiver Blob copy. A
production rollout also needs an explicit accepted-connection/thread quota, a
deployment-specific ingress frame cap below the legacy ~2 GiB maximum, idle
read deadlines, complete provisioning/template coverage for hostname-verified
mTLS, and mixed-version fallback or a coordinated restart policy.
