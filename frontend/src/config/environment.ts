export type AppEnvironment = "development" | "staging" | "production"

const environmentAliases: Record<string, AppEnvironment> = {
  develop: "development",
  development: "development",
  local: "development",
  staging: "staging",
  production: "production",
  prod: "production",
}

const configuredEnvironment = import.meta.env.VITE_APP_ENV?.trim().toLowerCase()
const normalizedEnvironment = configuredEnvironment
  ? environmentAliases[configuredEnvironment]
  : undefined

export const appEnvironment: AppEnvironment =
  normalizedEnvironment ?? (import.meta.env.DEV ? "development" : "production")

export const environmentLabels: Record<AppEnvironment, string> = {
  development: "Development",
  staging: "Staging",
  production: "Production",
}
