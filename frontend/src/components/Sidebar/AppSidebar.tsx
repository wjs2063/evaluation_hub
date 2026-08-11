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
      <SidebarHeader className="border-b border-sidebar-border px-4 py-3">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="py-3">
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border">
        <div className="mx-2 flex h-8 items-center gap-2 px-2">
          <span
            className={cn(
              "size-2 rounded-full",
              backendHealth.isPending && "animate-pulse bg-amber-500",
              isApiConnected && "bg-emerald-500",
              isApiUnavailable && "bg-destructive",
            )}
          />
          <p className="truncate text-[11px] text-sidebar-foreground/55">
            {apiStatus}
          </p>
        </div>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
