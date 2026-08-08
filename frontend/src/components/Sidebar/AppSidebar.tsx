import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import useBackendHealth from "@/hooks/useBackendHealth"
import { cn } from "@/lib/utils"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { title: "Overview", path: "/", section: "Monitor" },
  {
    title: "Evaluations",
    path: "/evaluations",
    section: "Evaluate",
    children: [
      {
        title: "Single-turn",
        path: "/evaluation-single-turn",
        children: [
          {
            title: "Live Test",
            path: "/evaluation-single-turn/live-test",
          },
          {
            title: "Regression Test",
            path: "/evaluation-single-turn/regression",
          },
        ],
      },
      {
        title: "Multi-turn",
        path: "/evaluation-multi-turn",
        children: [
          {
            title: "Live Test",
            path: "/evaluation-multi-turn/live-test",
          },
          {
            title: "Regression Test",
            path: "/evaluation-multi-turn/regression",
          },
        ],
      },
    ],
  },
  { title: "Items", path: "/items", section: "Manage" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const backendHealth = useBackendHealth()
  const isApiConnected = backendHealth.isSuccess && backendHealth.data === true
  const isApiUnavailable = !backendHealth.isPending && !isApiConnected
  const apiStatus = backendHealth.isPending
    ? "Checking API"
    : isApiConnected
      ? "API connected"
      : "API unavailable"

  const items = currentUser?.is_superuser
    ? [
        ...baseItems,
        {
          title: "Users",
          path: "/admin",
          section: "Administration",
        },
      ]
    : baseItems

  return (
    <Sidebar collapsible="offcanvas" className="border-sidebar-border">
      <SidebarHeader className="border-b border-sidebar-border px-4 py-4">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="py-3">
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border">
        <div className="mx-2 flex items-center gap-2 rounded-full border border-sidebar-border bg-white/[0.04] px-3 py-2">
          <span
            className={cn(
              "size-2 rounded-full",
              backendHealth.isPending && "animate-pulse bg-amber-500",
              isApiConnected && "bg-emerald-500",
              isApiUnavailable && "bg-destructive",
            )}
          />
          <div className="min-w-0">
            <p className="text-[11px] font-medium text-sidebar-foreground">
              {apiStatus}
            </p>
            <p className="text-[9px] text-sidebar-foreground/45">
              {isApiConnected
                ? "Live health check passed"
                : backendHealth.isPending
                  ? "Running live health check"
                  : "Live health check failed"}
            </p>
          </div>
        </div>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
