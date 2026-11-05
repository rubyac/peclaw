import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(process.cwd(), "../..");
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
test("private knowledge: worker, original download, versions, ACL and deletion", async ({
  page,
  browser,
}) => {
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
    const created = await page.request.post(
      `/api/organizations/${a.org_id}/projects`,
      { headers, data: { name: "知识库测试", description: "合成资料" } },
    );
    expect(created.status()).toBe(201);
    const p = await created.json();
    expect(
      (
        await page.request.put(
          `/api/organizations/${a.org_id}/projects/${p.id}/members`,
          { headers, data: { user_id: a.viewer_id, role: "viewer" } },
        )
      ).ok(),
    ).toBeTruthy();
    const url = `/knowledge?organization=${a.org_id}&project=${p.id}`;
    await page.goto(url);
    await page.getByLabel("文档名称", { exact: true }).fill("合成盈利研究");
    await page.getByLabel("文档文件", { exact: true }).setInputFiles({
      name: "research.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# 盈利情况\n企业盈利能力持续改善，利润增长来自先进封装设备销售。浏览器独有原文。",
      ),
    });
    await page
      .getByRole("button", { name: "上传并建立索引", exact: true })
      .click();
    await expect(page.locator(".private-doc-row")).toContainText("已可检索", {
      timeout: 45000,
    });
    await expect(page.locator(".citation-card").first()).toContainText(
      "浏览器独有原文",
    );
    const downloaded = page.waitForEvent("download");
    await page
      .getByRole("link", { name: "下载此版本原文件", exact: true })
      .click();
    const file = await downloaded;
    expect(file.suggestedFilename()).toBe("research.md");
    expect(readFileSync((await file.path())!, "utf8")).toContain(
      "浏览器独有原文",
    );
    await page
      .getByLabel("研究问题 / 关键词", { exact: true })
      .fill("企业盈利");
    await page.getByLabel("检索方式", { exact: true }).selectOption("semantic");
    await page
      .getByRole("button", { name: "检索原文证据", exact: true })
      .click();
    await expect(page.locator(".search-citation")).toContainText(
      "浏览器独有原文",
    );
    await page
      .getByRole("link", { name: "定位文档版本 →", exact: true })
      .click();
    await expect(page).toHaveURL(/document=.+&version=1/);
    await expect(page.locator(".citation-card").first()).toContainText(
      "浏览器独有原文",
    );
    await page.getByText("上传新版本", { exact: true }).click();
    await page.getByLabel("新版本文件", { exact: true }).setInputFiles({
      name: "research-v2.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# 新版研究\n新版研发验证进度有待核验，禁止把原文直接当作事实。",
      ),
    });
    await page.getByRole("button", { name: "保存新版本", exact: true }).click();
    await expect(page.locator(".private-doc-row")).toContainText(
      "v2 · research-v2.md · 已可检索",
      { timeout: 45000 },
    );
    await page.getByLabel("查看版本", { exact: true }).selectOption("1");
    await expect(
      page
        .locator(".citation-card")
        .filter({ hasText: "浏览器独有原文" })
        .first(),
    ).toBeVisible();
    await page
      .getByLabel("研究问题 / 关键词", { exact: true })
      .fill("浏览器独有原文");
    await page.getByLabel("检索方式", { exact: true }).selectOption("keyword");
    await page
      .getByRole("button", { name: "检索原文证据", exact: true })
      .click();
    await expect(
      page.getByText("暂无授权范围内的匹配原文。", { exact: true }),
    ).toBeVisible();
    await expect(page.locator(".search-citation")).toHaveCount(0);
    const viewer = await viewerContext.newPage();
    await login(viewer, a.viewer_email, a.password);
    await viewer.goto(url);
    await expect(viewer.locator(".private-doc-row")).toContainText(
      "合成盈利研究",
    );
    await expect(
      viewer.getByRole("button", { name: "上传并建立索引", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "文档权限", exact: true }).click();
    await page
      .getByLabel("文档可见范围", { exact: true })
      .selectOption("restricted");
    await page
      .getByRole("button", { name: "保存文档权限", exact: true })
      .click();
    await expect(page.getByRole("heading", { name: /文档权限 ·/ })).toHaveCount(
      0,
    );
    await viewer.reload();
    await expect(
      viewer.getByText("暂无获授权文档。", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "文档权限", exact: true }).click();
    await page
      .getByLabel("Browser viewer 文档权限", { exact: true })
      .selectOption("reader");
    await page
      .getByRole("button", { name: "保存文档权限", exact: true })
      .click();
    await expect(page.getByRole("heading", { name: /文档权限 ·/ })).toHaveCount(
      0,
    );
    await viewer.reload();
    await expect(viewer.locator(".private-doc-row")).toContainText(
      "合成盈利研究",
    );
    await viewer
      .getByRole("button", { name: "查看原文片段", exact: true })
      .click();
    await expect(viewer.locator(".citation-card").first()).toContainText(
      "新版研发验证",
    );
    await page
      .getByRole("button", { name: "查看原文片段", exact: true })
      .click();
    await page.getByText("删除文档及全部版本", { exact: true }).click();
    await page
      .getByLabel("确认移除全部索引并清理原文，删除后无法通过应用恢复。", {
        exact: true,
      })
      .check();
    await page
      .getByRole("button", { name: "确认删除文档", exact: true })
      .click();
    await expect(page.locator(".private-doc-row")).toHaveCount(0);
    await page.getByLabel("显示删除记录", { exact: true }).check();
    await expect(page.locator(".private-doc-row")).toContainText(
      "原文与索引已清理",
      { timeout: 20000 },
    );
    await viewer.reload();
    await expect(
      viewer.getByText("暂无获授权文档。", { exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  } finally {
    await viewerContext.close();
    fixture("cleanup", a.key);
  }
});
