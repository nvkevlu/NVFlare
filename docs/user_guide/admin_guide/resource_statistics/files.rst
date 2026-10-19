.. _resource_statistics_files:

File Size and Workspace-Filesystem Capacity
*******************************************

Reports store two different byte values:

* ``retained_content.bytes`` is the total size of regular files found under
  the job's run directory when collection finishes.
* ``workspace_filesystem.capacity_bytes`` is the visible capacity of the
  filesystem containing that directory.

Run-directory file size
=======================

The CLI displays the file-size total as ``RUN-DIR FILES GiB``. It includes
inputs, configuration, logs, temporary files, and saved results that are still
under the run directory. It is not a total of only model or result files.

NVFlare adds regular-file lengths and skips symlinks and its own top-level
``resource_stats`` directory. It saves the total, not filenames or a file
inventory. For example:

.. code-block:: json

   {
     "retained_content": {
       "bytes": "1073741824"
     }
   }

This records 1 GiB of file content. Job and study queries can add these totals.
Shared files and repeated copies can be counted again at other participants;
the sum does not represent unique content or allocated disk space.

A scan that cannot finish keeps the subtotal and marks it ``*``.
An observed empty directory is zero. If no usable observation is possible,
the value is unavailable.

Visible workspace-filesystem capacity
=====================================

This is the capacity of the one filesystem containing the existing run
directory. It is **not storage owned by the job**. Other jobs may share it.

A workspace under a small temporary filesystem reports that filesystem's
capacity, even if a larger data disk is mounted elsewhere. NVFlare does not
enumerate or sum other filesystems, multiply this capacity by time, or add
it across participants.

The observation stays in participant detail and appears with ``--site``:

.. code-block:: shell

   nvflare job resources --job JOB_ID --site site-1

For example:

.. code-block:: json

   {
     "workspace_filesystem": {
       "capacity_bytes": "1099511627776"
     }
   }

This reports 1 TiB of visible workspace-filesystem capacity, not 1 TiB of
job data.

Collection details
==================

Both observations are taken during final collection, before report writing
and later cleanup. Files may change during scanning; later log growth or
uploads are not included automatically.

File-size rules
---------------

The collector walks the run directory with ``os.scandir`` and adds each
regular file's ``st_size``, without following symlinks.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Entry
     - Treatment
   * - Sparse file
     - Count logical length, not allocated disk blocks.
   * - Hardlink
     - Count each pathname; shared inodes are not deduplicated.
   * - Symlink, directory size, or other non-regular entry
     - Do not add its size.
   * - Top-level ``resource_stats`` directory
     - Exclude the reports themselves.
   * - Mounted subdirectory within the run directory
     - Traverse it as part of the tree.
   * - Result or log directory outside the run directory
     - Outside this total's scope.

The walk examines at most 100,000 entries, descends at most 64 directory
levels, and checks a one-second budget between entries. These limits keep
collection from scanning an unbounded tree. A blocked filesystem call can
exceed that time budget.

Filesystem query
----------------

NVFlare calls ``os.statvfs(run_directory)`` and records:

.. code-block:: text

   capacity_bytes = f_blocks × f_frsize

Here ``f_blocks`` is total filesystem blocks and ``f_frsize`` is bytes per
fragment. For an optional direct check on an existing directory:

.. code-block:: shell

   python3 - /absolute/path/to/job/run-directory <<'PY'
   import os
   import sys
   stats = os.statvfs(sys.argv[1])
   print(stats.f_blocks * stats.f_frsize)
   PY

This checks the filesystem now; the report contains the earlier observation.
A failed or invalid filesystem query is unavailable and does not remove a
usable file-size total.

The :github_nvflare_link:`file collectors <nvflare/private/fed/resource_stats/collector.py>`
implement these two observations.
