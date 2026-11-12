// Run with `npm test`. Error mapping only: no server is called.
import { test } from "node:test";
import assert from "node:assert/strict";
import { AxiosError } from "axios";

import { CHAT_ERROR_MESSAGES, chatErrorMessage } from "./chat.ts";
import { HttpError } from "./http/HttpError.ts";

test("http failures become one HttpError", () => {
  assert.equal(HttpError.from(new AxiosError("down", "ERR_NETWORK")).kind, "network");
  assert.equal(HttpError.from(new AxiosError("slow", "ECONNABORTED")).kind, "timeout");
  const res = { status: 422, data: { detail: "x" } } as never;
  const e = HttpError.from(new AxiosError("bad", "ERR_BAD_REQUEST", undefined, undefined, res));
  assert.equal(e.kind, "http");
  assert.equal(e.status, 422);
});

test("chat error messages", () => {
  assert.equal(chatErrorMessage(new HttpError("network")), CHAT_ERROR_MESSAGES.unreachable);
  assert.equal(chatErrorMessage(new HttpError("http", 422)), CHAT_ERROR_MESSAGES.invalid);
  assert.equal(chatErrorMessage(new HttpError("http", 500)), CHAT_ERROR_MESSAGES.server);
  assert.equal(chatErrorMessage(new HttpError("timeout")), CHAT_ERROR_MESSAGES.server);
});
