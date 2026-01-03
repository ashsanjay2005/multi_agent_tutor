import { Loader2 } from 'lucide-react';

export function LoadingView() {
  return (
    <div className="flex flex-col items-center justify-center h-[400px] space-y-4">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="text-sm text-muted-foreground">Analyzing your problem...</p>
    </div>
  );
}


