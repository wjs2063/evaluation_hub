import { expect, type Page, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const dataset = {
  id: "dataset-1",
  name: "상세 평가 데이터셋",
  description: null,
  evaluation_type: "single_turn",
  endpoint_id: "endpoint-1",
  body_template: '{"input":"{{input}}"}',
  response_path: null,
  threshold: 0.7,
  evaluator: "deepeval",
  row_count: 1,
  rows: [
    {
      id: "dataset-row-1",
      input: "질문",
      expected_output: "기대 응답",
    },
  ],
}

const runSummary = {
  id: "run-1",
  dataset_id: dataset.id,
  baseline_run_id: null,
  evaluator: "deepeval",
  created_at: "2026-08-09T00:00:00Z",
  total: 1,
  passed: 1,
  failed: 0,
  pass_rate: 1,
  average_score: 0.825,
  geval_available: true,
}

const runDetail = {
  ...runSummary,
  row_count: 1,
  rows: [
    {
      id: "run-row-1",
      input: "질문",
      expected_output: "기대 응답",
      actual_output: "실제 응답",
      response_status: 200,
      score: 0.825,
      passed: true,
      error: null,
      metrics: [
        {
          name: "toxicity",
          display_name: "유해성 안전성",
          score: 0.825,
          raw_score: 0.175,
          score_direction: "lower_is_better",
          weight_percent: 70,
          weighted_score: 0.5775,
          reason: "핵심 내용이 일치합니다.\n표현도 자연스럽습니다.",
        },
        {
          name: "custom_metric",
          score: 0.5,
          reason: null,
        },
      ],
    },
  ],
}

async function mockEvaluationApi(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "evaluation-details-token")
  })
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === "/api/v1/users/me") {
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
    if (path === "/api/v1/utils/health-check/") {
      return route.fulfill({ json: true })
    }
    if (path === "/api/v1/evaluations/endpoints") {
      return route.fulfill({
        json: {
          data: [
            { id: "endpoint-1", name: "A server", base_url: "https://a.test" },
          ],
        },
      })
    }
    if (path === `/api/v1/evaluations/datasets/${dataset.id}`) {
      return route.fulfill({ json: dataset })
    }
    if (path === `/api/v1/evaluations/datasets/${dataset.id}/runs`) {
      return route.fulfill({ json: { data: [runSummary], count: 1 } })
    }
    if (
      path ===
      `/api/v1/evaluations/datasets/${dataset.id}/runs/${runSummary.id}`
    ) {
      return route.fulfill({ json: runDetail })
    }
    if (path === "/api/v1/evaluations/datasets") {
      return route.fulfill({ json: { data: [dataset], count: 1 } })
    }
    return route.fulfill({ json: { data: [] } })
  })
}

async function expectEvaluationDetails(page: Page) {
  await expect(page.getByText("통과 · 82.50점", { exact: true })).toBeVisible()
  await expect(page.getByText("유해성 안전성", { exact: true })).toBeVisible()
  await expect(page.getByText("가중치 70% · 최종 기여 57.75점")).toBeVisible()
  await expect(
    page.getByText(
      "DeepEval 원점수 17.50점 · 낮을수록 좋음 · 합산용 품질점수 82.50점",
    ),
  ).toBeVisible()
  await expect(page.getByText("custom_metric", { exact: true })).toBeVisible()
  await expect(page.getByText("핵심 내용이 일치합니다.")).toBeVisible()
  await expect(page.getByText("표현도 자연스럽습니다.")).toBeVisible()
  await expect(
    page.getByText("평가 이유가 제공되지 않았습니다.", { exact: true }),
  ).toBeVisible()
}

test("live test displays the overall score, metrics, and reasons", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/evaluation-single-turn/live-test")
  await page.getByRole("button").filter({ hasText: "통과 1/1" }).click()

  await expectEvaluationDetails(page)
})

test("regression displays the overall score, metrics, and reasons", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/evaluation-single-turn/regression")

  await expectEvaluationDetails(page)
})
