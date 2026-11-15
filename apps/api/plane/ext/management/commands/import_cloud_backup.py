# Copyright (c) 2026-present HobOps and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Import a Plane Cloud workspace from an API v1 backup tree.

The backup is a directory of JSON files, one per API v1 endpoint, plus the
attachment files (see FORK.md, "Importing a Plane Cloud workspace"):

    workspace/{members,pages}.json  workspace/pages/<id>.json  workspace/assets/<id>.<ext>
    projects/<IDENT>/{project,members,states,labels,cycles,archived-cycles,modules,
                      archived-modules,views,pages,issues}.json
    projects/<IDENT>/{cycle-issues,module-issues}/<id>.json  projects/<IDENT>/pages/<id>.json
    projects/<IDENT>/issues/<seq>/{comments,activities,links,relations,worklogs,
                                   issue-attachments}.json  .../files/<asset id>

Rows keep the ids, sequence numbers, authors and timestamps they had in Cloud,
which the public API cannot do (created_by and sequence_id are read-only there).
Everything is written with bulk upserts keyed on the id, so the command can be
run again over the same instance, or with a newer backup, without duplicating
anything. Rows edited in the instance since the previous run are overwritten.

The command is a dry run unless --commit is given: it does the whole import
inside a transaction, checks the result against the backup and rolls back.
"""

import base64
import glob
import json
import mimetypes
import os
import re
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager

from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.html import strip_tags
from django.utils.text import slugify

from plane.db.models import (
    Cycle,
    CycleIssue,
    Description,
    FileAsset,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueLink,
    IssueRelation,
    IssueSequence,
    IssueView,
    Label,
    Module,
    ModuleIssue,
    ModuleMember,
    Page,
    Profile,
    Project,
    ProjectIdentifier,
    ProjectMember,
    ProjectPage,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.ext.models import IssueWorkLog
from plane.ext.models.worklog import MAX_WORKLOG_MINUTES, MIN_WORKLOG_MINUTES

NAMESPACE = uuid.UUID("6f1f3a52-2f0c-4d2e-9d53-7a1c5f0a9b11")
EMBED_RE = re.compile(r'<image-component[^>]*?\ssrc="([0-9a-f-]{36})"')
RELATION_TYPES = {
    # key in the API response -> (relation_type, the listed issue is `related_issue`)
    "blocked_by": ("blocked_by", True),
    "start_before": ("start_before", True),
    "finish_before": ("finish_before", True),
    "relates_to": ("relates_to", None),
    "duplicate": ("duplicate", None),
}


def derived_id(*parts):
    """Stable id for rows the API does not expose an id for (memberships, links between rows)."""
    return str(uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)))


@contextmanager
def keep_timestamps(model):
    """Let bulk_create write created_at/updated_at from the backup instead of the current time."""
    changed = []
    for field in model._meta.concrete_fields:
        for attr in ("auto_now", "auto_now_add"):
            if getattr(field, attr, False):
                setattr(field, attr, False)
                changed.append((field, attr))
    try:
        yield
    finally:
        for field, attr in changed:
            setattr(field, attr, True)


class Command(BaseCommand):
    help = "Import a Plane Cloud workspace from an API v1 backup tree (dry run unless --commit)"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Root of the backup tree")
        parser.add_argument("--commit", action="store_true", help="Write the import. Without it, roll back")
        parser.add_argument("--workspace-slug", default="hobops")
        parser.add_argument("--workspace-name", default="HobOps")
        parser.add_argument("--owner-email", help="Workspace owner; needed when the workspace does not exist yet")
        parser.add_argument(
            "--wiki-project",
            help="Identifier of the project that receives the workspace-level (wiki) pages, "
            "which the community edition has no place for. Without it they are imported without a project",
        )
        parser.add_argument("--skip-files", action="store_true", help="Do not upload attachments to the storage")
        parser.add_argument("--report", help="Write the report as JSON to this file")

    # ------------------------------------------------------------------ helpers

    def load(self, *parts, default=None):
        path = os.path.join(self.root, *parts)
        if not os.path.exists(path):
            return default
        with open(path) as handle:
            data = json.load(handle)
        if isinstance(data, dict) and "__error__" in data:
            self.note("unreadable in the backup", "/".join(parts))
            return default
        return data

    def note(self, kind, detail):
        self.notes[kind].append(str(detail))

    def user(self, value):
        """Every user id the backup mentions ends up existing: see ensure_users()."""
        if value is None:
            return None
        value = str(value)
        self.user_ids.add(value)
        return value

    def build(self, model, data, **overrides):
        """Map an API object onto the concrete fields of `model`. Returns None if a required FK dangles."""
        row = {}
        for field in model._meta.concrete_fields:
            if field.attname in overrides:
                row[field.attname] = overrides[field.attname]
                continue
            if field.name in data:
                value = data[field.name]
            elif field.attname in data:
                value = data[field.attname]
            else:
                continue
            if field.is_relation:
                target = field.related_model
                if value is not None:
                    value = str(value)
                    if target is User:
                        value = self.user(value)
                    elif target not in self.known or value not in self.known[target]:
                        self.dangling[f"{model.__name__}.{field.name}"] += 1
                        value = None
                if value is None and not field.null:
                    self.note(f"skipped {model.__name__}: no {field.name}", data.get("id"))
                    return None
                row[field.attname] = value
                continue
            if value is None:
                if field.null:
                    row[field.attname] = None
                continue  # else: let the model default apply
            if isinstance(field, models.DateTimeField):
                value = parse_datetime(value) if isinstance(value, str) else value
            elif isinstance(field, models.DateField):
                value = parse_date(value[:10]) if isinstance(value, str) else value
            elif isinstance(field, models.BinaryField):
                value = base64.b64decode(value) if isinstance(value, str) else value
            elif isinstance(field, (models.IntegerField, models.FloatField)) and isinstance(value, str):
                value = field.to_python(value)
            row[field.attname] = value
        return row

    def upsert(self, model, rows, label=None):
        rows = [row for row in rows if row is not None]
        label = label or model.__name__
        if not rows:
            self.stats[label] = {"backup": 0, "created": 0, "updated": 0}
            return
        deduped = {}
        for row in rows:
            deduped[str(row["id"])] = row
        rows = list(deduped.values())
        # keep_timestamps() switches auto_now off, so rows the backup has no dates for need them set here.
        for row in rows:
            if row.get("created_at") is None:
                row["created_at"] = self.started
            if row.get("updated_at") is None:
                row["updated_at"] = row["created_at"]
        manager = model._base_manager
        ids = [row["id"] for row in rows]
        existing = 0
        for start in range(0, len(ids), 2000):
            existing += manager.filter(pk__in=ids[start : start + 2000]).count()
        with keep_timestamps(model):
            # Rows with the same set of columns go together, so a missing key keeps meaning "model default".
            groups = defaultdict(list)
            for row in rows:
                groups[frozenset(row)].append(model(**row))
            for columns, objects in groups.items():
                fields = [f.name for f in model._meta.concrete_fields if f.attname in columns and f.attname != "id"]
                manager.bulk_create(
                    objects, batch_size=500, update_conflicts=True, unique_fields=["id"], update_fields=fields
                )
        self.stats[label] = {"backup": len(rows), "created": len(rows) - existing, "updated": existing}

    def upsert_pairs(self, model, rows, left, right, label=None):
        """Membership-like rows: one live row per (left, right). Skip pairs that already exist under another id."""
        rows = list({str(row["id"]): row for row in rows if row is not None}.values())
        by_id = {
            str(pk): pair
            for pk, *pair in model._base_manager.filter(deleted_at__isnull=True)
            .filter(**{f"{left}__in": {row[left] for row in rows}})
            .values_list("id", left, right)
        }
        taken = {(str(a), str(b)) for pk, (a, b) in by_id.items()}
        keep = []
        for row in rows:
            pair = (str(row[left]), str(row[right]))
            if str(row["id"]) in by_id or pair not in taken:
                keep.append(row)
                taken.add(pair)
        self.upsert(model, keep, label)
        self.stats[label or model.__name__]["backup"] = len(rows)

    def audit(self, data, fallback_user=None, **extra):
        row = {
            "created_at": parse_datetime(data["created_at"]) if data.get("created_at") else None,
            "updated_at": parse_datetime(data.get("updated_at") or data["created_at"])
            if data.get("created_at")
            else None,
            "created_by_id": self.user(data.get("created_by") or fallback_user),
        }
        row.update(extra)
        return {key: value for key, value in row.items() if value is not None or key == "created_by_id"}

    # ------------------------------------------------------------------ import

    def handle(self, *args, **options):
        self.root = options["path"]
        self.options = options
        self.notes = defaultdict(list)
        self.dangling = Counter()
        self.stats = {}
        self.user_ids = set()
        self.files = []  # (local path, storage key, content type)
        self.started = timezone.now()

        projects = self.load("workspace", "projects.json")
        if not projects:
            raise CommandError(f"{self.root}: workspace/projects.json not found or empty")
        self.read_backup(projects)

        with transaction.atomic():
            self.import_all()
            self.ensure_users()
            problems = self.verify()
            if problems:
                for problem in problems:
                    self.stderr.write(self.style.ERROR(problem))
                transaction.set_rollback(True)
                self.print_report()
                raise CommandError("the imported data does not match the backup: rolled back")
            if not options["commit"]:
                transaction.set_rollback(True)

        self.check_files()
        if options["commit"] and not options["skip_files"]:
            self.upload_files()
        self.print_report()
        if options["commit"]:
            self.stdout.write(self.style.SUCCESS("Import committed."))
        else:
            self.stdout.write(self.style.WARNING("Dry run: nothing was written. Run again with --commit."))

    def read_backup(self, projects):
        """Load the tree and collect the ids each foreign key is allowed to point at."""
        self.workspace_id = str(projects[0]["workspace"])
        self.members = self.load("workspace", "members.json", default=[])
        self.projects = []
        self.known = {
            Workspace: {self.workspace_id},
            Project: set(),
            State: set(),
            Label: set(),
            Issue: set(),
            Cycle: set(),
            Module: set(),
            IssueComment: set(),
            Description: set(),
            Page: set(),
        }
        for summary in projects:
            ident = summary["identifier"]
            project = {
                "ident": ident,
                "detail": self.load("projects", ident, "project.json") or summary,
                "members": self.load("projects", ident, "members.json", default=[]),
                "states": self.load("projects", ident, "states.json", default=[]),
                "labels": self.load("projects", ident, "labels.json", default=[]),
                "cycles": (self.load("projects", ident, "cycles.json", default=[]) or [])
                + (self.load("projects", ident, "archived-cycles.json", default=[]) or []),
                "modules": (self.load("projects", ident, "modules.json", default=[]) or [])
                + (self.load("projects", ident, "archived-modules.json", default=[]) or []),
                "views": self.load("projects", ident, "views.json", default=[]) or [],
                "issues": self.load("projects", ident, "issues.json", default=[]) or [],
                "pages": [],
                "types": len(self.load("projects", ident, "issue-types.json", default=[]) or []),
            }
            for page in self.load("projects", ident, "pages.json", default=[]) or []:
                project["pages"].append(self.load("projects", ident, "pages", f"{page['id']}.json") or page)
            project["id"] = str(project["detail"]["id"])
            self.projects.append(project)
            self.known[Project].add(project["id"])
            self.known[State].update(str(s["id"]) for s in project["states"])
            self.known[Label].update(str(x["id"]) for x in project["labels"])
            self.known[Issue].update(str(i["id"]) for i in project["issues"])
            self.known[Cycle].update(str(c["id"]) for c in project["cycles"])
            self.known[Module].update(str(m["id"]) for m in project["modules"])
            self.known[Page].update(str(p["id"]) for p in project["pages"])
            # Per-issue files are read now too: comments are a foreign key target of activities.
            for issue in project["issues"]:
                seq = str(issue["sequence_id"])
                issue["_comments"] = self.load("projects", ident, "issues", seq, "comments.json", default=[]) or []
                self.known[IssueComment].update(str(c["id"]) for c in issue["_comments"])
        self.wiki_pages = []
        for page in self.load("workspace", "pages.json", default=[]) or []:
            self.wiki_pages.append(self.load("workspace", "pages", f"{page['id']}.json") or page)
        self.known[Page].update(str(p["id"]) for p in self.wiki_pages)
        self.assets = {}
        for path in glob.glob(os.path.join(self.root, "workspace", "assets", "*")):
            self.assets[os.path.basename(path).split(".")[0]] = path

    def import_all(self):
        self.import_workspace()
        rows = defaultdict(list)
        for project in self.projects:
            self.collect_project(project, rows)
        self.collect_pages(rows)

        self.upsert(Project, rows["project"])
        for row in rows["identifier"]:
            ProjectIdentifier.objects.update_or_create(
                project_id=row["project_id"], defaults={"name": row["name"], "workspace_id": self.workspace_id}
            )
        self.upsert_pairs(ProjectMember, rows["project_member"], "project_id", "member_id")
        self.upsert(State, rows["state"])
        self.upsert(Label, rows["label"])
        self.upsert(Issue, rows["issue"])
        self.upsert_pairs(IssueSequence, rows["sequence"], "project_id", "sequence")
        self.upsert_pairs(IssueAssignee, rows["assignee"], "issue_id", "assignee_id")
        self.upsert_pairs(IssueLabel, rows["issue_label"], "issue_id", "label_id")
        self.upsert(Cycle, rows["cycle"])
        self.upsert_pairs(CycleIssue, rows["cycle_issue"], "cycle_id", "issue_id")
        self.upsert(Module, rows["module"])
        self.upsert_pairs(ModuleMember, rows["module_member"], "module_id", "member_id")
        self.upsert_pairs(ModuleIssue, rows["module_issue"], "issue_id", "module_id")
        self.upsert(Description, rows["description"])
        self.upsert(IssueComment, rows["comment"])
        self.upsert(IssueActivity, rows["activity"])
        self.upsert(IssueLink, rows["link"])
        self.upsert_pairs(IssueRelation, rows["relation"], "issue_id", "related_issue_id")
        self.upsert(IssueWorkLog, rows["worklog"])
        self.upsert(IssueView, rows["view"])
        self.upsert(Page, rows["page"])
        self.upsert_pairs(ProjectPage, rows["project_page"], "project_id", "page_id")
        self.upsert(FileAsset, rows["asset"])

    def import_workspace(self):
        slug = self.options["workspace_slug"]
        workspace = Workspace.objects.filter(pk=self.workspace_id).first()
        clash = Workspace.objects.filter(slug=slug).exclude(pk=self.workspace_id).first()
        if clash:
            raise CommandError(f"a different workspace already uses the slug {slug!r} ({clash.id})")
        if workspace is None:
            owner_email = self.options["owner_email"]
            owner = next((m for m in self.members if m.get("email") == owner_email), None)
            if owner is None:
                raise CommandError("--owner-email must be the email of a member in workspace/members.json")
            created = min(parse_datetime(p["detail"]["created_at"]) for p in self.projects)
            self.upsert(
                Workspace,
                [
                    {
                        "id": self.workspace_id,
                        "name": self.options["workspace_name"],
                        "slug": slug,
                        "owner_id": self.user(owner["id"]),
                        "created_by_id": self.user(owner["id"]),
                        "created_at": created,
                        "updated_at": created,
                    }
                ],
            )
        else:
            self.stats["Workspace"] = {"backup": 1, "created": 0, "updated": 0}
        self.upsert_pairs(
            WorkspaceMember,
            [
                {
                    "id": derived_id("workspace-member", self.workspace_id, member["id"]),
                    "workspace_id": self.workspace_id,
                    "member_id": self.user(member["id"]),
                    "role": int(member["role"]),
                    "is_active": bool(member.get("is_active", True)),
                }
                for member in self.members
            ],
            "workspace_id",
            "member_id",
        )

    def collect_project(self, project, rows):
        ident, pid, detail = project["ident"], project["id"], project["detail"]
        ws = self.workspace_id
        scope = {"workspace_id": ws, "project_id": pid}
        if project["types"]:
            self.note("issue types are not imported (work items keep no type)", f"{ident}: {project['types']} types")

        rows["project"].append(self.build(Project, detail, workspace_id=ws, cover_image_asset_id=None))
        if detail.get("cover_image_asset"):
            self.note("project cover images are not in the backup", ident)
        rows["identifier"].append({"project_id": pid, "name": ident})
        for member in project["members"]:
            rows["project_member"].append(
                {
                    "id": derived_id("project-member", pid, member["id"]),
                    "member_id": self.user(member["id"]),
                    "role": int(member["role"]),
                    "is_active": bool(member.get("is_active", True)),
                    **scope,
                }
            )
        for state in project["states"]:
            rows["state"].append(self.build(State, state, slug=slugify(state["name"])[:100], **scope))
        for label in project["labels"]:
            rows["label"].append(self.build(Label, label, **scope))
        for cycle in project["cycles"]:
            rows["cycle"].append(self.build(Cycle, cycle, **scope))
            for issue in self.load("projects", ident, "cycle-issues", f"{cycle['id']}.json", default=[]) or []:
                if str(issue["id"]) not in self.known[Issue]:
                    self.dangling["CycleIssue.issue"] += 1
                    continue
                rows["cycle_issue"].append(
                    {
                        "id": derived_id("cycle-issue", cycle["id"], issue["id"]),
                        "cycle_id": str(cycle["id"]),
                        "issue_id": str(issue["id"]),
                        **self.audit(cycle),
                        **scope,
                    }
                )
        for module in project["modules"]:
            rows["module"].append(self.build(Module, module, **scope))
            for member in module.get("members") or []:
                rows["module_member"].append(
                    {
                        "id": derived_id("module-member", module["id"], member),
                        "module_id": str(module["id"]),
                        "member_id": self.user(member),
                        **self.audit(module),
                        **scope,
                    }
                )
            for issue in self.load("projects", ident, "module-issues", f"{module['id']}.json", default=[]) or []:
                if str(issue["id"]) not in self.known[Issue]:
                    self.dangling["ModuleIssue.issue"] += 1
                    continue
                rows["module_issue"].append(
                    {
                        "id": derived_id("module-issue", module["id"], issue["id"]),
                        "module_id": str(module["id"]),
                        "issue_id": str(issue["id"]),
                        **self.audit(module),
                        **scope,
                    }
                )
        for view in project["views"]:
            rows["view"].append(self.build(IssueView, {"query": {}, **view}, **scope))
        for issue in project["issues"]:
            self.collect_issue(project, issue, rows)

    def collect_issue(self, project, issue, rows):
        ident, pid = project["ident"], project["id"]
        iid, seq = str(issue["id"]), str(issue["sequence_id"])
        scope = {"workspace_id": self.workspace_id, "project_id": pid}
        html = issue.get("description_html") or "<p></p>"
        rows["issue"].append(
            self.build(
                Issue,
                issue,
                description_html=html,
                description_stripped=issue.get("description_stripped") or strip_tags(html),
                type_id=None,
                estimate_point_id=None,
                **scope,
            )
        )
        rows["sequence"].append(
            {
                "id": derived_id("sequence", iid),
                "issue_id": iid,
                "sequence": issue["sequence_id"],
                **self.audit(issue),
                **scope,
            }
        )
        for assignee in issue.get("assignees") or []:
            rows["assignee"].append(
                {
                    "id": derived_id("assignee", iid, assignee),
                    "issue_id": iid,
                    "assignee_id": self.user(assignee),
                    **self.audit(issue),
                    **scope,
                }
            )
        for label in issue.get("labels") or []:
            if str(label) not in self.known[Label]:
                self.dangling["IssueLabel.label"] += 1
                continue
            rows["issue_label"].append(
                {
                    "id": derived_id("issue-label", iid, label),
                    "issue_id": iid,
                    "label_id": str(label),
                    **self.audit(issue),
                    **scope,
                }
            )
        self.collect_embeds(html, "ISSUE_DESCRIPTION", issue, rows, issue_id=iid, **scope)

        for comment in issue["_comments"]:
            comment_html = comment.get("comment_html") or "<p></p>"
            stripped = comment.get("comment_stripped") or strip_tags(comment_html)
            description_id = str(comment.get("description") or derived_id("comment-description", comment["id"]))
            self.known[Description].add(description_id)
            rows["description"].append(
                {
                    "id": description_id,
                    "description_html": comment_html,
                    "description_stripped": stripped,
                    **self.audit(comment),
                    **scope,
                }
            )
            rows["comment"].append(
                self.build(
                    IssueComment,
                    comment,
                    issue_id=iid,
                    description_id=description_id,
                    comment_html=comment_html,
                    comment_stripped=stripped,
                    **scope,
                )
            )
            self.collect_embeds(
                comment_html, "COMMENT_DESCRIPTION", comment, rows, issue_id=iid, comment_id=str(comment["id"]), **scope
            )
        folder = ("projects", ident, "issues", seq)
        for activity in self.load(*folder, "activities.json", default=[]) or []:
            rows["activity"].append(self.build(IssueActivity, activity, issue_id=iid, **scope))
        for link in self.load(*folder, "links.json", default=[]) or []:
            rows["link"].append(self.build(IssueLink, link, issue_id=iid, **scope))
        for worklog in self.load(*folder, "worklogs.json", default=[]) or []:
            if not MIN_WORKLOG_MINUTES <= worklog["duration"] <= MAX_WORKLOG_MINUTES:
                self.note("skipped IssueWorkLog: duration out of range", f"{ident}-{seq} {worklog['id']}")
                continue
            rows["worklog"].append(self.build(IssueWorkLog, worklog, issue_id=iid, **scope))
        relations = self.load(*folder, "relations.json", default={}) or {}
        for key, (relation_type, _) in RELATION_TYPES.items():
            for other in relations.get(key) or []:
                other = str(other["id"] if isinstance(other, dict) else other)
                if other not in self.known[Issue]:
                    self.dangling["IssueRelation.related_issue"] += 1
                    continue
                if key in ("relates_to", "duplicate"):
                    # Listed from both sides: keep one row per pair.
                    first, second = sorted((iid, other))
                else:
                    first, second = iid, other
                rows["relation"].append(
                    {
                        "id": derived_id("relation", relation_type, first, second),
                        "issue_id": first,
                        "related_issue_id": second,
                        "relation_type": relation_type,
                        **self.audit(issue),
                        **scope,
                    }
                )
        for attachment in self.load(*folder, "issue-attachments.json", default=[]) or []:
            rows["asset"].append(
                self.build(
                    FileAsset, attachment, issue_id=iid, draft_issue_id=None, comment_id=None, page_id=None, **scope
                )
            )
            content_type = (attachment.get("attributes") or {}).get("type") or "application/octet-stream"
            self.files.append(
                (os.path.join(self.root, *folder, "files", str(attachment["id"])), attachment["asset"], content_type)
            )

    def collect_embeds(self, html, entity_type, owner, rows, **refs):
        """Images pasted in a description or comment: the HTML only carries the asset id."""
        for asset_id in set(EMBED_RE.findall(html or "")):
            path = self.assets.get(asset_id)
            if path is None:
                self.note("embedded image not in the backup", f"{asset_id} ({entity_type} {owner.get('id')})")
                continue
            name = os.path.basename(path)
            key = f"{self.workspace_id}/{uuid.UUID(asset_id).hex}-{name}"
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            size = os.path.getsize(path)
            rows["asset"].append(
                {
                    "id": asset_id,
                    "asset": key,
                    "attributes": {"name": name, "type": content_type, "size": size},
                    "size": size,
                    "entity_type": entity_type,
                    "is_uploaded": True,
                    **self.audit(owner, fallback_user=owner.get("owned_by")),
                    **refs,
                }
            )
            self.files.append((path, key, content_type))

    def collect_pages(self, rows):
        wiki_project = None
        if self.options["wiki_project"]:
            wiki_project = next((p["id"] for p in self.projects if p["ident"] == self.options["wiki_project"]), None)
            if wiki_project is None:
                raise CommandError(f"--wiki-project: no project {self.options['wiki_project']!r} in the backup")
        pages = [(page, [str(p) for p in page.get("projects") or []]) for p in self.projects for page in p["pages"]]
        for page in self.wiki_pages:
            projects = [wiki_project] if wiki_project else []
            if not projects:
                self.note("workspace page imported without a project (not visible in the UI)", page.get("name"))
            pages.append((page, projects))
        seen = set()
        for page, projects in pages:
            if page["id"] in seen:
                continue
            seen.add(page["id"])
            data = dict(page)
            if not isinstance(data.get("description_json"), dict):
                data.pop("description_json", None)
            data.setdefault("created_by", data.get("owned_by"))
            rows["page"].append(
                self.build(Page, data, workspace_id=self.workspace_id, is_global=not projects, parent_id=None)
            )
            for project_id in projects:
                if project_id not in self.known[Project]:
                    continue
                rows["project_page"].append(
                    {
                        "id": derived_id("project-page", project_id, page["id"]),
                        "project_id": project_id,
                        "page_id": str(page["id"]),
                        "workspace_id": self.workspace_id,
                        **self.audit(data),
                    }
                )
            self.collect_embeds(
                data.get("description_html"),
                "PAGE_DESCRIPTION",
                data,
                rows,
                page_id=str(page["id"]),
                workspace_id=self.workspace_id,
                project_id=projects[0] if projects else None,
            )

    def ensure_users(self):
        """Create the accounts the backup refers to and the instance does not have yet."""
        members = {str(m["id"]): m for m in self.members}
        existing = {str(u.id): u for u in User.objects.filter(pk__in=self.user_ids)}
        created = []
        for user_id in sorted(self.user_ids):
            member = members.get(user_id)
            if user_id in existing:
                if member and member.get("email") and existing[user_id].email != member["email"].lower():
                    raise CommandError(
                        f"user {user_id} is {existing[user_id].email} here but {member['email']} in the backup"
                    )
                continue
            if member:
                email = (member.get("email") or "").lower() or f"{user_id}@import.invalid"
                if User.objects.filter(email=email).exists():
                    raise CommandError(f"{email} already has an account with another id: cannot keep {user_id}")
                fields = {
                    "email": email,
                    "first_name": member.get("first_name") or "",
                    "last_name": member.get("last_name") or "",
                    "display_name": member.get("display_name") or email.split("@")[0],
                    "is_bot": bool(member.get("is_bot")),
                    "is_active": bool(member.get("is_active", True)),
                }
            else:
                # Someone who left the workspace: their work stays attributed, the account cannot sign in.
                fields = {
                    "email": f"former-member-{user_id[:8]}@import.invalid",
                    "display_name": f"Former member {user_id[:8]}",
                    "is_active": False,
                }
                self.note("placeholder account for a user who is no longer a member", user_id)
            user = User(id=user_id, username=uuid.uuid4().hex, is_password_autoset=True, **fields)
            user.set_unusable_password()
            user.save()
            Profile.objects.get_or_create(user=user)
            created.append(fields["email"])
        self.stats["User"] = {"backup": len(self.user_ids), "created": len(created), "updated": 0}
        if created:
            self.notes["accounts created (no password: set one with reset_password)"] = created

    # ------------------------------------------------------------------ checks

    def verify(self):
        """Compare what is now in the database with the backup. Returns the list of mismatches."""
        problems = []
        self.projects_report = []
        skipped_worklogs = len(self.notes.get("skipped IssueWorkLog: duration out of range", []))
        for project in self.projects:
            pid, ident = project["id"], project["ident"]
            backup_minutes = backup_entries = 0
            for issue in project["issues"]:
                for worklog in self.load("projects", ident, "issues", str(issue["sequence_id"]), "worklogs.json") or []:
                    if MIN_WORKLOG_MINUTES <= worklog["duration"] <= MAX_WORKLOG_MINUTES:
                        backup_minutes += worklog["duration"]
                        backup_entries += 1
            in_backup = {str(i["id"]) for i in project["issues"]}
            issues = Issue._base_manager.filter(project_id=pid, pk__in=in_backup)
            worklogs = IssueWorkLog.objects.filter(project_id=pid, issue_id__in=in_backup).aggregate(
                entries=Count("id"), minutes=Sum("duration")
            )
            row = {
                "project": ident,
                "issues": issues.count(),
                "issues_backup": len(project["issues"]),
                "max_sequence": issues.aggregate(m=Max("sequence_id"))["m"] or 0,
                "max_sequence_backup": max((i["sequence_id"] for i in project["issues"]), default=0),
                "worklogs": worklogs["entries"],
                "worklogs_backup": backup_entries,
                "minutes": worklogs["minutes"] or 0,
                "minutes_backup": backup_minutes,
            }
            self.projects_report.append(row)
            for key in ("issues", "max_sequence", "worklogs", "minutes"):
                if row[key] != row[f"{key}_backup"]:
                    problems.append(f"{ident}: {key} is {row[key]}, the backup has {row[f'{key}_backup']}")
            mismatched = 0
            by_id = {
                str(pk): (seq, author) for pk, seq, author in issues.values_list("id", "sequence_id", "created_by_id")
            }
            for issue in project["issues"]:
                seq, author = by_id.get(str(issue["id"]), (None, None))
                if seq != issue["sequence_id"] or str(author or "") != str(issue.get("created_by") or ""):
                    mismatched += 1
            if mismatched:
                problems.append(f"{ident}: {mismatched} issues differ in sequence number or author")
        if skipped_worklogs:
            self.note("worklogs left out of the totals above", skipped_worklogs)
        return problems

    def check_files(self):
        missing = [path for path, _, _ in self.files if not os.path.exists(path)]
        for path in missing:
            self.note("attachment file missing in the backup", os.path.relpath(path, self.root))
        self.stats["files"] = {"backup": len(self.files), "missing": len(missing), "uploaded": 0}

    def upload_files(self):
        from plane.settings.storage import S3Storage

        storage = S3Storage()
        uploaded = 0
        for path, key, content_type in self.files:
            if not os.path.exists(path):
                continue
            storage.s3_client.upload_file(
                path, storage.aws_storage_bucket_name, key, ExtraArgs={"ContentType": content_type}
            )
            uploaded += 1
        self.stats["files"]["uploaded"] = uploaded

    def print_report(self):
        report = {
            "committed": bool(self.options["commit"]),
            "workspace": {"id": self.workspace_id, "slug": self.options["workspace_slug"]},
            "rows": self.stats,
            "projects": getattr(self, "projects_report", []),
            "dangling_references_set_to_null": dict(self.dangling),
            "notes": {kind: items for kind, items in self.notes.items()},
        }
        if self.options["report"]:
            with open(self.options["report"], "w") as handle:
                json.dump(report, handle, indent=1, default=str)
        self.stdout.write(f"{'rows':<16}{'backup':>8}{'created':>9}{'updated':>9}")
        for label, stat in self.stats.items():
            if label == "files":
                continue
            self.stdout.write(f"{label:<16}{stat['backup']:>8}{stat['created']:>9}{stat['updated']:>9}")
        files = self.stats.get("files", {})
        self.stdout.write(
            f"files: {files.get('backup', 0)} in the backup, {files.get('missing', 0)} missing, "
            f"{files.get('uploaded', 0)} uploaded"
        )
        self.stdout.write(f"\n{'project':<11}{'issues':>7}{'max seq':>9}{'worklogs':>10}{'minutes':>9}")
        totals = Counter()
        for row in getattr(self, "projects_report", []):
            self.stdout.write(
                f"{row['project']:<11}{row['issues']:>7}{row['max_sequence']:>9}{row['worklogs']:>10}{row['minutes']:>9}"
            )
            for key in ("issues", "worklogs", "minutes"):
                totals[key] += row[key]
        self.stdout.write(f"{'TOTAL':<11}{totals['issues']:>7}{'':>9}{totals['worklogs']:>10}{totals['minutes']:>9}")
        if self.dangling:
            self.stdout.write("\nReferences to rows that are not in the backup (set to null or left out):")
            for key, count in sorted(self.dangling.items()):
                self.stdout.write(f"  {key}: {count}")
        for kind, items in self.notes.items():
            shown = ", ".join(str(item) for item in items[:8]) + (" ..." if len(items) > 8 else "")
            self.stdout.write(f"\n{kind} ({len(items)}): {shown}")
