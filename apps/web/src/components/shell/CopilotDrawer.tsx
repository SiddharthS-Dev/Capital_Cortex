import * as Dialog from "@radix-ui/react-dialog";
import { Sparkles, X } from "lucide-react";
import { CopilotChat, useCopilotSession } from "@/components/copilot/Copilot";
import { useUI } from "@/store/ui";

/** Right-side Capital Copilot drawer, available on every page: grounded, cited Q&A over the Capital Knowledge
 * Graph. The conversation lives here (always mounted), so it survives closing the drawer but not a reload. */
export function CopilotDrawer() {
  const open = useUI((s) => s.copilotOpen);
  const setOpen = useUI((s) => s.setCopilotOpen);
  const session = useCopilotSession();
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/20" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l bg-card shadow-2xl">
          <div className="flex h-14 items-center gap-2 border-b px-4">
            <Sparkles className="size-4 text-primary" aria-hidden />
            <Dialog.Title className="flex-1 text-sm font-semibold">Capital Copilot</Dialog.Title>
            <Dialog.Close className="rounded p-1 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close Copilot"><X className="size-4" /></Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Grounded Q&A over the Capital Knowledge Graph. Every answer carries citations; ungrounded questions are refused.</Dialog.Description>
          <CopilotChat session={session} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
