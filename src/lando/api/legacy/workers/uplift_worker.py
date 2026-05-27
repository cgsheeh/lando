import json
import logging
import os
import subprocess
import tempfile

from django.conf import settings
from typing_extensions import override

from lando.api.legacy.commit_message import REVISION_URL_TEMPLATE
from lando.api.legacy.revisions import ensure_revisions_from_phabricator
from lando.api.legacy.workers.base import Worker
from lando.main.models import (
    JobAction,
    JobStatus,
    PermanentFailureException,
    Revision,
    TemporaryFailureException,
    WorkerType,
)
from lando.main.models.uplift import UpliftJob, UpliftJobMode, UpliftRevision
from lando.utils.phabricator import PhabricatorClient
from lando.utils.tasks import (
    send_uplift_failure_email,
    send_uplift_success_email,
    set_uplift_request_form_on_revision,
)

logger = logging.getLogger(__name__)


def rewrite_commit_message_for_target(
    commit_message: str, target_revision_id: int
) -> str:
    """Replace the `Differential Revision:` footer to point at `target_revision_id`.

    Steers `moz-phab submit` to update that revision instead of creating a new one.
    """
    kept_lines = [
        line
        for line in commit_message.splitlines()
        if not line.startswith("Differential Revision:")
    ]
    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()

    target_url = f"{settings.PHABRICATOR_URL}/D{target_revision_id}"
    kept_lines.append("")
    kept_lines.append(REVISION_URL_TEMPLATE.format(url=target_url))
    return "\n".join(kept_lines) + "\n"


class UpliftWorker(Worker):
    """Worker to execute uplift jobs.

    This worker runs `UpliftJob`s on enabled repositories.
    These jobs apply patches to respositories and create new Phabricator
    revisions on success.
    """

    job_type = UpliftJob

    worker_type = WorkerType.UPLIFT

    @override
    def refresh_active_repos(self):
        """Override base functionality by not checking treestatus."""
        self.active_repos = self.enabled_repos

    @override
    def run_job(self, job: UpliftJob) -> bool:
        """Run an uplift job."""
        repo = job.target_repo
        submission = job.submission
        user = submission.requested_by
        job_url = job.url()

        requested_revision_ids = submission.requested_revision_ids

        try:
            created_revision_ids = self.apply_and_uplift(job)
        except TemporaryFailureException:
            return False
        except PermanentFailureException:
            self.notify_uplift_failure(
                job, repo.name, job_url, user.email, requested_revision_ids
            )
            return False
        except Exception:  # pragma: no cover - defensive catch
            self.notify_uplift_failure(
                job, repo.name, job_url, user.email, requested_revision_ids
            )
            return False

        self.notify_uplift_success(
            repo.name,
            job_url,
            user.email,
            created_revision_ids,
            requested_revision_ids,
        )
        return True

    def apply_and_uplift(self, job: UpliftJob) -> list[int]:
        """Apply uplift patches and create or refresh target revisions.

        Returns target revision IDs: newly-created revisions for CREATE jobs,
        the parent's `created_revision_ids` (refreshed in place) for UPDATE.
        """
        repo = job.target_repo
        submission = job.submission
        user = submission.requested_by
        scm = repo.scm
        is_update = job.mode == UpliftJobMode.UPDATE
        parent_job = job.parent_job if is_update else None
        target_revision_ids = list(parent_job.created_revision_ids) if is_update else []

        # Refresh source diffs in place so UPDATE jobs apply the latest content.
        if is_update:
            phab = PhabricatorClient(
                settings.PHABRICATOR_URL,
                user.profile.phabricator_api_key,
            )
            ensure_revisions_from_phabricator(phab, submission.requested_revision_ids)

        # Update to the latest commit in the target train.
        base_revision = self.update_repo(repo, job, scm, target_cset=None)

        for index, uplift_revision in enumerate(job.revisions.all()):
            # Default-arg captures this iteration's `index` for the closure.
            def apply_uplift_revision(revision: Revision, idx: int = index):
                """Cherry-pick (CREATE) or apply the patch with a rewritten footer (UPDATE)."""
                commit_message = revision.commit_message

                if is_update:
                    # Footer steers `moz-phab submit` at the existing target.
                    target_id = target_revision_ids[idx]
                    commit_message = rewrite_commit_message_for_target(
                        commit_message, target_id
                    )
                    # Skip cherry-pick: the autoland commit may predate the
                    # developer's latest edits.
                    scm.apply_patch(
                        revision.diff,
                        commit_message,
                        revision.author,
                        revision.timestamp,
                    )
                    return

                commit_id = revision.get_latest_landing_commit_id()
                if commit_id and scm.commit_exists(commit_id):
                    logger.debug(
                        f"Cherry-picking {revision} with commit_id: {commit_id}"
                    )
                    try:
                        scm.cherry_pick_commit(commit_id)
                        return
                    except NotImplementedError:
                        logger.debug(
                            "Cherry-pick not supported for this SCM type. "
                            "Falling back to applying patch."
                        )
                else:
                    logger.debug(
                        f"No landing commit found for {revision}. "
                        f"Falling back to applying patch."
                    )

                scm.apply_patch(
                    revision.diff,
                    commit_message,
                    revision.author,
                    revision.timestamp,
                )

            self.handle_new_commit_failures(
                apply_uplift_revision, repo, job, scm, uplift_revision
            )
            new_commit = scm.describe_commit()
            logger.debug(f"Created new commit {new_commit}")

        if is_update:
            # `moz-phab submit` updated the targets in place; mirror the
            # parent's `created_revision_ids` for email/UI parity.
            self.submit_uplift_updates(
                job, user.profile.phabricator_api_key, base_revision
            )
            job.created_revision_ids = target_revision_ids
            job.status = JobStatus.LANDED
            job.save()
            return target_revision_ids

        result = self.create_uplift_revisions(
            job, user.profile.phabricator_api_key, base_revision
        )

        # Retrieve created revision IDs and tip revision ID.
        commits = result["commits"]
        created_revision_ids = [int(commit["rev_id"]) for commit in commits]
        tip_revision_id = created_revision_ids[-1]

        UpliftRevision.link_revision_to_assessment(
            tip_revision_id, submission.assessment
        )

        # Trigger a Celery task to update the form on Phabricator.
        self.call_task(
            set_uplift_request_form_on_revision,
            tip_revision_id,
            submission.assessment.to_conduit_json_str(),
            user.id,
        )

        job.created_revision_ids = created_revision_ids
        # `LANDED` is the same as "success".
        job.status = JobStatus.LANDED
        job.save()

        return created_revision_ids

    def notify_uplift_success(
        self,
        repo_label: str,
        job_url: str,
        recipient_email: str,
        created_revision_ids: list[int],
        requested_revision_ids: list[int],
    ) -> None:
        """Send an uplift success notification email."""
        self.call_task(
            send_uplift_success_email,
            recipient_email,
            repo_label,
            job_url,
            created_revision_ids,
            requested_revision_ids,
        )

    def notify_uplift_failure(
        self,
        job: UpliftJob,
        repo_label: str,
        job_url: str,
        recipient_email: str,
        requested_revision_ids: list[int],
    ) -> None:
        """Send an uplift failure notification email.

        UPDATE-mode failures use wording that points the requester at the
        stale target revisions to fix by hand.
        """
        is_update = job.mode == UpliftJobMode.UPDATE
        target_revision_ids = (
            list(job.parent_job.created_revision_ids)
            if is_update and job.parent_job is not None
            else None
        )

        self.call_task(
            send_uplift_failure_email,
            recipient_email,
            repo_label,
            job_url,
            job.error,
            requested_revision_ids,
            is_update,
            target_revision_ids,
        )

    def create_uplift_revisions(
        self, job: UpliftJob, api_key: str, base_revision: str
    ) -> dict:
        """Create Phabricator uplift revisions using `moz-phab uplift`."""
        env = os.environ.copy()
        env["MOZPHAB_PHABRICATOR_API_TOKEN"] = api_key

        with tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w+", suffix="json"
        ) as f_output:
            self.run_moz_phab_uplift(job, base_revision, env, f_output.name)

            f_output.seek(0)

            try:
                return json.load(f_output)
            except json.JSONDecodeError as exc:
                message = (
                    "`moz-phab uplift` may have produced revisions on Phabricator but "
                    "failed while returning results. Please check Phabricator for any "
                    "new revisions."
                )
                logger.exception(
                    message,
                    extra={
                        "moz_phab_json_error": exc.msg,
                        "moz_phab_json_position": exc.pos,
                        "moz_phab_json_raw": exc.doc,
                    },
                )
                job.transition_status(JobAction.FAIL, message=message)
                raise PermanentFailureException(message) from exc

    def submit_uplift_updates(
        self, job: UpliftJob, api_key: str, base_revision: str
    ) -> None:
        """Refresh existing target revisions via `moz-phab submit`.

        Each commit's `Differential Revision:` footer (set by the apply step)
        steers `moz-phab` to update the matching revision instead of creating
        a new one.
        """
        env = os.environ.copy()
        env["MOZPHAB_PHABRICATOR_API_TOKEN"] = api_key

        self.run_moz_phab_submit(job, base_revision, env)

    def run_moz_phab_submit(
        self,
        job: UpliftJob,
        base_revision: str,
        env: dict[str, str],
    ) -> None:
        """Invoke `moz-phab submit` to refresh the existing uplift revisions."""
        target_repo = job.target_repo
        try:
            subprocess.run(
                [
                    "moz-phab",
                    "submit",
                    # Use `--yes` to avoid confirmation prompts.
                    "--yes",
                    # Use `--no-rebase` as Lando has already applied
                    # patches to the tip of the target train.
                    "--no-rebase",
                    base_revision,
                    "HEAD",
                ],
                capture_output=True,
                check=True,
                cwd=target_repo.system_path,
                encoding="utf-8",
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            message = "`moz-phab submit` did not complete successfully."
            logger.exception(
                message,
                extra={
                    "returncode": exc.returncode,
                    "command": exc.cmd,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                },
            )
            job.transition_status(JobAction.FAIL, message=message)
            raise PermanentFailureException(message) from exc

    def run_moz_phab_uplift(
        self,
        job: UpliftJob,
        base_revision: str,
        env: dict[str, str],
        output_path: str,
    ) -> None:
        """Invoke `moz-phab uplift` for the given job and capture the output."""
        target_repo = job.target_repo
        try:
            subprocess.run(
                [
                    "moz-phab",
                    "uplift",
                    # Use `--yes` to avoid confirmation prompts.
                    "--yes",
                    # Use `--no-rebase` as Lando has already applied
                    # patches to the tip of the target train.
                    "--no-rebase",
                    "--output-file",
                    output_path,
                    "--train",
                    target_repo.short_name,
                    base_revision,
                    "HEAD",
                ],
                capture_output=True,
                check=True,
                cwd=target_repo.system_path,
                encoding="utf-8",
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            message = "`moz-phab uplift` did not complete successfully."
            logger.exception(
                message,
                extra={
                    "returncode": exc.returncode,
                    "command": exc.cmd,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                },
            )
            job.transition_status(JobAction.FAIL, message=message)
            raise PermanentFailureException(message) from exc
