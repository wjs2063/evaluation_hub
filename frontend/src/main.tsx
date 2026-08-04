import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { isAxiosError } from "axios"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL ?? ""
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

let isRedirectingToLogin = false

const shouldRedirectForStatus = (status: number) =>
  status === 401 || status === 403 || status >= 500

const isBackendConnectionError = (error: unknown) =>
  isAxiosError(error) &&
  error.response === undefined &&
  error.code !== "ERR_CANCELED"

const redirectToLogin = () => {
  localStorage.removeItem("access_token")

  if (window.location.pathname !== "/login" && !isRedirectingToLogin) {
    isRedirectingToLogin = true
    window.location.replace("/login")
  }
}

OpenAPI.interceptors.response.use((response) => {
  if (shouldRedirectForStatus(response.status)) {
    redirectToLogin()
  }

  return response
})

const shouldRedirectToLogin = (error: unknown) =>
  (error instanceof ApiError && shouldRedirectForStatus(error.status)) ||
  isBackendConnectionError(error)

const handleApiError = (error: Error) => {
  if (shouldRedirectToLogin(error)) {
    redirectToLogin()
  }
}
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        !shouldRedirectToLogin(error) && failureCount < 3,
    },
  },
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
