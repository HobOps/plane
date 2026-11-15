# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Plane Cloud importer keeps ids, sequence numbers, authors and dates, and can be run again."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from django.core.management import call_command

from plane.db.models import (
    CycleIssue,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRelation,
    IssueSequence,
    ModuleIssue,
    Project,
    ProjectMember,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.ext.models import IssueWorkLog

WORKSPACE = str(uuid4())
PROJECT = str(uuid4())
OWNER = str(uuid4())
FORMER = str(uuid4())
STATE = str(uuid4())
LABEL = str(uuid4())
CYCLE = str(uuid4())
MODULE = str(uuid4())
PARENT = str(uuid4())
CHILD = str(uuid4())
COMMENT = str(uuid4())
WORKLOG = str(uuid4())
CREATED = "2025-03-04T05:06:07.123456Z"
UPDATED = "2025-04-05T06:07:08.654321Z"


def stamp(**fields):
    return {"created_at": CREATED, "updated_at": UPDATED, "created_by": OWNER, "updated_by": None, **fields}


@pytest.fixture
def backup(tmp_path):
    scope = {"workspace": WORKSPACE, "project": PROJECT}
    issue = {"state": STATE, "priority": "high", "description_html": "<p>Hello</p>", "assignees": [], "labels": []}
    tree = {
        "workspace/members.json": [
            {"id": OWNER, "email": "Owner@Example.com", "display_name": "owner", "role": 20, "is_active": True}
        ],
        "workspace/projects.json": [{"id": PROJECT, "identifier": "IMP", "workspace": WORKSPACE}],
        "projects/IMP/project.json": stamp(
            id=PROJECT, name="Imported", identifier="IMP", workspace=WORKSPACE, is_time_tracking_enabled=True
        ),
        "projects/IMP/members.json": [{"id": OWNER, "role": 20, "is_active": True}],
        "projects/IMP/states.json": [stamp(id=STATE, name="Done", color="#000", group="completed", **scope)],
        "projects/IMP/labels.json": [stamp(id=LABEL, name="ops", color="#fff", **scope)],
        "projects/IMP/cycles.json": [stamp(id=CYCLE, name="2025-10", owned_by=OWNER, **scope)],
        "projects/IMP/modules.json": [stamp(id=MODULE, name="Module", members=[], **scope)],
        "projects/IMP/issues.json": [
            # Sequence numbers with a gap, as left by deleted work items, and a child listed before nothing else.
            stamp(id=CHILD, name="Child", sequence_id=7, parent=PARENT, **issue, **scope)
            | {"assignees": [OWNER], "labels": [LABEL], "created_by": FORMER, "completed_at": UPDATED},
            stamp(id=PARENT, name="Parent", sequence_id=3, parent=None, **issue, **scope),
        ],
        f"projects/IMP/cycle-issues/{CYCLE}.json": [{"id": CHILD}],
        f"projects/IMP/module-issues/{MODULE}.json": [{"id": CHILD}, {"id": PARENT}],
        "projects/IMP/issues/7/comments.json": [
            stamp(id=COMMENT, comment_html="<p>Noted</p>", actor=OWNER, issue=CHILD, access="INTERNAL", **scope)
        ],
        "projects/IMP/issues/7/activities.json": [
            stamp(id=str(uuid4()), verb="created", actor=OWNER, issue=CHILD, issue_comment=str(uuid4()), **scope)
        ],
        "projects/IMP/issues/7/worklogs.json": [
            stamp(id=WORKLOG, duration=75, description="ops: work", logged_at=None, logged_by=OWNER),
            stamp(id=str(uuid4()), duration=0, description="", logged_at="2025-04-05T12:00:00Z", logged_by=OWNER),
        ],
        "projects/IMP/issues/7/relations.json": {"blocked_by": [PARENT], "blocking": [], "relates_to": [PARENT]},
        "projects/IMP/issues/3/relations.json": {"blocked_by": [], "blocking": [CHILD], "relates_to": [CHILD]},
    }
    for name, content in tree.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content))
    return str(tmp_path)


def run(backup, *extra):
    call_command("import_cloud_backup", backup, "--owner-email", "Owner@Example.com", "--skip-files", *extra)


@pytest.mark.contract
@pytest.mark.django_db
class TestImportCloudBackup:
    def test_dry_run_writes_nothing(self, backup):
        run(backup)

        assert not Workspace.objects.filter(pk=WORKSPACE).exists()
        assert not Issue.objects.filter(project_id=PROJECT).exists()
        assert not User.objects.filter(pk=OWNER).exists()

    def test_commit_keeps_ids_numbers_authors_and_dates(self, backup):
        run(backup, "--commit")

        workspace = Workspace.objects.get(pk=WORKSPACE)
        assert (workspace.slug, str(workspace.owner_id)) == ("hobops", OWNER)
        assert User.objects.get(pk=OWNER).email == "owner@example.com"
        assert WorkspaceMember.objects.get(workspace=workspace, member_id=OWNER).role == 20
        assert ProjectMember.objects.get(project_id=PROJECT, member_id=OWNER).role == 20
        assert Project.objects.get(pk=PROJECT).is_time_tracking_enabled is True

        child = Issue.objects.get(pk=CHILD)
        assert child.sequence_id == 7
        assert str(child.parent_id) == PARENT
        assert child.created_at == datetime(2025, 3, 4, 5, 6, 7, 123456, tzinfo=timezone.utc)
        assert child.updated_at == datetime(2025, 4, 5, 6, 7, 8, 654321, tzinfo=timezone.utc)
        assert child.completed_at == child.updated_at
        assert child.description_stripped == "Hello"
        # The author left the workspace: the work stays attributed to an account that cannot sign in.
        former = User.objects.get(pk=FORMER)
        assert str(child.created_by_id) == FORMER
        assert former.is_active is False and not former.has_usable_password()
        assert IssueSequence.objects.get(issue=child).sequence == 7
        assert IssueAssignee.objects.filter(issue=child, assignee_id=OWNER).count() == 1
        assert IssueLabel.objects.filter(issue=child, label_id=LABEL).count() == 1
        assert CycleIssue.objects.filter(cycle_id=CYCLE, issue=child).count() == 1
        assert ModuleIssue.objects.filter(module_id=MODULE).count() == 2

        comment = IssueComment.objects.get(pk=COMMENT)
        assert comment.comment_stripped == "Noted"
        assert comment.description.description_html == "<p>Noted</p>"
        assert comment.created_at == child.created_at
        # The comment the activity pointed at is gone from Cloud: the activity stays, without it.
        assert IssueActivity.objects.get(issue=child).issue_comment_id is None

        worklog = IssueWorkLog.objects.get(pk=WORKLOG)
        assert (worklog.duration, worklog.logged_at, str(worklog.logged_by_id)) == (75, None, OWNER)
        assert worklog.created_at == child.created_at
        assert IssueWorkLog.objects.filter(issue=child).count() == 2

        # "blocked_by" and "blocking" are one row seen from both ends, and so is each "relates_to".
        relations = set(IssueRelation.objects.values_list("issue_id", "related_issue_id", "relation_type"))
        assert len(relations) == 2
        assert (child.id, Issue.objects.get(pk=PARENT).id, "blocked_by") in relations

        # A work item created afterwards continues the numbering.
        new = Issue.objects.create(name="New", project_id=PROJECT, workspace_id=WORKSPACE)
        assert new.sequence_id == 8

    def test_second_run_does_not_duplicate(self, backup):
        run(backup, "--commit")
        counts = [
            model.objects.count()
            for model in (User, Issue, IssueSequence, IssueAssignee, IssueComment, IssueWorkLog, IssueRelation)
        ]

        run(backup, "--commit")

        assert counts == [
            model.objects.count()
            for model in (User, Issue, IssueSequence, IssueAssignee, IssueComment, IssueWorkLog, IssueRelation)
        ]
        assert Issue.objects.get(pk=CHILD).created_at == datetime(2025, 3, 4, 5, 6, 7, 123456, tzinfo=timezone.utc)
