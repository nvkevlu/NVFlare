.. _native_tensor_bulk:

Native TLS Tensor Bulk Transport
================================

NVFlare can optionally move eligible single-receiver PyTorch state dictionaries
over a bounded native mTLS bulk path. The existing F3 connection still performs
identity, routing, negotiation, transaction progress, and completion. Bulk data
uses short-lived client-initiated TLS connections to the same listener address,
so the feature does not require a second inbound port.

The fast path is disabled by default. Enable it with matching ``comm_config``
settings on upgraded peers::

  {
    "tcp_verify_hostname": true,
    "tcp_tensor_bulk_enabled": true,
    "tcp_tensor_bulk_lanes": 3,
    "tcp_tensor_bulk_max_bytes": 34359738368,
    "tcp_tensor_bulk_max_sessions": 2,
    "tcp_tensor_bulk_timeout": 300.0
  }

Security requirements
---------------------

The feature requires mTLS and hostname verification. The active connection's
target must match a DNS or IP subject alternative name in the server
certificate. F3 also binds the certificate common name to the claimed endpoint
identity. A random 128-bit session token is bound to that authenticated peer;
lane count, total bytes, tensor metadata, active sessions, and time are bounded
before tensor storage is exposed.

Do not enable native bulk with one-way TLS, missing hostname verification, or
through an HTTP/2-only L7 proxy. Generic TCP pass-through load balancers are
compatible only when every connection in a negotiated session reaches the same
NVFlare process.

Compatibility and fallback
--------------------------

The feature is capability-negotiated. An old or disabled peer continues using
the established Download Service path. Multiple receivers, disk consumers,
Cell end-to-end encrypted messages, ineligible tensors, and transfers beyond
local limits also use that fallback. A native session that starts and then
fails is reported as a failed download; it is not automatically replayed into
partially written buffers.

The example profile and validation commands are in
``dev_tools/f3/native_tls/comm_config.yml`` and ``dev_tools/f3/README.md``.
