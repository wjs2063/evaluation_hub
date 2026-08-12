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
  await page.route("**/api/v1/evaluations/single-turn/datasets**", (route) =>
    route.fulfill({ json: { data: [] } }),
  )
  await page.route("**/api/v1/evaluations/multi-turn/datasets**", (route) =>
    route.fulfill({ json: { data: [] } }),
  )
  await page.route("**/api/v1/evaluations/endpoints", (route) =>
    route.fulfill({ json: { data: [] } }),
  )
  await page.route("**/api/v1/evaluations/metric-profiles", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route("**/api/v1/evaluations/metric-catalog", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route("**/api/v1/evaluations/schedules**", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route("**/api/v1/items**", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route(/\/api\/v1\/users(?:\?.*)?$/, (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
})

test("sidebar uses English labels and simple page indicators", async ({
  page,
}) => {
  await page.goto("/")

  const sidebar = page.locator('[data-sidebar="sidebar"]')
  const brand = sidebar.getByRole("link", { name: "Go to overview" })
  await expect(brand.getByText("EvaluationHub", { exact: true })).toBeVisible()
  await expect(brand.getByText("E", { exact: true })).toBeVisible()
  await expect(sidebar.getByText("Single-turn", { exact: true })).toBeVisible()
  await expect(sidebar.getByText("Multi-turn", { exact: true })).toBeVisible()
  await expect(sidebar.getByText("Live Test", { exact: true })).toHaveCount(2)
  await expect(
    sidebar.getByText("Regression Test", { exact: true }),
  ).toHaveCount(2)
  await expect(sidebar.getByText("Scheduling", { exact: true })).toBeVisible()
  await expect(
    sidebar.getByText("Results & Reports", { exact: true }),
  ).toBeVisible()
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
  expect(borderRadii.every((radius) => radius >= 4 && radius <= 8)).toBe(true)

  const contentButtons = sidebar.locator('[data-sidebar="content"] a')
  await expect(contentButtons).toHaveCount(12)
  await expect(contentButtons.locator("svg")).toHaveCount(0)
  await expect(
    sidebar.locator('[data-sidebar="menu-button"][data-active="true"]'),
  ).toHaveAttribute("data-active", "true")
})

test("sidebar links to independent scheduling and result reports", async ({
  page,
}) => {
  await page.goto("/evaluation-single-turn/live-test")

  const sidebar = page.locator('[data-sidebar="sidebar"]')
  const buttonFor = (label: string) =>
    sidebar
      .locator('[data-sidebar="menu-button"], [data-sidebar="menu-sub-button"]')
      .filter({ hasText: label })
      .first()

  await sidebar.getByText("Scheduling", { exact: true }).click()
  await expect(page).toHaveURL(/\/scheduling$/)
  await expect(page.getByRole("heading", { name: "스케줄링" })).toBeVisible()
  await expect(buttonFor("Scheduling")).toHaveAttribute("data-active", "true")

  await sidebar.getByText("Results & Reports", { exact: true }).click()
  await expect(page).toHaveURL(/\/evaluation-single-turn\/live-test#results$/)
  await expect(page.locator("#results")).toBeInViewport()
  await expect(buttonFor("Results & Reports")).toHaveAttribute(
    "data-active",
    "true",
  )
  await expect(buttonFor("Scheduling")).toHaveAttribute("data-active", "false")
})

test("sidebar orange state distinguishes active evaluation paths", async ({
  page,
}) => {
  await page.goto("/evaluation-single-turn/live-test")

  const sidebar = page.locator('[data-sidebar="sidebar"]')
  const buttonFor = (label: string) =>
    sidebar
      .locator('[data-sidebar="menu-button"], [data-sidebar="menu-sub-button"]')
      .filter({ hasText: label })
      .first()

  for (const label of ["Evaluations", "Single-turn", "Live Test"]) {
    await expect(buttonFor(label)).toHaveAttribute("data-active", "true")
    await expect(buttonFor(label).locator("span").first()).toHaveClass(
      /bg-primary/,
    )
  }

  for (const label of ["Overview", "Multi-turn", "Items", "Users"]) {
    await expect(buttonFor(label)).toHaveAttribute("data-active", "false")
    await expect(buttonFor(label).locator("span").first()).toHaveClass(
      /border-sidebar-border/,
    )
  }
})

test("new users default to dark and system mode follows OS changes", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" })
  await page.goto("/")
  await expect(page.locator("html")).toHaveClass(/dark/)

  await page.getByTestId("theme-button").click()
  await page.getByTestId("system-mode").click()
  await expect(page.locator("html")).toHaveClass(/light/)
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("vite-ui-theme")))
    .toBe("system")

  await page.emulateMedia({ colorScheme: "dark" })
  await expect(page.locator("html")).toHaveClass(/dark/)
})

test("responsive shell has no horizontal overflow in either theme", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/")
  await expect(page.getByText("Workspace overview")).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.body.scrollWidth))
    .toBeLessThanOrEqual(1440)
  await page.screenshot({
    path: testInfo.outputPath("overview-dark-desktop.png"),
    fullPage: true,
  })

  await page.getByTestId("theme-button").click()
  await page.getByTestId("light-mode").click()
  await expect(page.locator("html")).toHaveClass(/light/)
  await expect(page.getByTestId("light-mode")).not.toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.body.scrollWidth))
    .toBeLessThanOrEqual(1440)
  await page.screenshot({
    path: testInfo.outputPath("overview-light-desktop.png"),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.body.scrollWidth))
    .toBeLessThanOrEqual(390)
  await page.locator('button[data-sidebar="trigger"]').click()
  const mobileSidebar = page.locator(
    '[data-sidebar="sidebar"][data-mobile="true"]',
  )
  await expect(mobileSidebar.getByText("EvaluationHub")).toBeVisible()
  await expect
    .poll(async () => (await mobileSidebar.boundingBox())?.x ?? -1)
    .toBe(0)
  await page.screenshot({
    path: testInfo.outputPath("overview-light-mobile-menu.png"),
    fullPage: true,
  })
})

test("primary console routes render without layout errors", async ({
  page,
}) => {
  for (const path of [
    "/items",
    "/admin",
    "/settings",
    "/evaluations",
    "/evaluation-single-turn/live-test",
    "/evaluation-single-turn/regression",
    "/evaluation-multi-turn/live-test",
    "/evaluation-multi-turn/regression",
  ]) {
    await page.goto(path)
    await expect(page.locator("main h1").first()).toBeVisible()
    await expect(page.getByTestId("error-component")).toHaveCount(0)
    await expect
      .poll(() => page.evaluate(() => document.body.scrollWidth))
      .toBeLessThanOrEqual(1280)
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
