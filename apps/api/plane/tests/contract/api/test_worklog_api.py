# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract of the worklog endpoints in api/v1, pinned to Plane Cloud's (see FORK.md, rule 5).

The examples below have the shape of Cloud's responses as read on 2026-11-07: the same
keys in the same order and the same value formats. Their values are made up (rule 6).
"""

import re
from uuid import uuid4

import pytest
from freezegun import freeze_time
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import APIToken, Issue, Project, ProjectMember, State, User, WorkspaceMember
from plane.ext.models import IssueWorkLog

CLOUD_WORKLOG_EXAMPLE = {
    "id": "0b7e6c1d-3f0a-4c59-9e0b-2f6a1d9c4e11",
    "created_at": "2026-11-07T13:59:51.511045Z",
    "updated_at": "2026-11-07T13:59:51.511052Z",
    "description": "Made-up description",
    "duration": 30,
    "logged_at": "2026-11-07T12:00:00Z",
    "created_by": "5c2d9a7e-8b41-4f6e-a0d3-7e9b1c2f4a55",
    "updated_by": None,
    "project_id": "9e4f2b8c-1a6d-4c3e-b7f0-5d8a2c1e9b66",
    "workspace_id": "3a1c7e9f-6b2d-4e8a-9c5f-1d7b3e2a8c77",
    "logged_by": "5c2d9a7e-8b41-4f6e-a0d3-7e9b1c2f4a55",
}
CLOUD_TOTAL_EXAMPLE = {"issue_id": "7d3b9f1e-2c8a-4e6d-b5f9-0a1c3e7d9b88", "duration": 90}
CLOUD_NOT_ENABLED = {"message": "Worklog is not enabled for the project"}
CLOUD_NO_ACCESS = {"detail": "You don't have permission to view this workitem"}
CLOUD_NEGATIVE = {"non_field_errors": ["Duration cannot be negative"]}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
UUID_KEYS = {"id", "created_by", "updated_by", "project_id", "workspace_id", "logged_by"}
DATETIME_KEYS = {"created_at", "updated_at", "logged_at"}

FAMILIES = ["issues", "work-items"]


def assert_cloud_worklog(entry):
    assert list(entry.keys()) == list(CLOUD_WORKLOG_EXAMPLE.keys())
    for key, value in entry.items():
        if value is None:
            assert key in {"updated_by", "logged_at"}, key
        elif key in UUID_KEYS:
            assert UUID_RE.match(value), (key, value)
        elif key in DATETIME_KEYS:
            assert DATETIME_RE.match(value), (key, value)
        else:
            assert isinstance(value, type(CLOUD_WORKLOG_EXAMPLE[key])), (key, value)


@pytest.fixture(autouse=True)
def mock_background_tasks(mocker):
    """Keep the contract independent from the Celery broker."""
    mocker.patch("plane.ext.api.views.issue_activity.delay")
    mocker.patch("plane.db.mixins.soft_delete_related_objects.delay")


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="API Worklogs",
        identifier="APW",
        workspace=workspace,
        created_by=create_user,
        is_time_tracking_enabled=True,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(db, project, workspace):
    return State.objects.create(
        name="Todo", group="unstarted", color="#fff", project=project, workspace=workspace, default=True
    )


@pytest.fixture
def issue(db, project, workspace, state):
    return Issue.objects.create(name="Timed work", project=project, workspace=workspace, state=state)


def make_worklog(author, **fields):
    """An entry saved as a request by its author would save it (created_by set)."""
    worklog = IssueWorkLog(logged_by=author, **fields)
    worklog.save(created_by_id=author.id)
    return worklog


def base(workspace, project):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}"


def worklogs_url(workspace, project, issue, family="issues"):
    return f"{base(workspace, project)}/{family}/{issue.id}/worklogs/"


def key_client(workspace, project, workspace_role=15, project_role=None):
    """An API key client for a new user; project_role None means not a project member."""
    uid = uuid4().hex[:8]
    user = User.objects.create(email=f"api-{uid}@hobops.test", username=f"api_{uid}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=workspace_role, is_active=True)
    if project_role is not None:
        ProjectMember.objects.create(project=project, member=user, role=project_role, is_active=True)
    token = APIToken.objects.create(user=user, label=f"test-{uid}")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token.token)
    return client, user


@pytest.mark.contract
class TestWorklogListAndCreate:
    @pytest.mark.django_db
    @pytest.mark.parametrize("family", FAMILIES)
    def test_list_has_cloud_shape_newest_first(self, api_key_client, workspace, project, issue, create_user, family):
        fields = {"issue": issue, "project": project, "workspace": workspace}
        with freeze_time("2026-11-01 10:00:00"):
            older = make_worklog(create_user, duration=15, **fields)
        with freeze_time("2026-11-02 10:00:00"):
            newer = make_worklog(create_user, duration=45, description="later", **fields)

        response = api_key_client.get(worklogs_url(workspace, project, issue, family))
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert [entry["id"] for entry in response.data] == [str(newer.id), str(older.id)]
        for entry in response.data:
            assert_cloud_worklog(entry)
        assert response.data[0]["project_id"] == str(project.id)
        assert response.data[0]["workspace_id"] == str(workspace.id)

    @pytest.mark.django_db
    @pytest.mark.parametrize("family", FAMILIES)
    def test_create_like_the_mcp_does(self, api_key_client, workspace, project, issue, create_user, family):
        # Plane's MCP server 0.1.5 sends only duration and description.
        with freeze_time("2026-11-06 18:25:00"):
            response = api_key_client.post(
                worklogs_url(workspace, project, issue, family),
                {"duration": 30, "description": "Reviewed the port"},
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert_cloud_worklog(response.data)
        assert response.data["duration"] == 30
        assert response.data["description"] == "Reviewed the port"
        # Cloud fills in the day at 12:00 UTC when logged_at is left out.
        assert response.data["logged_at"] == "2026-11-06T12:00:00Z"
        assert response.data["logged_by"] == str(create_user.id)
        assert response.data["created_by"] == str(create_user.id)
        assert response.data["updated_by"] is None

    @pytest.mark.django_db
    def test_create_keeps_a_given_logged_at(self, api_key_client, workspace, project, issue):
        response = api_key_client.post(
            worklogs_url(workspace, project, issue),
            {"duration": 20, "logged_at": "2026-10-04T08:30:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["logged_at"] == "2026-10-04T08:30:00Z"

    @pytest.mark.django_db
    def test_create_without_duration_is_zero_minutes(self, api_key_client, workspace, project, issue):
        response = api_key_client.post(worklogs_url(workspace, project, issue), {"description": "x"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["duration"] == 0

    @pytest.mark.django_db
    def test_negative_duration_is_rejected_like_cloud(self, api_key_client, workspace, project, issue):
        response = api_key_client.post(worklogs_url(workspace, project, issue), {"duration": -1}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == CLOUD_NEGATIVE
        assert not IssueWorkLog.objects.exists()

    @pytest.mark.django_db
    def test_more_than_a_day_is_rejected(self, api_key_client, workspace, project, issue):
        # Cloud accepts it; this fork keeps the 1,440-minute cap of the model.
        response = api_key_client.post(worklogs_url(workspace, project, issue), {"duration": 1441}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "duration" in response.data
        assert not IssueWorkLog.objects.exists()

    @pytest.mark.django_db
    def test_logged_by_cannot_be_spoofed(self, api_key_client, workspace, project, issue, create_user):
        response = api_key_client.post(
            worklogs_url(workspace, project, issue),
            {"duration": 10, "logged_by": str(uuid4())},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["logged_by"] == str(create_user.id)


@pytest.mark.contract
class TestWorklogUpdateAndDelete:
    @pytest.mark.django_db
    @pytest.mark.parametrize("family", FAMILIES)
    def test_patch_then_delete(self, api_key_client, workspace, project, issue, create_user, family):
        url = worklogs_url(workspace, project, issue, family)
        created = api_key_client.post(url, {"duration": 30, "description": "draft"}, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.data

        patched = api_key_client.patch(
            f"{url}{created.data['id']}/",
            {"duration": 45, "description": "final", "logged_at": "2026-10-04T12:00:00Z"},
            format="json",
        )
        assert patched.status_code == status.HTTP_200_OK, patched.data
        assert_cloud_worklog(patched.data)
        assert patched.data["duration"] == 45
        assert patched.data["description"] == "final"
        assert patched.data["logged_at"] == "2026-10-04T12:00:00Z"
        assert patched.data["updated_by"] == str(create_user.id)

        deleted = api_key_client.delete(f"{url}{created.data['id']}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert api_key_client.get(url).data == []

    @pytest.mark.django_db
    def test_member_cannot_edit_someone_elses_entry(self, api_key_client, workspace, project, issue):
        url = worklogs_url(workspace, project, issue)
        created = api_key_client.post(url, {"duration": 30}, format="json")
        member, _ = key_client(workspace, project, project_role=15)
        assert member.patch(f"{url}{created.data['id']}/", {"duration": 1}, format="json").status_code == 403
        assert member.delete(f"{url}{created.data['id']}/").status_code == 403

    @pytest.mark.django_db
    def test_missing_entry_is_not_found(self, api_key_client, workspace, project, issue):
        url = worklogs_url(workspace, project, issue)
        assert api_key_client.patch(f"{url}{uuid4()}/", {"duration": 1}, format="json").status_code == 404
        assert api_key_client.delete(f"{url}{uuid4()}/").status_code == 404


@pytest.mark.contract
class TestTotalWorklogs:
    @pytest.mark.django_db
    def test_totals_have_cloud_shape_sorted_by_issue(
        self, api_key_client, workspace, project, issue, state, create_user
    ):
        second = Issue.objects.create(name="More work", project=project, workspace=workspace, state=state)
        Issue.objects.create(name="No time logged", project=project, workspace=workspace, state=state)
        for target, minutes in ((issue, 30), (issue, 15), (second, 0), (second, 60)):
            IssueWorkLog.objects.create(
                issue=target, project=project, workspace=workspace, logged_by=create_user, duration=minutes
            )

        response = api_key_client.get(f"{base(workspace, project)}/total-worklogs/")
        assert response.status_code == status.HTTP_200_OK
        assert all(list(row.keys()) == list(CLOUD_TOTAL_EXAMPLE.keys()) for row in response.data)
        expected = sorted([(str(issue.id), 45), (str(second.id), 60)])
        assert [(row["issue_id"], row["duration"]) for row in response.data] == expected


@pytest.mark.contract
class TestWorklogAccess:
    @pytest.mark.django_db
    def test_without_a_key_is_unauthorized(self, workspace, project, issue):
        response = APIClient().get(worklogs_url(workspace, project, issue))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.django_db
    def test_non_member_gets_403(self, workspace, project, issue):
        outsider, _ = key_client(workspace, project, workspace_role=15, project_role=None)
        assert outsider.get(worklogs_url(workspace, project, issue)).status_code == 403
        assert outsider.post(worklogs_url(workspace, project, issue), {"duration": 5}, format="json").status_code == 403
        assert outsider.get(f"{base(workspace, project)}/total-worklogs/").status_code == 403
        assert not IssueWorkLog.objects.exists()

    @pytest.mark.django_db
    def test_guest_gets_403(self, workspace, project, issue):
        guest, _ = key_client(workspace, project, workspace_role=5, project_role=5)
        assert guest.get(worklogs_url(workspace, project, issue)).status_code == 403
        assert guest.post(worklogs_url(workspace, project, issue), {"duration": 5}, format="json").status_code == 403

    @pytest.mark.django_db
    def test_time_tracking_disabled_answers_like_cloud(self, api_key_client, workspace, project, issue):
        project.is_time_tracking_enabled = False
        project.save(update_fields=["is_time_tracking_enabled"])
        for response in (
            api_key_client.get(worklogs_url(workspace, project, issue)),
            api_key_client.post(worklogs_url(workspace, project, issue), {"duration": 5}, format="json"),
            api_key_client.get(f"{base(workspace, project)}/total-worklogs/"),
        ):
            assert response.status_code == status.HTTP_404_NOT_FOUND
            assert response.data == CLOUD_NOT_ENABLED

    @pytest.mark.django_db
    @pytest.mark.parametrize("family", FAMILIES)
    def test_unknown_work_item_answers_like_cloud(self, api_key_client, workspace, project, family):
        url = f"{base(workspace, project)}/{family}/{uuid4()}/worklogs/"
        for response in (api_key_client.get(url), api_key_client.post(url, {"duration": 5}, format="json")):
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert response.data == CLOUD_NO_ACCESS

    @pytest.mark.django_db
    def test_work_item_of_another_project_answers_like_cloud(
        self, api_key_client, workspace, project, issue, create_user
    ):
        other = Project.objects.create(
            name="Other", identifier="OTH", workspace=workspace, created_by=create_user, is_time_tracking_enabled=True
        )
        ProjectMember.objects.create(project=other, member=create_user, role=20, is_active=True)
        response = api_key_client.get(f"{base(workspace, other)}/issues/{issue.id}/worklogs/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data == CLOUD_NO_ACCESS
