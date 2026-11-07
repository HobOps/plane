/**
 * Copyright (c) 2026-present Maciej Szymczak and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Mirrors the server-side cap (24h per entry).
export const MAX_WORKLOG_MINUTES = 24 * 60;
export const MAX_WORKLOG_DESCRIPTION_LENGTH = 5000;

// Mirrors the backend project roles allowed to read confidential worklog data.
const WORKLOG_READER_ROLES = new Set([20, 15]);

export function canViewWorklogsForRole(role: number | undefined): boolean {
  return role !== undefined && WORKLOG_READER_ROLES.has(role);
}

export function formatWorklogDuration(minutes: number): string {
  const total = Math.max(0, Math.floor(minutes || 0));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours && rest) return `${hours}h ${rest}m`;
  if (hours) return `${hours}h`;
  return `${rest}m`;
}

/**
 * Parses a human duration into minutes.
 * Accepts "2h 30m", "2h30m", "2h", "30m", "1.5h" and plain minutes ("90").
 * Returns null when the input cannot be parsed. Zero is valid (HobOps: Plane Cloud has
 * 0-minute entries, and the API takes them).
 */
export function parseWorklogDuration(input: string): number | null {
  const value = input.trim().toLowerCase();
  if (!value) return null;
  if (/^\d+$/.test(value)) {
    return parseInt(value, 10);
  }
  const match = value.match(/^(?:(\d+(?:[.,]\d+)?)\s*h)?\s*(?:(\d+)\s*m(?:in)?s?)?$/);
  if (!match || (match[1] === undefined && match[2] === undefined)) return null;
  const hours = match[1] ? parseFloat(match[1].replace(",", ".")) : 0;
  const mins = match[2] ? parseInt(match[2], 10) : 0;
  return Math.round(hours * 60 + mins);
}

// HobOps: the date of the work. The API stores logged_at as a datetime; like Plane Cloud,
// the fork keeps it at 12:00 UTC of that day, so the date reads the same in almost every time zone.

/** Today in the browser's time zone, as YYYY-MM-DD. */
export function todayISODate(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

/** The logged_at value for a YYYY-MM-DD date. */
export function loggedAtFromDate(date: string): string {
  return `${date}T12:00:00Z`;
}

/** The YYYY-MM-DD date of a logged_at value, in UTC. */
export function dateFromLoggedAt(loggedAt: string | null | undefined): string | undefined {
  if (!loggedAt) return undefined;
  const parsed = new Date(loggedAt);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString().slice(0, 10);
}

/** A work date is a YYYY-MM-DD date that is not in the future. */
export function isValidWorkDate(date: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= todayISODate();
}
