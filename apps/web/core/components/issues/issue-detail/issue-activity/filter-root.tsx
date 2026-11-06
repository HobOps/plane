/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TActivityFilters, TActivityFilterOption } from "@plane/constants";
import { ACTIVITY_FILTER_TYPE_OPTIONS } from "@plane/constants";
// components
import { ActivityFilter } from "@/components/issues/issue-detail/issue-activity";
// Fork (see FORK.md): worklog filter
import { observer } from "mobx-react";
import { EActivityFilterType } from "@plane/constants";
import { useProject } from "@/hooks/store/use-project";

export type TActivityFilterRoot = {
  selectedFilters: TActivityFilters[];
  toggleFilter: (filter: TActivityFilters) => void;
  projectId: string;
  isIntakeIssue?: boolean;
  // Fork (see FORK.md): worklogs
  canViewWorklogs: boolean;
};

// Fork (see FORK.md): an observer that hides the worklog filter where there can be no worklogs
export const ActivityFilterRoot = observer(function ActivityFilterRoot(props: TActivityFilterRoot) {
  const { selectedFilters, toggleFilter, projectId, isIntakeIssue = false, canViewWorklogs } = props;
  // store hooks
  const { getProjectById } = useProject();
  // derived values — the worklog filter only applies where worklogs can exist
  const isTimeTrackingEnabled = Boolean(getProjectById(projectId)?.is_time_tracking_enabled);
  const showWorklogFilter = isTimeTrackingEnabled && canViewWorklogs && !isIntakeIssue;
  const selectedFilterSet = new Set(selectedFilters);

  const filters = Object.entries(ACTIVITY_FILTER_TYPE_OPTIONS).reduce<TActivityFilterOption[]>(
    (options, [key, value]) => {
      if (!showWorklogFilter && key === EActivityFilterType.WORKLOG) return options;
      const filterKey = key as TActivityFilters;
      options.push({
        key: filterKey,
        labelTranslationKey: value.labelTranslationKey,
        isSelected: selectedFilterSet.has(filterKey),
        onClick: () => toggleFilter(filterKey),
      });
      return options;
    },
    []
  );

  return <ActivityFilter selectedFilters={selectedFilters} filterOptions={filters} />;
});
