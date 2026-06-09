import { ProfileContent } from "@/components/profile-content";

export default function ProfilePage() {
  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      <ProfileContent footer={<ProfileFooter />} />
    </div>
  );
}

// Static end-of-list row. Server-rendered and handed to the client island so it
// stays off the client bundle.
function ProfileFooter() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pt-8">
      <span className="label text-white/40">End of list</span>
      <a href="/dashboard" className="group inline-flex items-baseline gap-3">
        <span className="label text-[color:var(--pink)]">Next</span>
        <span className="spray-link display text-3xl md:text-4xl text-white">
          Today&rsquo;s drop →
        </span>
      </a>
    </div>
  );
}
