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

"""Research entry point for the production raw-capacity schema 3 contract.

Live and archive validation require schema 3. Earlier unreleased prototype
formats are deliberately not supported.
"""

from nvflare.private.fed.resource_stats.contract import (  # noqa: F401
    GPU_KINDS,
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    KIND_STUDY_SUMMARY,
    MAX_CAPACITY_INTERVALS,
    MAX_CPU_UNITS,
    MAX_GPU_GROUPS,
    MAX_RECORD_BYTES,
    MAX_STUDY_JOBS,
    RECORD_KINDS,
    SCHEMA_VERSION,
    U64_MAX,
    U128_MAX,
    ContractError,
    canonical_json_bytes,
    capacity_to_resource_time,
    derive_job_totals,
    derive_study_totals,
    load_and_validate,
    normalize_measurement,
    normalize_message_traffic,
    normalize_quota_units,
    normalize_record,
    participant_measurements,
    validate_bundle,
    validate_record,
)
