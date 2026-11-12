import { Button } from "./Button.tsx";
import { TextField } from "./TextField.tsx";
import type { MessageFormProps } from "./types/index.ts";

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
