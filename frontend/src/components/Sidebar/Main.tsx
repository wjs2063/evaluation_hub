import { Link as RouterLink, useRouterState } from "@tanstack/react-router"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { ItemIndicator } from "./ItemIndicator"

export type SubItem = {
  title: string
  path: string
  children?: SubItem[]
}

export type Item = SubItem & {
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

  const isActiveOrDescendant = (item: SubItem) =>
    currentPath === item.path ||
    item.children?.some(isActiveOrDescendant) === true

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
                const hasActiveChild = item.children?.some(isActiveOrDescendant)

                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      tooltip={item.title}
                      isActive={isActive || hasActiveChild}
                      className="h-9 rounded-full! px-2.5 text-sidebar-foreground/70 data-[active=true]:bg-cyan-400/12 data-[active=true]:text-cyan-300"
                      asChild
                    >
                      <RouterLink to={item.path} onClick={handleMenuClick}>
                        <ItemIndicator active={isActive || hasActiveChild} />
                        <span>{item.title}</span>
                      </RouterLink>
                    </SidebarMenuButton>
                    {item.children && (
                      <SidebarMenuSub>
                        {item.children.map((child) => (
                          <SidebarMenuSubItem key={child.title}>
                            <SidebarMenuSubButton
                              isActive={isActiveOrDescendant(child)}
                              className="rounded-full!"
                              asChild
                            >
                              <RouterLink
                                to={child.path}
                                onClick={handleMenuClick}
                              >
                                <ItemIndicator
                                  active={isActiveOrDescendant(child)}
                                />
                                <span>{child.title}</span>
                              </RouterLink>
                            </SidebarMenuSubButton>
                            {child.children && (
                              <SidebarMenuSub className="ml-3">
                                {child.children.map((grandchild) => (
                                  <SidebarMenuSubItem key={grandchild.title}>
                                    <SidebarMenuSubButton
                                      isActive={isActiveOrDescendant(
                                        grandchild,
                                      )}
                                      className="rounded-full!"
                                      asChild
                                    >
                                      <RouterLink
                                        to={grandchild.path}
                                        onClick={handleMenuClick}
                                      >
                                        <ItemIndicator
                                          active={isActiveOrDescendant(
                                            grandchild,
                                          )}
                                        />
                                        <span>{grandchild.title}</span>
                                      </RouterLink>
                                    </SidebarMenuSubButton>
                                  </SidebarMenuSubItem>
                                ))}
                              </SidebarMenuSub>
                            )}
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    )}
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
