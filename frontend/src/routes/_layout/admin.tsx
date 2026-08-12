import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { EvaluationEndpoints } from "@/components/Admin/EvaluationEndpoints"
import { EvaluationMetricProfiles } from "@/components/Admin/EvaluationMetricProfiles"
import { DataTable } from "@/components/Common/DataTable"
import { PageHeader } from "@/components/Common/PageHeader"
import PendingUsers from "@/components/Pending/PendingUsers"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    queryKey: ["users"],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Users - EvalHub",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Administration"
        title="Users & access"
        description="Manage user accounts, roles, and access to this workspace."
        action={<AddUser />}
      />
      <div className="console-surface overflow-hidden">
        <div className="border-b px-5 py-4">
          <h2 className="text-sm font-semibold">User directory</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Accounts with access to the control plane
          </p>
        </div>
        <div className="p-4">
          <UsersTable />
        </div>
      </div>
      <EvaluationEndpoints />
      <EvaluationMetricProfiles />
    </div>
  )
}
