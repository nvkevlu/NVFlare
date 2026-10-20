.. _resource_statistics_message_traffic:

Application Message Traffic
***************************

Message traffic records selected application payload accepted for sending.
It shows how much data was sent by each participant and how much was addressed
to each participant. It is not a network-interface byte counter or proof
that the receiving application processed the data.

What is counted
===============

NVFlare counts payload for three operations:

* The server deploys a job application to a client.
* The server sends a task to a client.
* A client sends a task result to the server or, in a hierarchical deployment,
  its parent client.

The bytes include serialized application data and associated separately
transferred tensors. One operation to one destination counts as one message;
tensor transfers add bytes to that message.

Registration, heartbeats, control requests, empty task polling, statistics
reports, and unrelated custom traffic are excluded. Encryption and transport
overhead are not included.

Read the output
===============

``PAYLOAD SENT GiB`` is the participant's accepted sends.
``PAYLOAD SENT TO SITE GiB`` is calculated from the other participants'
reports of sends addressed to that site. It is not a separate receive counter.

Inspect these values with:

.. code-block:: shell

   nvflare job resources --job JOB_ID
   nvflare job resources --job JOB_ID --site site-1 --format json

A participant stores sends by destination:

.. code-block:: json

   {
     "message_traffic": {
       "sent_to": [
         {
           "participant_name": "server",
           "payload_bytes": "1073741824",
           "messages": "5"
         }
       ]
     }
   }

This is 1 GiB across five included messages addressed to the server.
``messages`` does not count network packets.

Job and study totals add sent bytes once. Do not add the sent-to-site view
to the sent view: both describe the same addressed traffic. Missing or partial
sender reports also make the sent-to-site view incomplete.

Collection details
==================

When bytes are counted
----------------------

NVFlare measures serialized payload before encryption and credits it after
local send acceptance or the associated completed stream transfer. A rejected
send contributes nothing. Local acceptance does not prove remote receipt.
For a stream, the byte count comes from successful completion, even when its
size was unknown before sending.

For example, a 1 KiB result envelope with 64 MiB of transferred tensors
contributes 67,109,888 payload bytes and one message.

Forwarding hops and transport frames do not become additional messages.
Final delivery between endpoints in the same Python process is excluded;
a local relay on the way to a remote destination is not the final delivery.

NVFlare selects the included operations at its own application call sites.
A received header cannot declare arbitrary traffic countable. Unresolved
transfers or a collection failure keep a partial subtotal rather than
silently treating missing bytes as zero. An empty ``sent_to`` list without
an exception means observed zero included traffic.

Chunked downloads
-----------------

Each chunk needs a stable identifier so a retried chunk is not counted twice.
The built-in producers supply one. A custom ``Downloadable`` can provide it
through ``accounting_chunk_key``; otherwise its byte accounting is incomplete.

The ``counter_gap`` issue also covers a transfer still pending when the report
is collected, a failed accounting callback, too many tracking entries, or the
same chunk identifier appearing with conflicting byte lengths. These conditions
affect statistics only: downloads keep their normal behavior.

External trainers
-----------------

A managed external trainer can transfer tensors directly to the server.
NVFlare combines those bytes with the client's task result so the tensors
are neither omitted nor counted as a second message.

The existing download-completion request carries the source's byte
contribution. To associate a transfer with its client, job, and task, NVFlare
uses the authenticated connection or the site's existing delegated credentials.
No additional authentication setup is required. Those credentials establish
a site identity, not independent proof of which trainer process holds them.

Missing or unmatched contributions make the statistics partial. They do not
reject an otherwise valid download or change its completion, cancellation,
or cleanup. Credentials and private transfer identifiers are not saved.

Custom communication outside the included operations is not automatically
measured. A successful training result does not by itself establish complete
traffic statistics.

Source reference
----------------

The :github_nvflare_link:`transport hooks <nvflare/fuel/f3/send_accounting.py>`,
:github_nvflare_link:`job bindings <nvflare/private/fed/resource_stats/f3_bindings.py>`,
and :github_nvflare_link:`external-trainer binding <nvflare/private/fed/resource_stats/external_transfer.py>`
implement these rules.
