import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "sidebar-test-token")
  })
  await page.route("**/api/v1/**", (route) => route.fulfill({ json: [] }))
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000001",
        email: "admin@example.com",
        full_name: "Test Admin",
        is_active: true,
        is_superuser: true,
      },
    }),
  )
  await page.route("**/api/v1/utils/health-check/", (route) =>
    route.fulfill({ json: true }),
  )
  await page.route("**/api/v1/evaluations/datasets**", (route) =>
    route.fulfill({ json: { data: [] } }),
  )
  await page.route("**/api/v1/evaluations/endpoints", (route) =>
    route.fulfill({ json: { data: [] } }),
  )
})

test("sidebar uses English evaluation labels", async ({ page }) => {
  await page.goto("/")

  const sidebar = page.locator('[data-sidebar="sidebar"]')
  const brand = sidebar.getByRole("link", { name: "Go to overview" })
  await expect(brand.getByText("EvaluationHub", { exact: true })).toBeVisible()
  await expect(brand.locator('[data-sidebar="item-indicator"]')).toHaveCount(1)
  await expect(sidebar.getByText("Single-turn", { exact: true })).toBeVisible()
  await expect(sidebar.getByText("Multi-turn", { exact: true })).toBeVisible()
  await expect(sidebar.getByText("Live Test", { exact: true })).toHaveCount(2)
  await expect(
    sidebar.getByText("Regression Test", { exact: true }),
  ).toHaveCount(2)
  await expect(sidebar.getByText("라이브 API 테스트")).toHaveCount(0)
  await expect(sidebar.getByText("회귀 평가")).toHaveCount(0)
  await expect(sidebar.locator('[data-sidebar="content"] svg')).toHaveCount(0)

  const sidebarButtons = sidebar.locator(
    '[data-sidebar="menu-button"], [data-sidebar="menu-sub-button"]',
  )
  const borderRadii = await sidebarButtons.evaluateAll((buttons) =>
    buttons.map((button) =>
      Number.parseFloat(getComputedStyle(button).borderRadius),
    ),
  )
  expect(borderRadii.length).toBeGreaterThan(0)
  expect(borderRadii.every((radius) => radius > 100)).toBe(true)

  await expect(sidebar.locator('[data-sidebar="item-indicator"]')).toHaveCount(
    13,
  )
  await expect(
    sidebarButtons.locator('[data-sidebar="item-indicator"]'),
  ).toHaveCount(12)
  await expect(
    sidebarButtons
      .filter({ hasText: "Overview" })
      .locator('[data-sidebar="item-indicator"]'),
  ).toHaveAttribute("data-active", "true")

  const indicatorSizes = await sidebar
    .locator('[data-sidebar="item-indicator"]')
    .evaluateAll((indicators) =>
      indicators.map((indicator) => {
        const style = getComputedStyle(indicator)
        return [style.width, style.height]
      }),
    )
  expect(
    indicatorSizes.every(
      ([width, height]) => width === "8px" && height === "8px",
    ),
  ).toBe(true)
})

test("sidebar dots distinguish active evaluation paths", async ({ page }) => {
  await page.goto("/evaluation-single-turn/live-test")

  const sidebar = page.locator('[data-sidebar="sidebar"]')
  const buttonFor = (label: string) =>
    sidebar
      .locator('[data-sidebar="menu-button"], [data-sidebar="menu-sub-button"]')
      .filter({ hasText: label })
      .first()

  for (const label of ["Evaluations", "Single-turn", "Live Test"]) {
    await expect(
      buttonFor(label).locator('[data-sidebar="item-indicator"]'),
    ).toHaveAttribute("data-active", "true")
    await expect(
      buttonFor(label).locator('[data-sidebar="item-indicator"]'),
    ).toHaveClass(/bg-cyan-400/)
  }

  for (const label of ["Overview", "Multi-turn", "Items", "Users"]) {
    await expect(
      buttonFor(label).locator('[data-sidebar="item-indicator"]'),
    ).toHaveAttribute("data-active", "false")
    await expect(
      buttonFor(label).locator('[data-sidebar="item-indicator"]'),
    ).toHaveClass(/bg-sidebar-foreground\/25/)
  }
})

test("single-turn test links show English breadcrumb names", async ({
  page,
}) => {
  await page.goto("/")

  const header = page.locator("header")
  await page.locator('a[href="/evaluation-single-turn/live-test"]').click()
  await expect(header.getByText("Live Test", { exact: true })).toBeVisible()

  await page.goto("/evaluation-single-turn/regression")
  await expect(
    header.getByText("Regression Test", { exact: true }),
  ).toBeVisible()
})

test("multi-turn test links show English breadcrumb names", async ({
  page,
}) => {
  await page.goto("/")

  const header = page.locator("header")
  await page.locator('a[href="/evaluation-multi-turn/live-test"]').click()
  await expect(
    header.getByText("Multi-turn Live Test", { exact: true }),
  ).toBeVisible()

  await page.goto("/evaluation-multi-turn/regression")
  await expect(
    header.getByText("Multi-turn Regression Test", { exact: true }),
  ).toBeVisible()
})
