import { cn } from "@/lib/utils";

const Logo = ({ className }: { className?: string }) => {
  return (
    <div className={cn("flex items-baseline leading-none", className)}>
      <span className="tag text-[1.6rem] tracking-tight">
        put you <span className="ink-pink">on.</span>
      </span>
    </div>
  );
};

export default Logo;
