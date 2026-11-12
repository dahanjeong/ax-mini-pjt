import { cx, MessageForm } from "../base/index.ts";
import type { ComposerProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/Button.css";
import "./styles/Composer.css";

// Sticky message bar at the bottom of the screen with the pear send button.
export function Composer({ className, ...rest }: ComposerProps) {
  return (
    <MessageForm
      {...rest}
      classNames={{ root: cx("sticky-bar", "composer", className), input: "composer-input", submit: "stock primary" }}
    />
  );
}
