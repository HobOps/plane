# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Worklogs in the public API (api/v1), with Plane Cloud's routes, fields and responses.

Clients written for Cloud, such as Plane's MCP server, only change the host and the key.
Authentication and the per-key rate limit are upstream's (plane.api); permissions are
the ones of the session API in plane.ext.views.worklog: project admins and members,
not guests, and only in projects with time tracking enabled.
"""

# Python imports
import json
from datetime import datetime, time
from datetime import timezone as dt_timezone

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue
from plane.utils.host import base_host

from plane.ext.api.serializers import IssueWorkLogAPISerializer
from plane.ext.models import IssueWorkLog
from plane.ext.views.worklog import can_modify, time_tracking_enabled


def midday_utc_today():
    """Cloud's logged_at when a client leaves it out: today at 12:00 UTC."""
    today = timezone.now().astimezone(dt_timezone.utc).date()
    return datetime.combine(today, time(12, 0), tzinfo=dt_timezone.utc)


def worklog_not_enabled():
    # Cloud's response for a project without time tracking.
    return Response({"message": "Worklog is not enabled for the project"}, status=status.HTTP_404_NOT_FOUND)


def no_access_to_work_item():
    # Cloud answers a work item that is not in the project, or does not exist, with a 403.
    return Response(
        {"detail": "You don't have permission to view this workitem"},
        status=status.HTTP_403_FORBIDDEN,
    )


def record_activity(request, kind, issue_id, project_id, duration, previous_duration=None):
    issue_activity.delay(
        type=f"worklog.activity.{kind}",
        requested_data=json.dumps({"duration": duration}, cls=DjangoJSONEncoder),
        actor_id=str(request.user.id),
        issue_id=str(issue_id),
        project_id=str(project_id),
        current_instance=(
            json.dumps({"duration": previous_duration}, cls=DjangoJSONEncoder)
            if previous_duration is not None
            else None
        ),
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=base_host(request=request, is_app=True),
    )


class IssueWorkLogListCreateAPIEndpoint(BaseAPIView):
    """GET and POST .../issues/<issue_id>/worklogs/ and .../work-items/<issue_id>/worklogs/."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, issue_id):
        if not time_tracking_enabled(slug, project_id):
            return worklog_not_enabled()
        if not Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).exists():
            return no_access_to_work_item()
        worklogs = IssueWorkLog.objects.filter(
            workspace__slug=slug, project_id=project_id, issue_id=issue_id
        ).order_by("-created_at")
        return Response(IssueWorkLogAPISerializer(worklogs, many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        if not time_tracking_enabled(slug, project_id):
            return worklog_not_enabled()
        issue = Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).first()
        if issue is None:
            return no_access_to_work_item()

        serializer = IssueWorkLogAPISerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        defaults = {}
        if "duration" not in serializer.validated_data:
            defaults["duration"] = 0
        if "logged_at" not in request.data:
            defaults["logged_at"] = midday_utc_today()
        # logged_by is never client-supplied.
        worklog = serializer.save(
            issue=issue,
            project_id=project_id,
            workspace=issue.workspace,
            logged_by=request.user,
            **defaults,
        )
        record_activity(request, "created", issue_id, project_id, worklog.duration)
        return Response(IssueWorkLogAPISerializer(worklog).data, status=status.HTTP_201_CREATED)


class IssueWorkLogDetailAPIEndpoint(BaseAPIView):
    """PATCH and DELETE .../worklogs/<pk>/ under both route families."""

    def get_worklog(self, slug, project_id, issue_id, pk):
        return get_object_or_404(IssueWorkLog, workspace__slug=slug, project_id=project_id, issue_id=issue_id, pk=pk)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, issue_id, pk):
        if not time_tracking_enabled(slug, project_id):
            return worklog_not_enabled()
        if not Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).exists():
            return no_access_to_work_item()
        worklog = self.get_worklog(slug, project_id, issue_id, pk)
        if not can_modify(worklog, request.user, slug, project_id):
            return Response(
                {"error": "Only the author or a project admin can edit this entry"},
                status=status.HTTP_403_FORBIDDEN,
            )
        previous_duration = worklog.duration
        serializer = IssueWorkLogAPISerializer(worklog, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        worklog = serializer.save()
        record_activity(request, "updated", issue_id, project_id, worklog.duration, previous_duration)
        return Response(IssueWorkLogAPISerializer(worklog).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, issue_id, pk):
        if not time_tracking_enabled(slug, project_id):
            return worklog_not_enabled()
        if not Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id).exists():
            return no_access_to_work_item()
        worklog = self.get_worklog(slug, project_id, issue_id, pk)
        if not can_modify(worklog, request.user, slug, project_id):
            return Response(
                {"error": "Only the author or a project admin can delete this entry"},
                status=status.HTTP_403_FORBIDDEN,
            )
        duration = worklog.duration
        worklog.delete()
        record_activity(request, "deleted", issue_id, project_id, duration)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectWorkLogTotalAPIEndpoint(BaseAPIView):
    """GET .../total-worklogs/: minutes per work item, as Cloud returns them."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        if not time_tracking_enabled(slug, project_id):
            return worklog_not_enabled()
        totals = (
            IssueWorkLog.objects.filter(workspace__slug=slug, project_id=project_id, issue__deleted_at__isnull=True)
            .values("issue_id")
            .annotate(duration=Sum("duration"))
            .order_by("issue_id")
        )
        return Response(
            [{"issue_id": str(row["issue_id"]), "duration": row["duration"]} for row in totals],
            status=status.HTTP_200_OK,
        )
