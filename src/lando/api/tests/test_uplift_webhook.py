import hashlib
import hmac
import json

import pytest

from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.main.models.jobs import JobStatus
from lando.main.models.uplift import UpliftJob, UpliftJobMode
from lando.main.scm import SCMType

WEBHOOK_URL = "/api/uplift/webhook/revision-updated"
WEBHOOK_HMAC_KEY = "test-phabricator-hmac-key"


@pytest.fixture
def configured_webhook_secret(db):
    """Set the `PHABRICATOR_WEBHOOK_HMAC_KEY` configuration variable."""
    ConfigurationVariable.set(
        ConfigurationKey.PHABRICATOR_WEBHOOK_HMAC_KEY,
        VariableTypeChoices.STR,
        WEBHOOK_HMAC_KEY,
    )


def sign_body(body: str, key: str = WEBHOOK_HMAC_KEY) -> str:
    """Compute the hex-encoded HMAC-SHA256 signature as Phabricator would."""
    return hmac.new(
        key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def post_webhook(
    client,
    revision_id: int,
    signature: str | None = None,
    send_signature: bool = True,
):
    """POST a Phabricator-shaped payload, signing the body unless told otherwise.

    By default the body is signed with the valid `WEBHOOK_HMAC_KEY`. Pass an
    explicit `signature` to forge a bad one, or `send_signature=False` to omit
    the header entirely.
    """
    body = json.dumps(
        {
            "object": {
                "id": revision_id,
                "phid": f"PHID-DREV-{revision_id}",
            },
        }
    )
    headers = {}
    if send_signature:
        header_value = signature if signature is not None else sign_body(body)
        headers["HTTP_X_PHABRICATOR_WEBHOOK_SIGNATURE"] = header_value
    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        **headers,
    )


@pytest.mark.parametrize(
    "post_kwargs, description",
    [
        ({"send_signature": False}, "missing"),
        ({"signature": "deadbeef"}, "invalid"),
    ],
)
@pytest.mark.django_db
def test_webhook_unauthorized(
    client, configured_webhook_secret, post_kwargs, description
):
    """Requests with a missing or invalid HMAC signature should return 401."""
    response = post_webhook(client, revision_id=1, **post_kwargs)

    assert response.status_code == 401, (
        f"{description} webhook signature should return 401."
    )


@pytest.mark.django_db
def test_webhook_unset_secret_rejects_caller(client):
    """An unset server-side HMAC key should reject all callers."""
    response = post_webhook(client, revision_id=1, signature="anything")

    assert response.status_code == 401, (
        "Unset PHABRICATOR_WEBHOOK_HMAC_KEY should reject all callers."
    )


@pytest.mark.django_db
def test_webhook_no_matching_submission_returns_202_with_empty_jobs(
    client, configured_webhook_secret
):
    """A webhook for a revision Lando has never seen should be a no-op 202."""
    response = post_webhook(client, revision_id=99999)

    assert response.status_code == 202, (
        "Webhook should always succeed (idempotent), even without matching state."
    )
    body = response.json()
    assert body["revision_id"] == 99999, "Response should echo the revision ID."
    assert body["queued_jobs"] == [], (
        "No matching submission should result in no queued jobs."
    )


@pytest.mark.django_db
def test_webhook_queues_update_for_landed_parent(
    client,
    configured_webhook_secret,
    repo_mc,
    user,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
):
    """A LANDED CREATE parent with created_revision_ids should yield one UPDATE job."""
    repo = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    revisions = [create_patch_revision(100, patch=normal_patch(0))]
    parent_job = make_uplift_job_with_revisions(repo, user, revisions)

    parent_job.status = JobStatus.LANDED
    parent_job.created_revision_ids = [200]
    parent_job.save()

    response = post_webhook(client, revision_id=100)

    assert response.status_code == 202, "Successful webhook should return 202."
    body = response.json()
    assert len(body["queued_jobs"]) == 1, (
        "Exactly one UPDATE job should be queued for the LANDED CREATE parent."
    )

    update_job = UpliftJob.objects.get(id=body["queued_jobs"][0])
    assert update_job.mode == UpliftJobMode.UPDATE, (
        "Queued job should be in UPDATE mode."
    )
    assert update_job.parent_job_id == parent_job.id, (
        "Queued job should point back at the LANDED CREATE parent."
    )
    assert update_job.status == JobStatus.SUBMITTED, (
        "Queued job should be SUBMITTED so the worker picks it up."
    )
    assert update_job.target_repo_id == parent_job.target_repo_id, (
        "Queued job should target the same repo as the parent."
    )
    assert list(update_job.revisions.all()) == list(parent_job.revisions.all()), (
        "Queued job should inherit the parent's ordered revisions."
    )


@pytest.mark.django_db
def test_webhook_skips_parents_without_created_revisions(
    client,
    configured_webhook_secret,
    repo_mc,
    user,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
):
    """A LANDED parent with empty created_revision_ids should be skipped."""
    repo = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    revisions = [create_patch_revision(101, patch=normal_patch(0))]
    parent_job = make_uplift_job_with_revisions(repo, user, revisions)

    parent_job.status = JobStatus.LANDED
    parent_job.created_revision_ids = []
    parent_job.save()

    response = post_webhook(client, revision_id=101)

    assert response.status_code == 202, "Webhook should return 202."
    assert response.json()["queued_jobs"] == [], (
        "Parents without `created_revision_ids` should not yield UPDATE jobs."
    )


@pytest.mark.django_db
def test_webhook_skips_failed_parents(
    client,
    configured_webhook_secret,
    repo_mc,
    user,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
):
    """A FAILED CREATE parent should not be auto-updated on source revision changes."""
    repo = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    revisions = [create_patch_revision(102, patch=normal_patch(0))]
    parent_job = make_uplift_job_with_revisions(repo, user, revisions)

    parent_job.status = JobStatus.FAILED
    parent_job.created_revision_ids = []
    parent_job.save()

    response = post_webhook(client, revision_id=102)

    assert response.status_code == 202, "Webhook should return 202."
    assert response.json()["queued_jobs"] == [], (
        "FAILED parents must be retried by hand, not auto-updated."
    )


@pytest.mark.django_db
def test_webhook_debounces_inflight_updates(
    client,
    configured_webhook_secret,
    repo_mc,
    user,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
):
    """A second webhook call should not queue another UPDATE while one is pending."""
    repo = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    revisions = [create_patch_revision(103, patch=normal_patch(0))]
    parent_job = make_uplift_job_with_revisions(repo, user, revisions)

    parent_job.status = JobStatus.LANDED
    parent_job.created_revision_ids = [203]
    parent_job.save()

    first = post_webhook(client, revision_id=103)
    assert first.status_code == 202, "First webhook call should succeed."
    assert len(first.json()["queued_jobs"]) == 1, "First call should queue one job."

    second = post_webhook(client, revision_id=103)
    assert second.status_code == 202, "Second webhook call should still succeed."
    assert second.json()["queued_jobs"] == [], (
        "Second call should debounce while the first UPDATE is still pending."
    )

    assert UpliftJob.objects.filter(parent_job=parent_job).count() == 1, (
        "Only one UPDATE job should exist for the parent."
    )


@pytest.mark.django_db
def test_webhook_queues_one_update_per_target_repo(
    client,
    configured_webhook_secret,
    repo_mc,
    user,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
):
    """A submission with multiple LANDED parents (one per train) should produce one UPDATE each."""
    beta = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    release = repo_mc(SCMType.GIT, name="firefox-release", approval_required=True)
    revisions = [create_patch_revision(104, patch=normal_patch(0))]

    beta_parent = make_uplift_job_with_revisions(beta, user, revisions)
    beta_parent.status = JobStatus.LANDED
    beta_parent.created_revision_ids = [204]
    beta_parent.save()

    # Reuse the same submission so this models a multi-train uplift cleanly.
    release_parent = UpliftJob.objects.create(
        status=JobStatus.LANDED,
        requester_email=user.email,
        target_repo=release,
        submission=beta_parent.submission,
        created_revision_ids=[304],
    )
    release_parent.add_revisions(revisions)
    release_parent.sort_revisions(revisions)

    response = post_webhook(client, revision_id=104)

    assert response.status_code == 202, "Webhook should return 202."
    queued = response.json()["queued_jobs"]
    assert len(queued) == 2, "One UPDATE per LANDED parent should be queued."

    queued_parents = set(
        UpliftJob.objects.filter(id__in=queued).values_list("parent_job_id", flat=True)
    )
    assert queued_parents == {beta_parent.id, release_parent.id}, (
        "Each LANDED parent should have exactly one UPDATE child queued."
    )
