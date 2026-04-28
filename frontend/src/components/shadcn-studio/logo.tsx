import LogoSvg from "@/assets/svg/logo";
import { cn } from "@/lib/utils";

const Logo = ({ className }: { className?: string }) => {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <LogoSvg className="size-7" />
      <div className="flex flex-col leading-none">
        <span className="label text-[0.62rem] tracking-[0.3em] opacity-70">
          DISPATCH N°
        </span>
        <span className="font-display text-[1.35rem] leading-[0.9] -tracking-[0.02em]">
          Put You On
        </span>
      </div>
    </div>
  );
};

export default Logo;
