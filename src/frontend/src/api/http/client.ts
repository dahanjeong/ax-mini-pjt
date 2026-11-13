// Library layer: call a method with params, get the response body back.
// Every failure is rethrown as HttpError. Only our own backend is called.
import axios from "axios";
import { HttpError } from "./HttpError.ts";
import type { RequestConfig } from "./types.ts";

// dev (Vite on :5173) -> the local backend; a production build is served by the backend
// itself (Dockerfile / Render), so it calls the same origin
export const API_BASE_URL = import.meta.env?.DEV ? "http://localhost:8000" : "";

// /chat takes 10-20 s (place search, weather, reviews), so leave room
export const DEFAULT_TIMEOUT_MS = 60_000;

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { "Content-Type": "application/json", Accept: "application/json" },
});

async function send<T>(config: RequestConfig & { method: string; url: string; data?: unknown }): Promise<T> {
  try {
    const res = await http.request<T>(config);
    return res.data;
  } catch (e) {
    throw HttpError.from(e);
  }
}

export function get<T>(url: string, config: RequestConfig = {}): Promise<T> {
  return send<T>({ ...config, method: "GET", url });
}

export function del<T>(url: string, config: RequestConfig = {}): Promise<T> {
  return send<T>({ ...config, method: "DELETE", url });
}

export function post<T, B = unknown>(url: string, body?: B, config: RequestConfig = {}): Promise<T> {
  return send<T>({ ...config, method: "POST", url, data: body });
}

export function put<T, B = unknown>(url: string, body?: B, config: RequestConfig = {}): Promise<T> {
  return send<T>({ ...config, method: "PUT", url, data: body });
}

export function patch<T, B = unknown>(url: string, body?: B, config: RequestConfig = {}): Promise<T> {
  return send<T>({ ...config, method: "PATCH", url, data: body });
}
