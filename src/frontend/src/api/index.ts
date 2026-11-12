// Backend calls. http/ is the generic client; one file per business domain on top of it.
export { CHAT_ERROR_MESSAGES, ChatError, chatErrorMessage, checkHealth, sendChat } from "./chat.ts";
export { HttpError } from "./http/index.ts";
export type * from "./types/index.ts"; // backend contract (request / response shapes)
