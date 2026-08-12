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
export type SubItem = {
  title: string
  path: string
  hash?: string
  children?: SubItem[]
}

export type Item = SubItem & {
  section: string
}

interface MainProps {
  items: Item[]
}

function MenuIcon({ active }: { active: boolean }) {
  return (
    <span
      className={
        active
          ? "grid size-5 shrink-0 place-items-center rounded-[4px] border border-primary/60 bg-primary/10"
          : "grid size-5 shrink-0 place-items-center rounded-[4px] border border-sidebar-border bg-white/[0.02]"
      }
    >
      <span
        className={
          active
            ? "size-1.5 rounded-[2px] bg-primary"
            : "size-1.5 rounded-[2px] bg-sidebar-foreground/25"
        }
      />
    </span>
  )
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname
  const currentHash = router.location.hash

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  const sections = items.reduce<Record<string, Item[]>>((groups, item) => {
    groups[item.section] = [...(groups[item.section] || []), item]
    return groups
  }, {})

  const isExactTargetActive = (item: SubItem) =>
    currentPath === item.path &&
    (item.hash ? currentHash === item.hash : currentHash.length === 0)

  const isActiveOrDescendant = (item: SubItem) =>
    isExactTargetActive(item) ||
    item.children?.some(isActiveOrDescendant) === true

  return (
    <>
      {Object.entries(sections).map(([section, sectionItems]) => (
        <SidebarGroup key={section} className="mb-1.5">
          <SidebarGroupLabel className="h-7 px-2 text-[9px] font-medium uppercase tracking-[0.14em] text-sidebar-foreground/30">
            {section}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {sectionItems.map((item) => {
                const isActive = isExactTargetActive(item)
                const hasActiveChild = item.children?.some(isActiveOrDescendant)
                const itemIsActive = isActive || hasActiveChild === true

                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      tooltip={item.title}
                      isActive={itemIsActive}
                      className="h-9 rounded-md px-2 text-sidebar-foreground/65 hover:bg-white/[0.035] data-[active=true]:bg-transparent data-[active=true]:font-medium data-[active=true]:text-sidebar-foreground"
                      asChild
                    >
                      <RouterLink
                        to={item.path}
                        hash={item.hash}
                        onClick={handleMenuClick}
                      >
                        <MenuIcon active={itemIsActive} />
                        <span>{item.title}</span>
                      </RouterLink>
                    </SidebarMenuButton>
                    {item.children && (
                      <SidebarMenuSub className="mx-0 ml-2 gap-0 border-0 px-0 py-0.5">
                        {item.children.map((child) => {
                          const childIsActive = isActiveOrDescendant(child)
                          return (
                            <SidebarMenuSubItem key={child.title}>
                              <SidebarMenuSubButton
                                isActive={childIsActive}
                                className="h-8 translate-x-0 rounded-md px-2 text-sidebar-foreground/60 hover:bg-white/[0.035] data-[active=true]:bg-transparent data-[active=true]:font-medium data-[active=true]:text-sidebar-foreground"
                                asChild
                              >
                                <RouterLink
                                  to={child.path}
                                  hash={child.hash}
                                  onClick={handleMenuClick}
                                >
                                  <MenuIcon active={childIsActive} />
                                  <span>{child.title}</span>
                                </RouterLink>
                              </SidebarMenuSubButton>
                              {child.children && (
                                <SidebarMenuSub className="mx-0 ml-4 gap-0 border-0 px-0 py-0.5">
                                  {child.children.map((grandchild) => {
                                    const grandchildIsActive =
                                      isActiveOrDescendant(grandchild)
                                    return (
                                      <SidebarMenuSubItem
                                        key={grandchild.title}
                                      >
                                        <SidebarMenuSubButton
                                          isActive={grandchildIsActive}
                                          className="h-8 translate-x-0 rounded-md px-2 text-xs text-sidebar-foreground/55 hover:bg-white/[0.035] data-[active=true]:bg-transparent data-[active=true]:font-medium data-[active=true]:text-sidebar-foreground"
                                          asChild
                                        >
                                          <RouterLink
                                            to={grandchild.path}
                                            hash={grandchild.hash}
                                            onClick={handleMenuClick}
                                          >
                                            <MenuIcon
                                              active={grandchildIsActive}
                                            />
                                            <span>{grandchild.title}</span>
                                          </RouterLink>
                                        </SidebarMenuSubButton>
                                      </SidebarMenuSubItem>
                                    )
                                  })}
                                </SidebarMenuSub>
                              )}
                            </SidebarMenuSubItem>
                          )
                        })}
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
