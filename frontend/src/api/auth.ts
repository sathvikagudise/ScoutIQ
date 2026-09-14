import { postJson, request } from "./client";
import type { AuthResponse, User, UserLogin, UserRegister } from "./types";

/** Create an account and start a session. Returns a fresh bearer token + user. */
export function registerUser(payload: UserRegister): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/register", payload);
}

/** Sign in and start a session. Returns a fresh bearer token + user. */
export function loginUser(payload: UserLogin): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/login", payload);
}

/** Revoke the server-side session. No content on success. */
export function logoutUser(): Promise<void> {
  return postJson<void>("/api/auth/logout", {});
}

/** Resolve the current user from the active session, if any. */
export function getMe(): Promise<User> {
  return request<User>("/api/auth/me");
}