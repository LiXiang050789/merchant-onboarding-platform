from __future__ import annotations

from .models import FormStatus


ALLOWED_TRANSITIONS: dict[FormStatus, set[FormStatus]] = {
    FormStatus.draft: {FormStatus.submitted},
    FormStatus.submitted: {FormStatus.validating},
    FormStatus.validating: {FormStatus.validated, FormStatus.rejected},
    FormStatus.validated: {FormStatus.batched},
    FormStatus.batched: {FormStatus.processing},
    FormStatus.processing: {FormStatus.published, FormStatus.failed},
    FormStatus.failed: {FormStatus.processing},
    FormStatus.rejected: set(),
    FormStatus.published: set(),
}


def can_transition(current: FormStatus, target: FormStatus, retry_count: int = 0) -> bool:
    if current == FormStatus.failed and target == FormStatus.processing:
        return retry_count < 3
    return target in ALLOWED_TRANSITIONS[current]
