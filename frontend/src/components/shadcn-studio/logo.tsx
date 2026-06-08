import { cn } from "@/lib/utils";

const Logo = ({ className }: { className?: string }) => {
  return (
    <div className={cn("flex items-baseline gap-2 leading-none", className)}>
      <span className="tag-flat text-[1.55rem] tracking-tight text-white">
        put you{" "}
        <span className="ink-lime">on</span>
        <span className="ink-pink">.</span>
      </span>
    </div>
  );
};

export default Logo;
