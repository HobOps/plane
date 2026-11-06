/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import type { TActivityFilters, TActivityFilterOption } from "@plane/constants";
import { ACTIVITY_FILTER_TYPE_OPTIONS, EActivityFilterType } from "@plane/constants";
// components
import { ActivityFilter } from "@/components/issues/issue-detail/issue-activity";
// hooks
import { useProject } from "@/hooks/store/use-project";

export type TActivityFilterRoot = {
  selectedFilters: TActivityFilters[];
  toggleFilter: (filter: TActivityFilters) => void;
  projectId: string;
  isIntakeIssue?: boolean;
  /** Restricts the options to these filters (e.g. the ones the active activity tab covers). */
  filterKeys?: TActivityFilters[];
  canViewWorklogs: boolean;
};

export const ActivityFilterRoot = observer(function ActivityFilterRoot(props: TActivityFilterRoot) {
  const { selectedFilters, toggleFilter, filterKeys, projectId, isIntakeIssue = false, canViewWorklogs } = props;
  // store hooks
  const { getProjectById } = useProject();
  // derived values — the worklog filter only applies where worklogs can exist
  const isTimeTrackingEnabled = Boolean(getProjectById(projectId)?.is_time_tracking_enabled);
  const showWorklogFilter = isTimeTrackingEnabled && canViewWorklogs && !isIntakeIssue;

  const filterEntries = Object.entries(ACTIVITY_FILTER_TYPE_OPTIONS).filter(([key]) => {
    if (!showWorklogFilter && key === EActivityFilterType.WORKLOG) return false;
    return !filterKeys || filterKeys.includes(key as TActivityFilters);
  });

  const filters: TActivityFilterOption[] = filterEntries.map(([key, value]) => {
    const filterKey = key as TActivityFilters;
    return {
      key: filterKey,
      labelTranslationKey: value.labelTranslationKey,
      isSelected: selectedFilters.includes(filterKey),
      onClick: () => toggleFilter(filterKey),
    };
  });

  return <ActivityFilter selectedFilters={selectedFilters} filterOptions={filters} />;
});
