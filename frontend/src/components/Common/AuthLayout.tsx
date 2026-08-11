import { Activity, Database, ShieldCheck } from "lucide-react"
import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh bg-background lg:grid-cols-[1.08fr_0.92fr]">
      <div className="relative hidden overflow-hidden bg-[oklch(0.095_0.005_55)] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 opacity-50 [background-image:linear-gradient(rgba(249,115,22,.07)_1px,transparent_1px),linear-gradient(90deg,rgba(249,115,22,.07)_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="absolute -right-32 top-16 size-80 rounded-full border border-orange-500/20" />
        <div className="absolute -right-16 top-32 size-48 rounded-full border border-orange-300/15" />
        <div className="relative">
          <Logo variant="full" />
        </div>
        <div className="relative max-w-xl">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-orange-400">
            Operations workspace
          </p>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            One console for your
            <br />
            application operations.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-6 text-white/50">
            Monitor resources, manage access, and keep everyday administration
            moving from a focused control plane.
          </p>
          <div className="mt-10 grid grid-cols-3 gap-3">
            {[
              { icon: Activity, label: "Live status" },
              { icon: Database, label: "Resources" },
              { icon: ShieldCheck, label: "Access control" },
            ].map(({ icon: Icon, label }) => (
              <div
                key={label}
                className="rounded-md border border-white/10 bg-white/5 p-3"
              >
                <Icon className="mb-3 size-4 text-orange-400" />
                <p className="text-xs text-white/70">{label}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-white/30">EvalHub AI Evaluation</p>
      </div>
      <div className="flex flex-col p-6 md:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">
            <div className="mb-8 lg:hidden">
              <Logo variant="full" />
            </div>
            <div className="console-surface p-6 sm:p-8">{children}</div>
            <p className="mt-5 text-center text-xs text-muted-foreground">
              Secure operations workspace
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
