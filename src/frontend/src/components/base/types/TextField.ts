import type { InputHTMLAttributes } from "react";
import type { ValueProps } from "./commonType.ts";

// the input's own value/onChange are replaced by ValueProps
export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & ValueProps;
