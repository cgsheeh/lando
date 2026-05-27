from lando.api.legacy.email import (
    make_uplift_failure_email,
    make_uplift_success_email,
)
from lando.utils.const import UPLIFT_DOCS_URL

FAILURE_EXPECTED_BODY = f"""
Your uplift request for firefox-beta did not complete successfully.

WHAT TO DO NEXT:

Visit your original revision page to see clear resolution instructions:
https://lando.test/D456/

On this page, click the "Show resolution steps" button to see the exact
commands you need to run to resolve merge conflicts and submit your uplift.

HOW TO RESOLVE:

Most uplift failures are due to merge conflicts. To resolve:
1. Pull the latest changes for firefox-beta
2. Resolve any merge conflicts locally
3. Submit a new uplift request using `moz-phab uplift`

Once you have created a new uplift Phabricator revision, you can use the
"Reuse Previous Assessment" button to reuse your previously submitted
uplift assessment form with the new revision.

For detailed step-by-step instructions, see {UPLIFT_DOCS_URL}

TECHNICAL DETAILS:

Job details: https://lando/jobs/1

Reason for failure:
moz-phab uplift exited with code 2
""".strip()


def test_make_uplift_failure_email():
    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
        [123, 456],
    )

    assert email.subject == "Lando: Uplift for firefox-beta failed (D456)"
    assert email.body == FAILURE_EXPECTED_BODY


SUCCESS_EXPECTED_BODY = """
Your uplift request for firefox-esr finished successfully.

Requested revisions:
- D123
- D456

Lando created the following revisions:
- D1234
- D5678

You can review the full job details at https://lando/jobs/123.

Thank you for keeping the uplift train moving!
""".strip()


def test_make_uplift_success_email():
    email = make_uplift_success_email(
        "user@example.com",
        "firefox-esr",
        "https://lando/jobs/123",
        [1234, 5678],
        [123, 456],
    )

    assert email.subject == "Lando: Uplift for firefox-esr succeeded (D456)"
    assert email.body == SUCCESS_EXPECTED_BODY


UPDATE_FAILURE_EXPECTED_BODY = f"""
Lando tried to automatically refresh your existing uplift revisions for
firefox-beta because the source revision was updated, but the refresh
did not complete successfully.

YOUR EXISTING UPLIFT REVISIONS WERE NOT UPDATED. The following uplift
revisions on Phabricator now lag behind the source revision and need to
be updated out-of-band (Lando will not retry this automatically):

- D200
- D201

WHAT TO DO NEXT:

Pull the latest firefox-beta branch locally, re-apply the updated
source patch, resolve any merge conflicts, and run `moz-phab submit`
against the target revisions above to bring them back in sync.

For detailed step-by-step instructions, see {UPLIFT_DOCS_URL}

TECHNICAL DETAILS:

Job details: https://lando/jobs/9

Reason for failure:
patch conflict
""".strip()


def test_make_uplift_failure_email_update_mode():
    """UPDATE-mode failure email should describe the out-of-band recovery path."""
    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/9",
        "patch conflict",
        [100, 101],
        is_update=True,
        target_revision_ids=[200, 201],
    )

    assert email.subject == (
        "Lando: Auto-refresh of uplift for firefox-beta failed (D201)"
    ), "UPDATE-mode failure subject should reference the target revision tip."
    assert email.body == UPDATE_FAILURE_EXPECTED_BODY, (
        "UPDATE-mode failure body should list the target revisions and the "
        "out-of-band recovery steps."
    )
