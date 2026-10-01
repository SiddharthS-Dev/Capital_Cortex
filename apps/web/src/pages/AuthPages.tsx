import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { userManager } from "@/lib/auth";

export function CallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return; // StrictMode double-invoke: the code can only be exchanged once
    done.current = true;
    userManager
      .signinRedirectCallback()
      .then((u) => navigate((u.state as { returnTo?: string } | undefined)?.returnTo ?? "/", { replace: true }))
      .catch((e: Error) => setError(e.message));
  }, [navigate]);
  return (
    <div className="flex h-full items-center justify-center p-6 text-sm">
      {error ? (
        <div className="space-y-2 text-center">
          <p className="font-semibold text-destructive">Sign-in failed</p>
          <p className="text-muted-foreground">{error}</p>
          <Link to="/" className="text-primary underline">Try again</Link>
        </div>
      ) : (
        <span className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Completing sign-in…</span>
      )}
    </div>
  );
}

export function NotFound() {
  return (
    <div className="p-10 text-center">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <Link to="/" className="text-sm text-primary underline">Back to Command Center</Link>
    </div>
  );
}
