/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Timer } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TIssueActivityComment } from "@plane/types";
// components
import { IssueActivityBlockComponent } from "@/components/issues/issue-detail/issue-activity/activity/actions";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";

type TIssueActivityWorklog = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  activityComment: TIssueActivityComment;
  ends?: "top" | "bottom";
};

export const IssueActivityWorklog = observer(function IssueActivityWorklog(props: TIssueActivityWorklog) {
  const { activityComment, ends } = props;
  // i18n
  const { t } = useTranslation();
  // store hooks
  const {
    activity: { getActivityById },
  } = useIssueDetail();
  // derived values
  const activity = getActivityById(activityComment.id);

  if (!activity) return <></>;

  return (
    <IssueActivityBlockComponent
      icon={<Timer size={14} className="text-secondary" aria-hidden="true" />}
      activityId={activityComment.id}
      ends={ends}
    >
      {activity.verb === "created" ? (
        <>
          {t("worklog.activity.logged")} <span className="font-medium text-primary">{activity.new_value}</span>
        </>
      ) : activity.verb === "updated" ? (
        <>
          {t("worklog.activity.updated_from")}{" "}
          <span className="font-medium text-primary">{activity.old_value}</span> {t("worklog.activity.to")}{" "}
          <span className="font-medium text-primary">{activity.new_value}</span>
        </>
      ) : (
        <>
          {t("worklog.activity.removed")} <span className="font-medium text-primary">{activity.old_value}</span>
        </>
      )}
    </IssueActivityBlockComponent>
  );
});
