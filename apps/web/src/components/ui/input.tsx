import { type InputHTMLAttributes, forwardRef } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-medium uppercase tracking-wide text-ink-muted"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`
            block w-full rounded-lg border px-3 py-2.5 text-sm
            bg-surface text-ink
            placeholder:text-ink-faint
            focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent
            transition-colors duration-150
            disabled:opacity-50 disabled:cursor-not-allowed
            ${
              error
                ? 'border-negative focus:ring-negative/40 focus:border-negative'
                : 'border-line-strong'
            }
            ${className}
          `}
          {...props}
        />
        {error && (
          <p className="text-xs text-negative">{error}</p>
        )}
        {helperText && !error && (
          <p className="text-xs text-ink-faint">{helperText}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
