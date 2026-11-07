# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Mounted under /api/v1/ next to plane.api.urls. Plane Cloud serves the worklogs of a
# work item under both issues/ and work-items/, so both families are here.

from django.urls import path

from plane.ext.api.views import (
    IssueWorkLogDetailAPIEndpoint,
    IssueWorkLogListCreateAPIEndpoint,
    ProjectWorkLogTotalAPIEndpoint,
)

PROJECT_BASE = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(
        f"{PROJECT_BASE}/total-worklogs/",
        ProjectWorkLogTotalAPIEndpoint.as_view(http_method_names=["get"]),
        name="api-project-total-worklogs",
    ),
]

for family in ("issues", "work-items"):
    urlpatterns += [
        path(
            f"{PROJECT_BASE}/{family}/<uuid:issue_id>/worklogs/",
            IssueWorkLogListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
            name=f"api-{family}-worklogs",
        ),
        path(
            f"{PROJECT_BASE}/{family}/<uuid:issue_id>/worklogs/<uuid:pk>/",
            IssueWorkLogDetailAPIEndpoint.as_view(http_method_names=["patch", "delete"]),
            name=f"api-{family}-worklog-detail",
        ),
    ]
