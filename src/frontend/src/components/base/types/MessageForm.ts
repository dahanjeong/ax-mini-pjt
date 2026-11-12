import type { ReactNode, Ref } from "react";
import type { ClassNames, ValueProps } from "./commonType.ts";
import type { TextFieldProps } from "./TextField.ts";

export type MessageFormProps = ValueProps &
  Pick<TextFieldProps, "placeholder" | "maxLength"> & {
    onSend: (text: string) => void;
    busy?: boolean; // a send is in flight: submitting is blocked, the input stays usable
    submitLabel: ReactNode;
    inputLabel: string;
    inputRef?: Ref<HTMLInputElement>;
    classNames?: ClassNames<"root" | "input" | "submit">;
  };
