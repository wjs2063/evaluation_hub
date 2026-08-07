import { createFileRoute, Navigate } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/evaluation-single-turn/")({
  component: SingleTurnIndex,
})

function SingleTurnIndex() {
  return <Navigate to="/evaluation-single-turn/live-test" replace />
}
