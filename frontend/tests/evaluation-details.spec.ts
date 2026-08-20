import { readFile } from "node:fs/promises"
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
  threshold: 70,
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
  average_score: 82.5,
  geval_available: true,
  dataset_name: dataset.name,
  dataset_description: "상세 평가 설명",
  executor_name: "Test Admin",
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
      score: 82.5,
      passed: true,
      error: null,
      metrics: [
        {
          name: "toxicity",
          display_name: "유해성 안전성",
          score: 82.5,
          raw_score_ratio: 0.175,
          score_direction: "lower_is_better",
          weight_percent: 70,
          weighted_score: 57.75,
          reason: "핵심 내용이 일치합니다.\n표현도 자연스럽습니다.",
        },
        {
          name: "custom_metric",
          score: 50,
          reason: null,
        },
      ],
    },
  ],
}

async function mockEvaluationApi(page: Page, savedRunCount = 1) {
  let schedules: Array<{
    id: string
    owner_id: string
    owner_name: string
    name: string
    target_type: "single_turn"
    target_id: string
    target_name: string
    target_description: string | null
    schedule_type: "interval" | "cron"
    interval_seconds: number | null
    cron_expression: string | null
    timezone: string
    is_active: boolean
    next_run_at: string
    last_enqueued_at: string | null
  }> = []
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
    if (path === `/api/v1/evaluations/single-turn/datasets/${dataset.id}`) {
      return route.fulfill({ json: dataset })
    }
    if (
      path === "/api/v1/evaluations/schedules" &&
      route.request().method() === "GET"
    ) {
      return route.fulfill({
        json: { data: schedules, count: schedules.length },
      })
    }
    if (
      path === "/api/v1/evaluations/schedules" &&
      route.request().method() === "POST"
    ) {
      const request = route.request().postDataJSON()
      schedules = [
        {
          id: "schedule-1",
          owner_id: "user-1",
          owner_name: "Test Admin",
          name: request.name,
          target_type: "single_turn",
          target_id: dataset.id,
          target_name: dataset.name,
          target_description: dataset.description,
          schedule_type: request.schedule_type,
          interval_seconds: request.interval_seconds,
          cron_expression: request.cron_expression,
          timezone: request.timezone,
          is_active: request.is_active,
          next_run_at: request.next_run_at,
          last_enqueued_at: null,
        },
      ]
      return route.fulfill({ status: 201, json: schedules[0] })
    }
    if (
      path === "/api/v1/evaluations/schedules/schedule-1" &&
      route.request().method() === "PUT"
    ) {
      schedules = [{ ...schedules[0], ...route.request().postDataJSON() }]
      return route.fulfill({ json: schedules[0] })
    }
    if (
      path === "/api/v1/evaluations/schedules/schedule-1" &&
      route.request().method() === "DELETE"
    ) {
      schedules = []
      return route.fulfill({ json: { message: "deleted" } })
    }
    if (
      path === `/api/v1/evaluations/single-turn/datasets/${dataset.id}/run` &&
      route.request().method() === "POST"
    ) {
      return route.fulfill({
        status: 202,
        json: {
          id: "job-1",
          dataset_id: dataset.id,
          status: "queued",
          run_id: null,
          error: null,
        },
      })
    }
    if (path === "/api/v1/evaluations/jobs/job-1") {
      return route.fulfill({
        json: {
          id: "job-1",
          dataset_id: dataset.id,
          status: "succeeded",
          run_id: runSummary.id,
          error: null,
        },
      })
    }
    if (
      path === `/api/v1/evaluations/single-turn/datasets/${dataset.id}/runs`
    ) {
      if (savedRunCount > 1) {
        expect(url.searchParams.get("limit")).toBe("10")
      }
      return route.fulfill({
        json: { data: [runSummary], count: savedRunCount },
      })
    }
    if (
      path ===
      `/api/v1/evaluations/single-turn/datasets/${dataset.id}/runs/${runSummary.id}`
    ) {
      return route.fulfill({ json: runDetail })
    }
    if (
      path ===
      `/api/v1/evaluations/single-turn/datasets/${dataset.id}/runs/${runSummary.id}/report.html`
    ) {
      return route.fulfill({
        contentType: "text/html; charset=utf-8",
        headers: {
          "content-disposition":
            'attachment; filename="evaluation-report.html"',
        },
        body: "<!doctype html><title>평가 결과</title>",
      })
    }
    if (path === "/api/v1/evaluations/single-turn/datasets") {
      return route.fulfill({ json: { data: [dataset], count: 1 } })
    }
    return route.fulfill({ json: { data: [] } })
  })
}

async function expectEvaluationDetails(page: Page) {
  await expect(page.getByText("통과 · 82.500점", { exact: true })).toBeVisible()
  await expect(page.getByText("유해성 안전성", { exact: true })).toBeVisible()
  await expect(page.getByText("가중치 70% · 최종 기여 57.750점")).toBeVisible()
  await expect(
    page.getByText(
      "DeepEval 원점수 17.500점 · 낮을수록 좋음 · 합산용 품질점수 82.500점",
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

test("live test waits for a queued worker job before loading results", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/evaluation-single-turn/live-test")

  await page.getByRole("button", { name: "평가 실행" }).click()

  await expect(page.getByText("통과 · 82.500점", { exact: true })).toBeVisible()
})

test("independent scheduling page manages schedules through CRUD", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  page.on("dialog", (dialog) => dialog.accept())
  await page.goto("/scheduling")

  await page.getByLabel("Schedule name").fill("매일 품질 테스트")
  await page.getByLabel("Schedule interval minutes").fill("1440")
  await page.getByRole("button", { name: "등록" }).click()
  const savedScheduleName = page.getByLabel("Schedule name schedule-1")
  await expect(savedScheduleName).toHaveValue("매일 품질 테스트")

  await savedScheduleName.fill("주간 품질 테스트")
  await page.getByLabel("Schedule active schedule-1").uncheck()
  await page
    .getByRole("button", { name: "Save schedule 주간 품질 테스트" })
    .click()
  await expect(page.getByText("중지", { exact: true })).toBeVisible()

  await page
    .getByRole("button", { name: "Delete schedule 주간 품질 테스트" })
    .click()
  await expect(page.getByText("등록된 스케줄이 없습니다.")).toBeVisible()
})

test("scheduling page shows Cron expression examples in a help dialog", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/scheduling")

  await page.getByRole("button", { name: "Cron 사용법 보기" }).click()
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByRole("heading", { name: "Cron 표현식 사용법" }),
  ).toBeVisible()
  await expect(dialog.getByText("0 9 * * 1-5", { exact: true })).toBeVisible()
  await expect(dialog.getByText("평일 오전 9시", { exact: true })).toBeVisible()
  await expect(dialog.getByText("Asia/Seoul", { exact: true })).toBeVisible()
})

test("single-turn page downloads a typed per-case JSON sample", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/evaluation-single-turn/live-test")

  const downloadPromise = page.waitForEvent("download")
  await page.getByRole("button", { name: "JSON 샘플" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe("single-turn-dataset-sample.json")
  const path = await download.path()
  const sample = JSON.parse(await readFile(path!, "utf8"))
  expect(sample.test_type).toBe("single_turn")
  expect(sample.cases[0]).toEqual(
    expect.objectContaining({
      input: "서울의 오늘 날씨를 알려줘",
      expected_output: "서울의 오늘 날씨는 맑음입니다.",
    }),
  )
  expect(sample.cases[0].request).toEqual(
    expect.objectContaining({
      headers: { "Content-Type": "application/json" },
      actual_output_json_pointer: "/answer",
    }),
  )
})

test("live test downloads the selected-metric HTML report", async ({
  page,
}) => {
  await mockEvaluationApi(page)
  await page.goto("/evaluation-single-turn/live-test")

  const downloadPromise = page.waitForEvent("download")
  await page.getByLabel(`Download HTML report ${runSummary.id}`).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(
    `evaluation-report-${runSummary.id}.html`,
  )
})

test("live test paginates saved results by 10", async ({ page }) => {
  await mockEvaluationApi(page, 21)
  await page.goto("/evaluation-single-turn/live-test")

  await expect(page.getByText("총 21건 · 1/2 페이지")).toBeVisible()
  await page.getByRole("button", { name: "다음" }).click()
  await expect(page.getByText("총 21건 · 2/2 페이지")).toBeVisible()
})
