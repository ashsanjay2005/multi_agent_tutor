import * as React from 'react';
import { cn } from '@/lib/utils';

interface RadioGroupContextValue {
  value: string;
  onValueChange: (value: string) => void;
}

const RadioGroupContext = React.createContext<RadioGroupContextValue | undefined>(undefined);

const RadioGroup = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    value: string;
    onValueChange: (value: string) => void;
  }
>(({ className, value, onValueChange, ...props }, ref) => (
  <RadioGroupContext.Provider value={{ value, onValueChange }}>
    <div ref={ref} className={cn('grid gap-2', className)} role="radiogroup" {...props} />
  </RadioGroupContext.Provider>
));
RadioGroup.displayName = 'RadioGroup';

const RadioGroupItem = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { value: string }
>(({ className, value, children, ...props }, ref) => {
  const context = React.useContext(RadioGroupContext);
  if (!context) throw new Error('RadioGroupItem must be used within RadioGroup');

  const isChecked = context.value === value;

  return (
    <button
      ref={ref}
      type="button"
      role="radio"
      aria-checked={isChecked}
      className={cn(
        'flex items-center gap-3 rounded-md border border-input p-3 text-left transition-colors hover:bg-accent hover:text-accent-foreground',
        isChecked && 'border-primary bg-primary/10',
        className
      )}
      onClick={() => context.onValueChange(value)}
      {...props}
    >
      <div
        className={cn(
          'h-4 w-4 rounded-full border-2 flex items-center justify-center',
          isChecked ? 'border-primary' : 'border-muted-foreground'
        )}
      >
        {isChecked && <div className="h-2 w-2 rounded-full bg-primary" />}
      </div>
      <div className="flex-1">{children}</div>
    </button>
  );
});
RadioGroupItem.displayName = 'RadioGroupItem';

export { RadioGroup, RadioGroupItem };


