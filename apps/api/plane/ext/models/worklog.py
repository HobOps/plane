# Copyright (c) 2026-present Maciej Szymczak and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# Module imports
from plane.db.models.project import ProjectBaseModel

# A single entry may not exceed 24 hours; longer work is logged as multiple
# entries. Stored in minutes — the UI parses "2h 30m" style input.
# HobOps: the minimum is 0 because Plane Cloud has 0-minute entries to import.
MIN_WORKLOG_MINUTES = 0
MAX_WORKLOG_MINUTES = 24 * 60
MAX_WORKLOG_DESCRIPTION_LENGTH = 5000


class IssueWorkLog(ProjectBaseModel):
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="worklogs")
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="worklogs",
    )
    duration = models.PositiveIntegerField(
        validators=[MinValueValidator(MIN_WORKLOG_MINUTES), MaxValueValidator(MAX_WORKLOG_MINUTES)],
        help_text="Logged time in minutes",
    )
    description = models.TextField(blank=True, max_length=MAX_WORKLOG_DESCRIPTION_LENGTH)
    # HobOps: the date of the work, as Plane Cloud has it.
    logged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the work was done. Null when unknown: entries from before Plane Cloud added the field.",
    )

    class Meta:
        verbose_name = "Issue Work Log"
        verbose_name_plural = "Issue Work Logs"
        db_table = "ext_issue_worklogs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["issue"]),
            models.Index(fields=["project", "logged_by"]),
            models.Index(fields=["workspace", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(duration__gte=MIN_WORKLOG_MINUTES, duration__lte=MAX_WORKLOG_MINUTES),
                name="ext_issue_worklog_duration_range",
            )
        ]

    def __str__(self):
        return f"{self.issue_id} {self.duration}m"
