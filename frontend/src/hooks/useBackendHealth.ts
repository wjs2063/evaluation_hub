import { useQuery } from "@tanstack/react-query"

import { UtilsService } from "@/client"

const useBackendHealth = () =>
  useQuery({
    queryKey: ["backend-health"],
    queryFn: UtilsService.healthCheck,
    refetchInterval: 30_000,
  })

export default useBackendHealth
