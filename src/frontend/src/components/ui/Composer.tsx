import { MessageForm, type MessageFormProps } from "../base/index.ts";
import "./Button.css";
import "./Composer.css";

export type ComposerProps = Omit<MessageFormProps, "classNames">;

// Sticky message bar at the bottom of the screen with the pear send button.
export function Composer(props: ComposerProps) {
  return <MessageForm {...props} classNames={{ root: "composer", input: "composer-input", submit: "stock primary" }} />;
}
