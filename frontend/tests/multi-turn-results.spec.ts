import { readFile } from "node:fs/promises"
import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const scenario = {
  id: "scenario-1",
  name: "상담 대화 품질",
  description: "멀티턴 상세 결과 테스트",
  endpoint_id: "endpoint-1",
  threshold: 0.7,
  evaluator: "local",
  turn_count: 1,
  turns: [
    {
      id: "turn-1",
      position: 0,
      identifier: "first_answer",
      url: "https://a.test/chat",
      headers_configured: false,
      body_template: '{"message":"첫 질문"}',
      response_path: "answer",
      expected_output: "기대 응답",
    },
  ],
}

const run = {
  id: "scenario-run-1",
  scenario_id: scenario.id,
  baseline_run_id: null,
  created_at: "2026-08-12T00:00:00Z",
  total: 1,
  passed: 1,
  failed: 0,
  turn_average_score: 0.9,
  conversation_score: null,
  conversation_reason: null,
  overall_score: 0.9,
  overall_passed: true,
  overall_reason: "전체 대화가 기대 조건을 충족했습니다.",
  average_score: 0.9,
  evaluator: "local",
  geval_score: null,
  geval_reason: null,
  error: null,
  scenario_name: scenario.name,
  scenario_description: scenario.description.slice(0, 20),
  executor_name: "Test Admin",
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "multi-turn-results-token")
  })
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/v1/users/me") {
      return route.fulfill({
        json: {
          id: "user-1",
          email: "admin@example.com",
          full_name: "Test Admin",
          is_active: true,
          is_superuser: true,
        },
      })
    }
    if (url.pathname === "/api/v1/utils/health-check/") {
      return route.fulfill({ json: true })
    }
    if (url.pathname === "/api/v1/evaluations/endpoints") {
      return route.fulfill({
        json: {
          data: [
            {
              id: "endpoint-1",
              name: "A server",
              base_url: "https://a.test",
              is_active: true,
            },
          ],
        },
      })
    }
    if (url.pathname === "/api/v1/evaluations/multi-turn/datasets") {
      return route.fulfill({ json: { data: [scenario], count: 1 } })
    }
    if (
      url.pathname === `/api/v1/evaluations/multi-turn/datasets/${scenario.id}`
    ) {
      return route.fulfill({ json: scenario })
    }
    if (
      url.pathname ===
      `/api/v1/evaluations/multi-turn/datasets/${scenario.id}/runs/${run.id}`
    ) {
      return route.fulfill({
        json: {
          ...run,
          turns: [
            {
              id: "scenario-run-turn-1",
              identifier: "first_answer",
              request_body: '{"message":"첫 질문"}',
              actual_output: "실제 멀티턴 응답",
              expected_output: "기대 응답",
              response_status: 200,
              score: 0.9,
              passed: true,
              reason: "요청 의도에 맞게 답변했습니다.",
              error: null,
            },
          ],
        },
      })
    }
    if (
      url.pathname ===
      `/api/v1/evaluations/multi-turn/datasets/${scenario.id}/runs`
    ) {
      expect(url.searchParams.get("limit")).toBe("20")
      return route.fulfill({ json: { data: [run], count: 21 } })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })
})

test("multi-turn results paginate and open a separate detail payload", async ({
  page,
}) => {
  await page.goto("/evaluation-multi-turn/live-test")
  await page.getByRole("button", { name: /상담 대화 품질/ }).click()

  await expect(page.getByText("총 21건 · 1/2 페이지")).toBeVisible()
  await page.getByRole("button", { name: /최종 통과/ }).click()
  await expect(page.getByText("실제 멀티턴 응답")).toBeVisible()
  await expect(page.getByText("요청 의도에 맞게 답변했습니다.")).toBeVisible()

  await page.getByRole("button", { name: "다음" }).click()
  await expect(page.getByText("총 21건 · 2/2 페이지")).toBeVisible()
})

test("multi-turn page downloads the JSON sample", async ({ page }) => {
  await page.goto("/evaluation-multi-turn/live-test")
  const downloadPromise = page.waitForEvent("download")
  await page.getByRole("button", { name: "JSON 샘플" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe("multi-turn-dataset-sample.json")
  const path = await download.path()
  const sample = JSON.parse(await readFile(path!, "utf8"))
  expect(sample.test_type).toBe("multi_turn")
  expect(sample.cases[0].request).toEqual(
    expect.objectContaining({
      headers: { "Content-Type": "application/json" },
      body: { message: "첫 질문", history: [] },
      actual_output_json_pointer: "/answer",
    }),
  )
  expect(sample.cases[0].expected_output).toBe("기대하는 첫 응답")
})
