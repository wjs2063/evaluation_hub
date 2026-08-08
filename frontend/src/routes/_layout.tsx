import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"

import { EnvironmentBadge } from "@/components/Common/EnvironmentBadge"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const pageName = pathname.startsWith("/evaluation-single-turn/live-test")
    ? "Live Test"
    : pathname.startsWith("/evaluation-single-turn/regression")
      ? "Regression Test"
      : pathname.startsWith("/evaluation-single-turn")
        ? "Single-turn Evaluation"
        : pathname.startsWith("/evaluation-multi-turn/live-test")
          ? "Multi-turn Live Test"
          : pathname.startsWith("/evaluation-multi-turn/regression")
            ? "Multi-turn Regression Test"
            : pathname.startsWith("/evaluation-multi-turn")
              ? "Multi-turn Evaluation"
              : pathname.startsWith("/evaluation-rag")
                ? "RAG Test (Coming Soon)"
                : {
                    "/": "Overview",
                    "/evaluations": "Evaluations",
                    "/items": "Items",
                    "/admin": "Users",
                    "/settings": "Settings",
                  }[pathname] || "Console"

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between border-b bg-background/95 px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <div className="h-5 w-px bg-border" />
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <span className="hidden text-muted-foreground sm:inline">
                Workspace
              </span>
              <span className="hidden text-muted-foreground sm:inline">/</span>
              <span className="truncate font-medium">{pageName}</span>
            </div>
          </div>
          <EnvironmentBadge />
        </header>
        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <div className="mx-auto max-w-[1440px]">
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
