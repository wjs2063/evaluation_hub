import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("normal user creates a screen-scoped weighted metric profile", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> | null = null
  let customMetricBody: Record<string, unknown> | null = null
  let customMetricAttempts = 0

  await page.addInitScript(() => {
    localStorage.setItem("access_token", "metric-profile-token")
  })
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === "/api/v1/users/me") {
      return route.fulfill({
        json: {
          id: "user-1",
          email: "user@example.com",
          full_name: "User",
          is_active: true,
          is_superuser: false,
        },
      })
    }
    if (path === "/api/v1/users/") {
      return route.fulfill({ json: { data: [], count: 0 } })
    }
    if (path === "/api/v1/utils/health-check/") {
      return route.fulfill({ json: true })
    }
    if (path === "/api/v1/evaluations/endpoints") {
      return route.fulfill({ json: { data: [], count: 0 } })
    }
    if (path === "/api/v1/evaluations/metric-profiles") {
      if (request.method() === "POST") {
        createdBody = request.postDataJSON()
        return route.fulfill({
          json: {
            ...(createdBody as object),
            id: "profile-1",
            version: 1,
            created_at: "2026-08-12T00:00:00Z",
            updated_at: "2026-08-12T00:00:00Z",
            metrics: [],
          },
        })
      }
      return route.fulfill({ json: { data: [], count: 0 } })
    }
    if (path === "/api/v1/evaluations/custom-metric-placeholder-contracts") {
      return route.fulfill({
        json: {
          data: [
            {
              evaluation_scope: "quick_upload",
              syntax: "double_curly_lower_snake_case",
              requires_at_least_one: true,
              allowed_keys: ["input", "actual_output", "expected_output"],
            },
            {
              evaluation_scope: "single_turn",
              syntax: "double_curly_lower_snake_case",
              requires_at_least_one: true,
              allowed_keys: ["input", "actual_output", "expected_output"],
            },
            {
              evaluation_scope: "multi_turn",
              syntax: "double_curly_lower_snake_case",
              requires_at_least_one: true,
              allowed_keys: ["role", "content", "expected_outcome"],
            },
          ],
          count: 3,
        },
      })
    }
    if (path === "/api/v1/evaluations/custom-metrics") {
      if (request.method() === "POST") {
        customMetricAttempts += 1
        customMetricBody = request.postDataJSON()
        if (customMetricAttempts === 1) {
          return route.fulfill({
            status: 422,
            json: {
              detail: [
                {
                  type: "custom_metric_placeholder_not_allowed",
                  loc: ["body", "prompt"],
                  msg: "multi_turn 범위에서 지원하지 않는 placeholder입니다: input",
                  input: "{{input}}",
                  ctx: {
                    evaluation_scope: "multi_turn",
                    invalid_tokens: ["input"],
                    allowed_keys: ["role", "content", "expected_outcome"],
                  },
                },
                {
                  type: "value_error",
                  loc: ["body", "name"],
                  msg: "이름 검증 오류도 함께 표시합니다.",
                  input: "새 CustomMetric",
                },
              ],
            },
          })
        }
        return route.fulfill({
          json: {
            ...(customMetricBody as object),
            id: "custom-1",
            version: 1,
            required_keys: ["role", "content"],
            created_by_id: "user-1",
            updated_by_id: "user-1",
            created_at: "2026-08-20T00:00:00Z",
            updated_at: "2026-08-20T00:00:00Z",
          },
        })
      }
      return route.fulfill({ json: { data: [], count: 0 } })
    }
    if (path === "/api/v1/evaluations/metric-catalog") {
      const item = (
        metric_type: string,
        display_name: string,
        required_fields: string[],
      ) => ({
        metric_type,
        display_name,
        description: `${display_name} 공식 설명`,
        required_fields,
        score_direction: "higher_is_better",
        uses_llm: true,
        docs_url: "https://deepeval.com/docs/metrics-introduction",
        evaluation_mode: "single_turn",
        required_config: [],
        supports_custom_instruction: false,
      })
      return route.fulfill({
        json: {
          data: [
            item("geval_correctness", "정확성 (G-Eval)", [
              "actual_output",
              "expected_output",
            ]),
            item("answer_relevancy", "답변 관련성", ["input", "actual_output"]),
            item("geval_professionalism", "전문성 (G-Eval)", ["actual_output"]),
            item("toxicity", "유해성 안전성", ["input", "actual_output"]),
          ],
          count: 4,
        },
      })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/")
  await page.getByRole("link", { name: "Metrics" }).click()
  await expect(page).toHaveURL(/\/metrics$/)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.body.scrollWidth))
    .toBeLessThanOrEqual(390)

  const weightStatus = page.getByRole("status", {
    name: "평가지표 가중치 합계",
  })
  await expect(weightStatus).toHaveText("가중치 합계 100% · 저장 가능")
  await expect(page.getByLabel("지표 1 타입")).toHaveValue(
    "builtin:geval_correctness",
  )
  await expect(page.getByLabel("정확성 (G-Eval) 지표 삭제")).toBeEnabled()
  const saveButton = page.getByRole("button", { name: "프로필 저장" })
  await page.getByLabel("정확성 (G-Eval) 가중치").fill("49")
  await expect(weightStatus).toHaveText("가중치 합계 99% · 100%로 맞춰 주세요")
  await expect(saveButton).toBeDisabled()
  expect(createdBody).toBeNull()

  await page.getByLabel("정확성 (G-Eval) 가중치").fill("50")
  await expect(saveButton).toBeEnabled()
  await saveButton.click()

  await expect.poll(() => createdBody).not.toBeNull()
  expect(createdBody).toMatchObject({
    name: "새 평가 프로필",
    is_active: true,
    evaluation_scope: "quick_upload",
    evaluation_mode: "single_turn",
    metrics: [
      { metric_type: "geval_correctness", weight_percent: 50 },
      { metric_type: "answer_relevancy", weight_percent: 30 },
      { metric_type: "geval_professionalism", weight_percent: 20 },
    ],
  })

  const prompt = page.getByLabel("CustomMetric G-Eval 프롬프트")
  const customSave = page.getByRole("button", { name: "저장", exact: true })
  await prompt.fill("{{ input }} 문법 오류")
  await expect(prompt).toHaveAttribute("aria-invalid", "true")
  await expect(page.getByText(/잘못된 token: \{\{ input \}\}/)).toBeVisible()
  await expect(customSave).toBeDisabled()
  expect(customMetricAttempts).toBe(0)

  await prompt.fill("{{input}}을 평가하세요.")
  await expect(prompt).toHaveAttribute("aria-invalid", "false")
  await page.getByRole("tab", { name: "멀티턴" }).click()
  await expect(prompt).toHaveValue("{{input}}을 평가하세요.")
  await expect(prompt).toHaveAttribute("aria-invalid", "true")
  await expect(page.getByText(/범위: multi_turn/)).toBeVisible()
  await expect(page.getByText(/허용: \{\{role\}\}/)).toBeVisible()
  expect(customMetricAttempts).toBe(0)

  await prompt.fill("  {{role}}과 {{content}}를 평가하세요.  ")
  await expect(prompt).toHaveAttribute("aria-invalid", "false")
  await expect(page.getByText("인식된 key: role, content")).toBeVisible()
  await customSave.click()
  await expect(
    page.getByText(/지원하지 않는 placeholder입니다: input/),
  ).toBeVisible()
  await expect(
    page.getByText(/허용: \{\{role\}\}, \{\{content\}\}/),
  ).toBeVisible()
  await expect(
    page.getByText("이름 검증 오류도 함께 표시합니다."),
  ).toBeVisible()
  expect(customMetricAttempts).toBe(1)

  await customSave.click()
  await expect.poll(() => customMetricAttempts).toBe(2)
  expect(customMetricBody).toMatchObject({
    evaluation_scope: "multi_turn",
    prompt: "  {{role}}과 {{content}}를 평가하세요.  ",
  })

  await page.setViewportSize({ width: 1440, height: 900 })
  await expect
    .poll(() => page.evaluate(() => document.body.scrollWidth))
    .toBeLessThanOrEqual(1440)
})

test("custom metric save is blocked when the placeholder contract fails", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "metric-contract-token")
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/users/me") {
      return route.fulfill({
        json: {
          id: "user-1",
          email: "user@example.com",
          full_name: "User",
          is_active: true,
          is_superuser: false,
        },
      })
    }
    if (path === "/api/v1/utils/health-check/")
      return route.fulfill({ json: true })
    if (path === "/api/v1/evaluations/custom-metric-placeholder-contracts") {
      return route.fulfill({
        status: 422,
        json: { detail: "placeholder 계약 서비스 점검 중" },
      })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/")
  await page.getByRole("link", { name: "Metrics" }).click()
  await expect(page).toHaveURL(/\/metrics$/)
  await expect(page.getByText("placeholder 계약 서비스 점검 중")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "저장", exact: true }),
  ).toBeDisabled()
})
