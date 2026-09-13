import { postJson, request } from "./client";
import type { User, UserLogin, UserRegister } from "./types";

/** Create an account and start a session. Returns the new user. */
export function registerUser(payload: UserRegister): Promise<User> {
  return postJson<User>("/api/auth/register", payload);
}

/** Sign in and start a session. Returns the current user. */
export function loginUser(payload: UserLogin): Promise<User> {
  return postJson<User>("/api/auth/login", payload);
}

/** Revoke the server-side session. No content on success. */
export function logoutUser(): Promise<void> {
  return postJson<void>("/api/auth/logout", {});
}

/** Resolve the current user from the active session, if any. */
export function getMe(): Promise<User> {
  return request<User>("/api/auth/me");
}