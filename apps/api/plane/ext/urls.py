# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Fork API endpoints, mounted under /api/ alongside plane.app.urls.
# Only Hangar's worklog routes are ported (see FORK.md).

from django.urls import path

from plane.ext.views.worklog import (
    IssueWorkLogDetailEndpoint,
    IssueWorkLogsEndpoint,
)

PROJECT_BASE = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(
        f"{PROJECT_BASE}/issues/<uuid:issue_id>/worklogs/",
        IssueWorkLogsEndpoint.as_view(),
        name="issue-worklogs",
    ),
    path(
        f"{PROJECT_BASE}/issues/<uuid:issue_id>/worklogs/<uuid:pk>/",
        IssueWorkLogDetailEndpoint.as_view(),
        name="issue-worklog-detail",
    ),
]
