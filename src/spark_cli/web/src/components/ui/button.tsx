import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-display text-sm font-medium transition-colors cursor-pointer"
  + " disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-foreground/90 text-background hover:bg-foreground",
        destructive: "bg-destructive/90 text-destructive-foreground hover:bg-destructive",
        outline: "border border-border bg-transparent text-foreground hover:bg-foreground/7",
        secondary: "bg-foreground/7 text-secondary-foreground hover:bg-foreground/11",
        ghost: "text-muted-foreground hover:bg-foreground/7 hover:text-foreground",
        link: "text-foreground underline-offset-4 hover:underline",
      },
      size: {
        default: "h-8 px-3 py-1.5",
        sm: "h-7 px-2.5 text-xs",
        lg: "h-9 px-4",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
