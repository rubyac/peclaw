import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync } from "node:fs";
import path from "node:path";
const root = path.resolve(process.cwd(), "../..");
const artifactRoot =
  process.env.PECLAW_ARTIFACT_DIR || path.join(root, "test-artifacts");
function fixture(mode: string, key?: string) {
  return execFileSync(
    "docker",
    [
      "compose",
      "exec",
      "-T",
      "api",
      "python",
      "-",
      mode,
      ...(key ? [key] : []),
    ],
    {
      cwd: root,
      input: readFileSync(
        path.join(root, "tests/fixtures/browser_accounts.py"),
        "utf8",
      ),
      encoding: "utf8",
    },
  );
}
async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
}
test("agent workbench: explicit unavailable model, real worker errors, bounded retry and tenant isolation", async ({
  page,
  browser,
}, info) => {
  test.slow();
  const a = JSON.parse(fixture("create"));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const viewerContext = await browser.newContext({
    baseURL: process.env.WEB_BASE_URL || "http://localhost:3000",
    viewport: page.viewportSize() || undefined,
  });
  try {
    await login(page, a.email, a.password);
    const me = await (await page.request.get("/api/auth/me")).json();
    const headers = {
      Origin: process.env.WEB_BASE_URL || "http://localhost:3000",
      "x-csrf-token": me.csrf_token,
    };
    const project = await (
      await page.request.post(`/api/organizations/${a.org_id}/projects`, {
        headers,
        data: {
          name: "Agent 工作流验证（合成演示）",
          description: "浏览器验证，不调用外部模型",
        },
      })
    ).json();
    expect(
      (
        await page.request.put(
          `/api/organizations/${a.org_id}/projects/${project.id}/members`,
          { headers, data: { user_id: a.viewer_id, role: "viewer" } },
        )
      ).ok(),
    ).toBeTruthy();
    await page.goto("/agents");
    await page.getByLabel("当前机构").selectOption(a.org_id);
    await expect(page.getByLabel("工作流")).toBeVisible();
    await expect(
      page.getByText("尚未配置生成模型", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "模型未配置，暂不可提交", exact: true }),
    ).toBeDisabled();
    await page.getByLabel("工作流").selectOption("project_match");
    await expect(page.getByLabel("机构投资 Thesis")).toBeVisible();
    await page.getByLabel("工作流").selectOption("bp_screening");
    await expect(
      page.getByText(
        "当前项目没有已完成索引且获授权的文档，请先到私有知识库上传。",
        { exact: true },
      ),
    ).toBeVisible();
    await page.getByLabel("工作流").selectOption("due_diligence");
    const base = `/api/organizations/${a.org_id}/projects/${project.id}/agent-tasks`;
    const submitted = await page.request.post(base, {
      headers,
      data: {
        kind: "due_diligence",
        question: "请列出授权资料中的缺口；本任务只验证模型未配置错误。",
        idempotency_key: crypto.randomUUID(),
      },
    });
    expect(submitted.status()).toBe(202);
    const task = await submitted.json();
    await page.getByRole("button", { name: "刷新任务", exact: true }).click();
    const row = page.locator(".agent-task-row");
    await expect(row).toContainText("模型尚未配置", { timeout: 20000 });
    await expect(row).toContainText("第 1 次执行");
    await page.getByRole("button", { name: "查看任务", exact: true }).click();
    await expect(page.locator(".agent-detail")).toContainText(
      "尚未调用模型；不伪造 token 或费用数据。",
    );
    for (let attempt = 2; attempt <= 3; attempt++) {
      await page.getByRole("button", { name: "重试任务", exact: true }).click();
      await expect(row).toContainText(`第 ${attempt} 次执行`, {
        timeout: 15000,
      });
      await expect(row).toContainText("执行失败");
    }
    await expect(
      page.getByRole("button", { name: "重试任务", exact: true }),
    ).toHaveCount(0);
    mkdirSync(path.join(artifactRoot, "stage5"), { recursive: true });
    await page.screenshot({
      path: path.join(
        artifactRoot,
        "stage5",
        `agents-${info.project.name}.png`,
      ),
      fullPage: true,
    });
    const viewer = await viewerContext.newPage();
    await login(viewer, a.viewer_email, a.password);
    await viewer.goto("/agents");
    await expect(
      viewer.getByText("当前项目为只读，不能创建、重试或取消研究任务。", {
        exact: true,
      }),
    ).toBeVisible();
    expect((await viewer.request.get(`${base}/${task.id}`)).status()).toBe(404);
    await page.getByLabel("当前机构").selectOption(a.other_org_id);
    await expect(
      page.getByText("暂无获授权项目，请先创建项目或联系项目管理员。", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.locator(".agent-detail")).toHaveCount(0);
    expect(errors).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  } finally {
    await viewerContext.close();
    fixture("cleanup", a.key);
  }
});
