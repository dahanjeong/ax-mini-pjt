import type { CalloutProps as BaseCalloutProps } from "../../base/index.ts";
import type { WithTone } from "./commonType.ts";

export type CalloutTone = "notice" | "warning"; // notice: sand, for information; warning: coral, for caution

export type CalloutProps = WithTone<BaseCalloutProps, CalloutTone>;
