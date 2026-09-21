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

"""Executable contract for shared terminal-outcome/resource-report handling.

This module is deliberately not a production CellNet implementation or a
choice of wire carrier.  It models the common completion body and the
acceptance rules that a root-server handler applies after carrier-specific
dispatch.  A carrier adapter remains responsible for its topic and outer
metadata, including validation of any protocol version, before it calls this
shared logic.  Authentication, CellNet framing, atomic workspace persistence,
and job-outcome resolution also remain responsibilities of the production
integration.

The caller supplies the authenticated client identity.  It must come from the
existing authenticated session, never from an envelope field.  The receiver
then binds that identity and the envelope's job ID to the server's expected
participants for that job.  A malformed or absent resource report never
changes the terminal outcome supplied by the client parent.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MAX_PARTICIPANT_SUMMARY_BYTES = 1 * 1024 * 1024

RESOURCE_REPORT_ACCEPTED = "accepted"
RESOURCE_REPORT_DUPLICATE = "duplicate"
RESOURCE_REPORT_INVALID = "invalid"
RESOURCE_REPORT_CONFLICT = "conflict"
RESOURCE_REPORT_TOO_LATE = "too_late"
RESOURCE_REPORT_NOT_PROVIDED = "not_provided"
RESOURCE_REPORT_SERVER_ERROR = "server_error"

TERMINAL_OUTCOME_ACCEPTED = "accepted"
TERMINAL_OUTCOME_DUPLICATE = "duplicate"
TERMINAL_OUTCOME_CONFLICT = "conflict"
TERMINAL_OUTCOME_TOO_LATE = "too_late"

_MISSING = object()


class TerminalEnvelopeError(ValueError):
    """Raised when the terminal-outcome part of an envelope is malformed."""


class UnexpectedParticipantError(ValueError):
    """Raised when authenticated server state does not expect this sender/job."""


class _InvalidResourceReport(ValueError):
    """Internal error converted to an ``invalid`` resource-report result."""


SemanticValidator = Callable[[Mapping[str, Any], int], None]


@dataclass(frozen=True)
class ExpectedParticipant:
    """Trusted job/site association prepared by the root server."""

    job_id: str
    authenticated_client_id: str
    participant_name: str

    def __post_init__(self) -> None:
        for label, value in (
            ("job_id", self.job_id),
            ("authenticated_client_id", self.authenticated_client_id),
            ("participant_name", self.participant_name),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be a non-empty string")


@dataclass(frozen=True)
class AcceptedResourceReport:
    """The exact bytes occupying one participant acceptance slot."""

    job_id: str
    participant_name: str
    participant_summary: bytes


@dataclass(frozen=True)
class AcceptanceResult:
    """Independent classifications for terminal outcome and resource report."""

    job_id: str
    participant_name: str
    terminal_outcome_status: str
    resource_report_status: str
    detail: str | None = None


@dataclass(frozen=True)
class _Candidate:
    participant_summary: bytes


def build_terminal_outcome_envelope(
    job_id: str,
    code: int,
    reason: str | None,
    participant_summary: bytes | None = None,
) -> dict[str, Any]:
    """Build the carrier-independent completion body.

    Carrier metadata such as ``protocol_version`` is intentionally outside
    this body.
    """

    _validate_terminal_fields(job_id, code, reason)
    envelope: dict[str, Any] = {"job_id": job_id, "code": code, "reason": reason}
    if participant_summary is not None:
        if not isinstance(participant_summary, bytes):
            raise TypeError("participant_summary must be bytes")
        if len(participant_summary) > MAX_PARTICIPANT_SUMMARY_BYTES:
            raise ValueError(f"participant_summary exceeds the {MAX_PARTICIPANT_SUMMARY_BYTES}-byte limit")
        envelope["resource_report"] = {"participant_summary": participant_summary}
    return envelope


def _validate_terminal_fields(job_id: object, code: object, reason: object) -> None:
    if not isinstance(job_id, str) or not job_id:
        raise TerminalEnvelopeError("job_id must be a non-empty string")
    if not isinstance(code, int) or isinstance(code, bool):
        raise TerminalEnvelopeError("code must be an integer")
    if reason is not None and not isinstance(reason, str):
        raise TerminalEnvelopeError("reason must be a string or null")


def _decode_json(data: bytes) -> Mapping[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _InvalidResourceReport(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise _InvalidResourceReport(f"non-finite JSON number {value!r} is forbidden")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _InvalidResourceReport("participant_summary must be valid UTF-8") from exc
    try:
        record = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except _InvalidResourceReport:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise _InvalidResourceReport(f"participant_summary is not valid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise _InvalidResourceReport("participant_summary must decode to a JSON object")
    return record


class TerminalReportReceiver:
    """In-memory prototype of shared validation and replay handling.

    ``semantic_validator`` must raise an exception for a record that fails the
    schema or semantic contract.  Its second argument is the exact serialized
    byte count.  Production code must atomically persist the accepted bytes in
    the server run workspace before acknowledging ``accepted``; this prototype
    retains them in memory so tests can inspect the state transition.  Semantic
    validation happens outside the state lock, and the final commit rechecks the
    cutoff under the same lock used by ``close_job``.
    """

    def __init__(
        self,
        expected_participants: Iterable[ExpectedParticipant],
        semantic_validator: SemanticValidator,
        *,
        max_participant_summary_bytes: int = MAX_PARTICIPANT_SUMMARY_BYTES,
    ):
        if not callable(semantic_validator):
            raise TypeError("semantic_validator must be callable")
        if (
            not isinstance(max_participant_summary_bytes, int)
            or isinstance(max_participant_summary_bytes, bool)
            or not 0 < max_participant_summary_bytes <= MAX_PARTICIPANT_SUMMARY_BYTES
        ):
            raise ValueError("max_participant_summary_bytes must be between 1 and " f"{MAX_PARTICIPANT_SUMMARY_BYTES}")

        self._semantic_validator = semantic_validator
        self._max_participant_summary_bytes = max_participant_summary_bytes
        self._expected: dict[tuple[str, str], ExpectedParticipant] = {}
        participant_slots: set[tuple[str, str]] = set()
        for expected in expected_participants:
            if not isinstance(expected, ExpectedParticipant):
                raise TypeError("expected_participants must contain ExpectedParticipant values")
            binding = (expected.job_id, expected.authenticated_client_id)
            slot = (expected.job_id, expected.participant_name)
            if binding in self._expected:
                raise ValueError("authenticated client/job binding must be unique")
            if slot in participant_slots:
                raise ValueError("participant acceptance slot must be unique within a job")
            self._expected[binding] = expected
            participant_slots.add(slot)

        self._known_jobs = frozenset(expected.job_id for expected in self._expected.values())
        self._accepted_reports: dict[tuple[str, str], AcceptedResourceReport] = {}
        self._terminal_outcomes: dict[tuple[str, str], tuple[int, str | None]] = {}
        self._closed_jobs: set[str] = set()
        self._lock = threading.Lock()

    def close_job(self, job_id: str) -> None:
        """Close resource-report acceptance at the server's fixed cutoff."""

        if job_id not in self._known_jobs:
            raise ValueError("cannot close an unknown job")
        with self._lock:
            self._closed_jobs.add(job_id)

    def get_accepted_report(self, job_id: str, participant_name: str) -> AcceptedResourceReport | None:
        """Return the accepted in-memory prototype record, if any."""

        with self._lock:
            return self._accepted_reports.get((job_id, participant_name))

    def get_terminal_outcome(self, job_id: str, authenticated_client_id: str) -> tuple[int, str | None] | None:
        """Return the first terminal outcome retained for an expected sender."""

        with self._lock:
            return self._terminal_outcomes.get((job_id, authenticated_client_id))

    def accept(self, envelope: Mapping[str, Any], authenticated_client_id: str) -> AcceptanceResult:
        """Validate one normalized completion body using an auth-layer identity."""

        job_id, code, reason = self._parse_terminal_outcome(envelope)
        expected = self._expected.get((job_id, authenticated_client_id))
        if expected is None:
            raise UnexpectedParticipantError(
                "authenticated client and job are not in the server's expected participants"
            )

        report_value = envelope.get("resource_report", _MISSING)
        if report_value is _MISSING:
            with self._lock:
                terminal_status = self._classify_terminal_locked(expected, code, reason)
            return AcceptanceResult(
                job_id=job_id,
                participant_name=expected.participant_name,
                terminal_outcome_status=terminal_status,
                resource_report_status=RESOURCE_REPORT_NOT_PROVIDED,
                detail="resource_report was omitted",
            )

        try:
            candidate = self._validate_candidate_transport(report_value)
        except _InvalidResourceReport as exc:
            with self._lock:
                terminal_status = self._classify_terminal_locked(expected, code, reason)
            return AcceptanceResult(
                job_id=job_id,
                participant_name=expected.participant_name,
                terminal_outcome_status=terminal_status,
                resource_report_status=RESOURCE_REPORT_INVALID,
                detail=str(exc),
            )

        slot = (expected.job_id, expected.participant_name)
        with self._lock:
            existing = self._accepted_reports.get(slot)
            if existing is not None and self._same_report(existing, candidate):
                terminal_status = self._classify_terminal_locked(expected, code, reason)
                return AcceptanceResult(
                    job_id=job_id,
                    participant_name=expected.participant_name,
                    terminal_outcome_status=terminal_status,
                    resource_report_status=RESOURCE_REPORT_DUPLICATE,
                )
            if expected.job_id in self._closed_jobs:
                terminal_status = self._classify_terminal_locked(expected, code, reason)
                return AcceptanceResult(
                    job_id=job_id,
                    participant_name=expected.participant_name,
                    terminal_outcome_status=terminal_status,
                    resource_report_status=RESOURCE_REPORT_TOO_LATE,
                    detail="resource-report cutoff has passed",
                )
            if existing is not None:
                terminal_status = self._classify_terminal_locked(expected, code, reason)
                return AcceptanceResult(
                    job_id=job_id,
                    participant_name=expected.participant_name,
                    terminal_outcome_status=terminal_status,
                    resource_report_status=RESOURCE_REPORT_CONFLICT,
                    detail="a different valid report already occupies the participant slot",
                )

        try:
            record = _decode_json(candidate.participant_summary)
            self._semantic_validator(record, len(candidate.participant_summary))
            if record.get("job_id") != expected.job_id:
                raise _InvalidResourceReport("participant_summary job_id does not match trusted state")
            if record.get("participant_name") != expected.participant_name:
                raise _InvalidResourceReport("participant_summary participant_name does not match trusted state")
        except _InvalidResourceReport as exc:
            detail = str(exc)
            validation_status = RESOURCE_REPORT_INVALID
        except ValueError as exc:
            detail = f"semantic validation failed: {exc}"
            validation_status = RESOURCE_REPORT_INVALID
        except Exception:  # A server fault must not be blamed on client data.
            detail = "server could not validate the resource report"
            validation_status = RESOURCE_REPORT_SERVER_ERROR
        else:
            detail = None
            validation_status = None

        if detail is not None:
            with self._lock:
                terminal_status = self._classify_terminal_locked(expected, code, reason)
            return AcceptanceResult(
                job_id=job_id,
                participant_name=expected.participant_name,
                terminal_outcome_status=terminal_status,
                resource_report_status=validation_status,
                detail=detail,
            )

        accepted = AcceptedResourceReport(
            job_id=expected.job_id,
            participant_name=expected.participant_name,
            participant_summary=candidate.participant_summary,
        )
        with self._lock:
            terminal_status = self._classify_terminal_locked(expected, code, reason)
            existing = self._accepted_reports.get(slot)
            if existing is not None and self._same_report(existing, candidate):
                report_status = RESOURCE_REPORT_DUPLICATE
            elif expected.job_id in self._closed_jobs:
                report_status = RESOURCE_REPORT_TOO_LATE
            elif existing is not None:
                report_status = RESOURCE_REPORT_CONFLICT
            else:
                self._accepted_reports[slot] = accepted
                report_status = RESOURCE_REPORT_ACCEPTED

        return AcceptanceResult(
            job_id=job_id,
            participant_name=expected.participant_name,
            terminal_outcome_status=terminal_status,
            resource_report_status=report_status,
        )

    def _parse_terminal_outcome(self, envelope: Mapping[str, Any]) -> tuple[str, int, str | None]:
        if not isinstance(envelope, Mapping):
            raise TerminalEnvelopeError("terminal outcome envelope must be a mapping")
        if "job_id" not in envelope or "code" not in envelope or "reason" not in envelope:
            raise TerminalEnvelopeError("terminal outcome envelope requires job_id, code, and reason")
        job_id = envelope["job_id"]
        code = envelope["code"]
        reason = envelope["reason"]
        _validate_terminal_fields(job_id, code, reason)
        return job_id, code, reason

    def _validate_candidate_transport(self, value: object) -> _Candidate:
        if not isinstance(value, Mapping):
            raise _InvalidResourceReport("resource_report must be an object")
        if set(value) != {"participant_summary"}:
            raise _InvalidResourceReport("resource_report requires only participant_summary")
        participant_summary = value.get("participant_summary")
        if not isinstance(participant_summary, bytes):
            raise _InvalidResourceReport("resource_report.participant_summary must be bytes")
        if len(participant_summary) > self._max_participant_summary_bytes:
            raise _InvalidResourceReport(
                "resource_report.participant_summary exceeds the " f"{self._max_participant_summary_bytes}-byte limit"
            )
        return _Candidate(participant_summary=participant_summary)

    def _classify_terminal_locked(self, expected: ExpectedParticipant, code: int, reason: str | None) -> str:
        binding = (expected.job_id, expected.authenticated_client_id)
        prior = self._terminal_outcomes.get(binding)
        candidate = (code, reason)
        if prior == candidate:
            return TERMINAL_OUTCOME_DUPLICATE
        if prior is not None:
            return TERMINAL_OUTCOME_CONFLICT
        if expected.job_id in self._closed_jobs:
            return TERMINAL_OUTCOME_TOO_LATE
        self._terminal_outcomes[binding] = candidate
        return TERMINAL_OUTCOME_ACCEPTED

    @staticmethod
    def _same_report(existing: AcceptedResourceReport, candidate: _Candidate) -> bool:
        return existing.participant_summary == candidate.participant_summary
