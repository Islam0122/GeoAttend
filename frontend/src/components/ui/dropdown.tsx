import * as DM from "@radix-ui/react-dropdown-menu";
import * as React from "react";
import { cn } from "@/lib/utils";

export const DropdownMenu = DM.Root;
export const DropdownMenuTrigger = DM.Trigger;
export function DropdownMenuContent({ className, ...p }: React.ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content sideOffset={6} className={cn("z-[1100] min-w-44 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg", className)} {...p} />
    </DM.Portal>
  );
}
export function DropdownMenuItem({ className, ...p }: React.ComponentProps<typeof DM.Item>) {
  return <DM.Item className={cn("flex cursor-pointer select-none items-center gap-2 rounded-md px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-muted [&_svg]:size-4", className)} {...p} />;
}
export const DropdownMenuSeparator = () => <DM.Separator className="my-1 h-px bg-border" />;
export function DropdownMenuLabel({ className, ...p }: React.ComponentProps<typeof DM.Label>) {
  return <DM.Label className={cn("px-2.5 py-1.5 text-xs text-muted-foreground", className)} {...p} />;
}
