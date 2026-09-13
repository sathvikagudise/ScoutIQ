import type { ValidationErrorItem } from "./types";

/**
 * Centralized API base URL. Comes from the environment (build-time config),
 * never hardcoded in components. Empty means same-origin relative URLs — the
 * Vite dev proxy forwards `/api` and `/health` to the backend.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** Typed error thrown by every client call. All error parsing is centralised here. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function findDetail(body: unknown, status: number): string {
  if (isRecord(body) && typeof body.detail === "string") {
    return body.detail;
  }
  if (isRecord(body) && Array.isArray(body.detail)) {
    const items = body.detail as ValidationErrorItem[];
    const messages = items
      .map((item) => item.msg ?? "Invalid value")
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  switch (status) {
    case 404:
      return "The requested resource was not found.";
    case 409:
      return "The request conflicts with the current state of the resource.";
    case 422:
      return "The request could not be validated.";
    default:
      return `The backend returned an unexpected response (HTTP ${status}).`;
  }
}

async function jsonBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** Perform a JSON API request. Throws ApiError on any failure. */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      null,
      `Network error: could not reach the backend at ${
        API_BASE_URL || "the local API proxy"
      }. Is the backend running?`,
    );
  }

  const body = await jsonBody(response);

  if (!response.ok) {
    throw new ApiError(response.status, body, findDetail(body, response.status));
  }

  return body as T;
}

/** POST a JSON body and decode a JSON response. */
export function postJson<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}