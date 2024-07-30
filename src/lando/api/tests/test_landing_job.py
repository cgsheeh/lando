import pytest

from lando.main.models.landing_job import LandingJob, LandingJobStatus


@pytest.fixture
def landing_job(db):
    def _landing_job(status, requester_email="tuser@example.com"):
        job = LandingJob(
            status=status,
            revision_to_diff_id={},
            revision_order=[],
            requester_email=requester_email,
            repository_name="",
        )
        job.save()
        return job

    return _landing_job


@pytest.mark.skip
def test_cancel_landing_job_cancels_when_submitted(client, landing_job, auth0_mock):
    """Test happy path; cancelling a job that has not started yet."""
    job = landing_job(LandingJobStatus.SUBMITTED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.json["id"] == job.id
    assert job.status == LandingJobStatus.CANCELLED


@pytest.mark.skip
def test_cancel_landing_job_cancels_when_deferred(client, landing_job, auth0_mock):
    """Test happy path; cancelling a job that has been deferred."""
    job = landing_job(LandingJobStatus.DEFERRED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.json["id"] == job.id
    assert job.status == LandingJobStatus.CANCELLED


@pytest.mark.skip
def test_cancel_landing_job_fails_in_progress(client, landing_job, auth0_mock):
    """Test trying to cancel a job that is in progress fails."""
    job = landing_job(LandingJobStatus.IN_PROGRESS)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["detail"] == (
        "Landing job status (LandingJobStatus.IN_PROGRESS) does not allow cancelling."
    )
    assert job.status == LandingJobStatus.IN_PROGRESS


@pytest.mark.skip
def test_cancel_landing_job_fails_not_owner(client, landing_job, auth0_mock):
    """Test trying to cancel a job that is created by a different user."""
    job = landing_job(LandingJobStatus.SUBMITTED, "anotheruser@example.org")
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 403
    assert response.json["detail"] == ("User not authorized to update landing job 1")
    assert job.status == LandingJobStatus.SUBMITTED


@pytest.mark.skip
def test_cancel_landing_job_fails_not_found(client, landing_job, auth0_mock):
    """Test trying to cancel a job that does not exist."""
    response = client.put(
        "/landing_jobs/1",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ("A landing job with ID 1 was not found.")


@pytest.mark.skip
def test_cancel_landing_job_fails_bad_input(client, landing_job, auth0_mock):
    """Test trying to send an invalid status to the update endpoint."""
    job = landing_job(LandingJobStatus.SUBMITTED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.IN_PROGRESS.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["detail"] == (
        "'IN_PROGRESS' is not one of ['CANCELLED'] - 'status'"
    )
    assert job.status == LandingJobStatus.SUBMITTED


@pytest.mark.django_db
def test_landing_job_acquire_job_job_queue_query():
    REPO_NAME = "test-repo"
    jobs = [
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"1": 1},
            revision_order=["1"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"2": 2},
            revision_order=["2"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"3": 3},
            revision_order=["3"],
        ),
    ]
    for job in jobs:
        job.save()
    # Queue order should match the order the jobs were created in.

    for qjob, job in zip(
        LandingJob.job_queue_query(repository_names=[REPO_NAME]), jobs, strict=False
    ):
        assert qjob.id == job.id

    # Update the last job to be in progress and mark the middle job to be
    # cancelled so that the queue changes.
    jobs[2].status = LandingJobStatus.IN_PROGRESS
    jobs[1].status = LandingJobStatus.CANCELLED

    for job in jobs:
        job.save()
    # The now IN_PROGRESS job should be first, and the cancelled job should
    # not appear in the queue.
    queue_items = LandingJob.job_queue_query(
        repository_names=[REPO_NAME], grace_seconds=0
    ).all()
    assert len(queue_items) == 2
    assert queue_items[0].id == jobs[2].id
    assert queue_items[1].id == jobs[0].id
    assert jobs[1] not in queue_items
