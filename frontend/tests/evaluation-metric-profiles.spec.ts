import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("admin creates a strongly typed weighted metric profile", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> | null = null

  await page.addInitScript(() => {
    localStorage.setItem("access_token", "metric-profile-token")
  })
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === "/api/v1/users/me") {
      return route.fulfill({
        json: {
          id: "admin-1",
          email: "admin@example.com",
          full_name: "Admin",
          is_active: true,
          is_superuser: true,
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

  await page.goto("/admin")

  const weightStatus = page.getByRole("status", {
    name: "평가지표 가중치 합계",
  })
  await expect(weightStatus).toHaveText("가중치 합계 100% · 저장 가능")
  await expect(page.getByLabel("지표 1 타입")).toHaveValue("geval_correctness")
  await expect(page.getByLabel("정확성 (G-Eval) 지표 삭제")).toBeEnabled()
  const saveButton = page.getByRole("button", { name: "프로필 저장" })
  await page.getByLabel("정확성 (G-Eval) 가중치").fill("49")
  await expect(weightStatus).toHaveText(
    "가중치 합계 99% · 100%가 되도록 1%를 추가하세요.",
  )
  await expect(saveButton).toBeDisabled()
  expect(createdBody).toBeNull()

  await page.getByLabel("정확성 (G-Eval) 가중치").fill("50")
  await expect(saveButton).toBeEnabled()
  await saveButton.click()

  await expect.poll(() => createdBody).not.toBeNull()
  expect(createdBody).toMatchObject({
    name: "새 평가 프로필",
    is_active: true,
    metrics: [
      { metric_type: "geval_correctness", weight_percent: 50 },
      { metric_type: "answer_relevancy", weight_percent: 30 },
      { metric_type: "geval_professionalism", weight_percent: 20 },
    ],
  })
})
