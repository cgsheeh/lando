import logging

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from ninja import NinjaAPI, Schema
from ninja.responses import codes_4xx

from lando.main.models.jobs import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftJobMode,
    UpliftRevision,
    UpliftSubmission,
)
from lando.utils.exceptions import (
    NotFoundProblemException,
    ProblemDetail,
    ProblemException,
    problem_exception_handler,
)
from lando.utils.ninja_auth import HarbormasterWebhookAuth, PhabricatorTokenAuth
from lando.utils.phabricator import PhabricatorAPIException, PhabricatorClient
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)

api = NinjaAPI(auth=PhabricatorTokenAuth(), urls_namespace="uplift-api")
api.exception_handler(ProblemException)(problem_exception_handler)


class LinkRevisionRequest(Schema):
    """Request body for linking a revision to an uplift assessment."""

    revision_id: int
    assessment_id: int


class LinkRevisionResponse(Schema):
    """Response body after successfully linking a revision to an assessment."""

    revision_id: int
    assessment_id: int
    created: bool


@api.post(
    "/assessments/link",
    response={201: LinkRevisionResponse, codes_4xx: ProblemDetail},
)
def link_revision_to_assessment(
    request: WSGIRequest,
    body: LinkRevisionRequest,
) -> tuple[int, dict]:
    """Link a Phabricator revision to an existing uplift assessment.

    This endpoint is intended for use by `moz-phab uplift` after the
    developer has manually resolved merge conflicts and submitted their
    revision. It creates an `UpliftRevision` record linking the new
    revision to the assessment, and triggers a Celery task to update
    the uplift request form on Phabricator.
    """
    logger.debug(
        "Received request to link revision %d to assessment %d.",
        body.revision_id,
        body.assessment_id,
    )

    try:
        assessment = UpliftAssessment.objects.get(id=body.assessment_id)
    except UpliftAssessment.DoesNotExist:
        detail = f"Assessment with id {body.assessment_id} does not exist."
        logger.warning(detail)
        raise NotFoundProblemException(title="Assessment not found", detail=detail)

    with transaction.atomic():
        uplift_revision, created = UpliftRevision.link_revision_to_assessment(
            body.revision_id, assessment
        )

    logger.info(
        "Linked revision %d to assessment %d (created=%s).",
        body.revision_id,
        body.assessment_id,
        created,
    )

    # Trigger the Celery task to update the uplift form on Phabricator.
    set_uplift_request_form_on_revision.apply_async(
        args=(
            body.revision_id,
            assessment.to_conduit_json_str(),
            assessment.user.id,
        )
    )

    return 201, LinkRevisionResponse(
        revision_id=body.revision_id,
        assessment_id=body.assessment_id,
        created=created,
    )


class HarbormasterRevisionObject(Schema):
    """Inner `object` payload as posted by a Phabricator webhook.

    Phabricator sends `phid` and `type` but no integer `id`; we resolve the PHID
    to a revision ID via Conduit. `id` is accepted for direct callers and tests.
    """

    phid: str | None = None
    type: str | None = None
    id: int | None = None


class RevisionUpdatedRequest(Schema):
    """Request body for the revision-updated webhook.

    `object` is optional so test pings without a usable object are a no-op
    rather than a `422`.
    """

    object: HarbormasterRevisionObject | None = None


class RevisionUpdatedResponse(Schema):
    """Response body summarising the UPDATE jobs queued by a webhook call."""

    revision_id: int | None
    queued_jobs: list[int]


def resolve_revision_phid_to_id(phid: str) -> int | None:
    """Look up a Differential revision's integer ID by its PHID via Conduit.

    Uses the admin API key since the webhook has no user context. Returns `None`
    when the PHID is unknown or Conduit errors, so the webhook stays a safe
    no-op.
    """
    phab = PhabricatorClient(
        settings.PHABRICATOR_URL, settings.PHABRICATOR_ADMIN_API_KEY
    )
    try:
        result = phab.call_conduit(
            "differential.revision.search",
            constraints={"phids": [phid]},
        )
    except PhabricatorAPIException:
        logger.exception("Failed to resolve revision PHID %s via Conduit.", phid)
        return None

    revisions = (result or {}).get("data") or []
    if not revisions:
        logger.info("No Differential revision found for PHID %s.", phid)
        return None

    return revisions[0]["id"]


def resolve_revision_id(
    revision_object: HarbormasterRevisionObject | None,
) -> int | None:
    """Return the Phabricator revision ID from the webhook `object` payload."""
    if revision_object is None:
        return None

    if revision_object.id is not None:
        return revision_object.id

    if not revision_object.phid:
        return None

    return resolve_revision_phid_to_id(revision_object.phid)


@api.post(
    "/webhook/revision-updated",
    auth=HarbormasterWebhookAuth(),
    response={202: RevisionUpdatedResponse, codes_4xx: ProblemDetail},
)
def revision_updated_webhook(
    request: WSGIRequest,
    body: RevisionUpdatedRequest,
) -> tuple[int, dict]:
    """Queue UPDATE-mode `UpliftJob`s when a tracked source revision is updated.

    Resolves the updated revision from the webhook payload (by PHID via Conduit,
    or by an explicit `id`), then queues one job per eligible parent CREATE job
    (status=LANDED, non-empty `created_revision_ids`, no pending UPDATE already
    in flight) for every `UpliftSubmission` whose `requested_revision_ids`
    contains that revision.
    """
    revision_id = resolve_revision_id(body.object)

    if revision_id is None:
        logger.info("Webhook payload had no resolvable revision; nothing to do.")
        return 202, RevisionUpdatedResponse(revision_id=None, queued_jobs=[])

    logger.info("Webhook fired for D%d.", revision_id)

    submissions = UpliftSubmission.objects.filter(
        requested_revision_ids__contains=[revision_id]
    )

    queued_job_ids: list[int] = []

    with transaction.atomic():
        for submission in submissions:
            create_jobs = submission.uplift_jobs.filter(
                mode=UpliftJobMode.CREATE,
                status=JobStatus.LANDED,
            )

            for parent_job in create_jobs:
                if not parent_job.has_created_revisions:
                    logger.debug(
                        "Skipping UpliftJob %d: no `created_revision_ids`.",
                        parent_job.id,
                    )
                    continue

                in_flight_update_exists = UpliftJob.objects.filter(
                    parent_job=parent_job,
                    status__in=JobStatus.pending(),
                ).exists()
                if in_flight_update_exists:
                    logger.info(
                        "Skipping UpliftJob %d: UPDATE already in flight.",
                        parent_job.id,
                    )
                    continue

                update_job = UpliftJob.objects.create(
                    submission=submission,
                    target_repo=parent_job.target_repo,
                    requester_email=parent_job.requester_email,
                    mode=UpliftJobMode.UPDATE,
                    parent_job=parent_job,
                    status=JobStatus.SUBMITTED,
                )
                parent_revisions = list(parent_job.revisions.all())
                update_job.add_revisions(parent_revisions)
                update_job.sort_revisions(parent_revisions)
                queued_job_ids.append(update_job.id)

                logger.info(
                    "Queued UPDATE UpliftJob %d (parent=%d) for D%d on %s.",
                    update_job.id,
                    parent_job.id,
                    revision_id,
                    parent_job.target_repo.name,
                )

    return 202, RevisionUpdatedResponse(
        revision_id=revision_id,
        queued_jobs=queued_job_ids,
    )
