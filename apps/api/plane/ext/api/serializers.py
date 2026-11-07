# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.ext.models import IssueWorkLog
from plane.ext.models.worklog import MAX_WORKLOG_MINUTES


class IssueWorkLogAPISerializer(serializers.ModelSerializer):
    """A worklog as Plane Cloud's api/v1 returns it: same fields, in the same order.

    As in Cloud, a missing duration means 0 minutes and a negative one is a
    non-field error. Unlike Cloud, which accepts any length, an entry cannot
    exceed MAX_WORKLOG_MINUTES; the model enforces it.
    """

    duration = serializers.IntegerField(required=False)
    project_id = serializers.UUIDField(read_only=True)
    workspace_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = IssueWorkLog
        fields = [
            "id",
            "created_at",
            "updated_at",
            "description",
            "duration",
            "logged_at",
            "created_by",
            "updated_by",
            "project_id",
            "workspace_id",
            "logged_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "project_id",
            "workspace_id",
            "logged_by",
        ]

    def validate(self, attrs):
        duration = attrs.get("duration")
        if duration is not None and duration < 0:
            raise serializers.ValidationError("Duration cannot be negative")
        if duration is not None and duration > MAX_WORKLOG_MINUTES:
            raise serializers.ValidationError(
                {"duration": [f"A single entry cannot exceed {MAX_WORKLOG_MINUTES} minutes."]}
            )
        return attrs
