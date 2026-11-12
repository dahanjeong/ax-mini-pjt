// Shapes of the HTTP library layer (no domain knowledge).
import type { AxiosRequestConfig } from "axios";

// Per-call options; the method, url and body are given by the helper itself.
export type RequestConfig = Omit<AxiosRequestConfig, "method" | "url" | "data">;

// network: no response (server down, CORS) · timeout: no response in time · http: non-2xx status
export type HttpErrorKind = "network" | "timeout" | "http";
