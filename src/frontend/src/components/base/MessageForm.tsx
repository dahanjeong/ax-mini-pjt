import type { ReactNode, Ref } from "react";
import { Button } from "./Button.tsx";
import { TextField } from "./TextField.tsx";

export interface MessageFormProps {
  value: string;
  onValueChange: (value: string) => void;
  onSend: (text: string) => void;
  busy?: boolean; // a send is in flight: submitting is blocked, the input stays usable
  submitLabel: ReactNode;
  inputLabel: string;
  placeholder?: string;
  maxLength?: number;
  inputRef?: Ref<HTMLInputElement>;
  classNames?: { root?: string; input?: string; submit?: string };
}

// Unstyled one-line message form: text field + send button.
// Blocks empty / whitespace-only sends and sends while busy.
export function MessageForm({
  value, onValueChange, onSend, busy = false, submitLabel, inputLabel, placeholder, maxLength, inputRef, classNames = {},
}: MessageFormProps) {
  const canSend = !busy && value.trim() !== "";
  return (
    <form
      className={classNames.root}
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSend(value);
      }}
    >
      {/* not disabled while busy: a disabled input drops focus */}
      <TextField
        ref={inputRef}
        className={classNames.input}
        value={value}
        onValueChange={onValueChange}
        placeholder={placeholder}
        maxLength={maxLength}
        aria-label={inputLabel}
        aria-busy={busy}
      />
      <Button type="submit" className={classNames.submit} disabled={!canSend}>
        {submitLabel}
      </Button>
    </form>
  );
}
