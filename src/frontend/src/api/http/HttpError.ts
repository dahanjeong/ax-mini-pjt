import { isAxiosError } from "axios";
import type { HttpErrorKind } from "./types.ts";

// One error type for every failed request, whatever the transport said.
export class HttpError extends Error {
  readonly kind: HttpErrorKind;
  readonly status: number | null; // HTTP status when the server answered
  readonly data: unknown; // response body when the server answered

  constructor(kind: HttpErrorKind, status: number | null = null, data: unknown = undefined, message?: string) {
    super(message ?? (status !== null ? `HTTP ${status}` : kind));
    this.name = "HttpError";
    this.kind = kind;
    this.status = status;
    this.data = data;
  }

  static from(error: unknown): HttpError {
    if (error instanceof HttpError) return error;
    if (isAxiosError(error)) {
      if (error.response) return new HttpError("http", error.response.status, error.response.data, error.message);
      if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") return new HttpError("timeout", null, undefined, error.message);
      return new HttpError("network", null, undefined, error.message);
    }
    return new HttpError("network", null, undefined, error instanceof Error ? error.message : String(error));
  }
}
