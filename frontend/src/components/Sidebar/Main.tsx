import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
  section: string
}

interface MainProps {
  items: Item[]
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  const sections = items.reduce<Record<string, Item[]>>((groups, item) => {
    groups[item.section] = [...(groups[item.section] || []), item]
    return groups
  }, {})

  return (
    <>
      {Object.entries(sections).map(([section, sectionItems]) => (
        <SidebarGroup key={section} className="mb-2">
          <SidebarGroupLabel className="px-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-sidebar-foreground/40">
            {section}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {sectionItems.map((item) => {
                const isActive = currentPath === item.path

                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      tooltip={item.title}
                      isActive={isActive}
                      className="h-9 rounded-md px-2.5 text-sidebar-foreground/70 data-[active=true]:bg-cyan-400/12 data-[active=true]:text-cyan-300"
                      asChild
                    >
                      <RouterLink to={item.path} onClick={handleMenuClick}>
                        <item.icon />
                        <span>{item.title}</span>
                        {isActive && (
                          <span className="ml-auto size-1.5 rounded-full bg-cyan-400" />
                        )}
                      </RouterLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
    </>
  )
}
