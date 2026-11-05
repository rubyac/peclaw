import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(process.cwd(), "../..");
const source = readFileSync(
  path.join(root, "tests/fixtures/browser_accounts.py"),
  "utf8",
);
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
    { cwd: root, input: source, encoding: "utf8" },
  );
}
async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

test("public catalog: licensed source, live worker import, evidence, edit, reversible merge and reader isolation", async ({
  page,
  browser,
}) => {
  test.slow();
  const account = JSON.parse(fixture("create-catalog"));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const viewerContext = await browser.newContext({
    viewport: page.viewportSize() || undefined,
    baseURL: process.env.WEB_BASE_URL || "http://localhost:3000",
  });
  try {
    await login(page, account.email, account.password);
    await page.goto("/catalog");
    const sourcePanel = page.locator("section").filter({
      has: page.getByRole("heading", { name: "登记公开来源", exact: true }),
    });
    const sourceName = `Browser source ${account.key}`;
    await sourcePanel.getByLabel("来源名称", { exact: true }).fill(sourceName);
    await sourcePanel
      .getByLabel("允许用途 / 授权范围", { exact: true })
      .fill("仅供本次自动化演示测试使用，全部企业与信息为合成资料。");
    await sourcePanel.getByRole("checkbox").check();
    await sourcePanel
      .getByRole("button", { name: "登记来源", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText("已保存");
    const importPanel = page.locator("section").filter({
      has: page.getByRole("heading", {
        name: "CSV / XLSX 企业批量导入",
        exact: true,
      }),
    });
    const companyName = `Browser Company ${account.key}`;
    const duplicateName = `Browser Company ${account.key} old`;
    const alias = `Browser Alias ${account.key}`;
    const csv = `canonical_name,aliases,country,province,listing_status,company_stage,industries,technologies,technology_excerpt\n${companyName},${alias},中国,江苏,unknown,pilot,Browser Industry ${account.key},Browser Tech ${account.key},这是合成测试资料中的技术关联原文。\n${duplicateName},,unknown,江苏,unknown,unknown,Browser Industry ${account.key},,\n`;
    await importPanel.getByLabel("导入文件", { exact: true }).setInputFiles({
      name: "companies.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv),
    });
    await importPanel
      .getByRole("combobox", { name: "导入来源", exact: true })
      .selectOption({ label: sourceName });
    await importPanel
      .getByLabel("导入原因", { exact: true })
      .fill("浏览器端到端测试导入");
    await importPanel.getByRole("checkbox").check();
    await importPanel
      .getByRole("button", { name: "提交导入任务", exact: true })
      .click();
    await expect(page.locator(".import-job").first()).toContainText("已完成", {
      timeout: 20000,
    });
    await expect(page.locator(".import-counts").first()).toContainText(
      "已创建：2",
    );
    await page.goto("/industry");
    await page
      .getByRole("button", {
        name: `Browser Industry ${account.key} →`,
        exact: true,
      })
      .click();
    await expect(page.locator(".company-card")).toHaveCount(2);
    await page
      .getByRole("button", { name: `Browser Tech ${account.key}`, exact: true })
      .click();
    await expect(page.locator(".company-card")).toHaveCount(1);
    await page.goto("/companies");
    await page
      .getByRole("combobox", { name: "上市状态", exact: true })
      .selectOption("unlisted");
    await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await expect(
      page.getByText("暂无符合条件的企业档案。", { exact: false }),
    ).toBeVisible();
    await page
      .getByRole("combobox", { name: "上市状态", exact: true })
      .selectOption("");
    await page.getByLabel("名称或别名", { exact: true }).fill(alias);
    await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await page
      .locator(".company-card")
      .filter({ hasText: companyName })
      .click();
    await expect(
      page.getByRole("heading", { name: companyName, exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".facts-grid>div").filter({ hasText: "融资阶段" }),
    ).toContainText("未知");
    const id = page.url().split("/").pop();
    await page.getByRole("button", { name: "编辑企业", exact: true }).click();
    await page
      .getByLabel("标准企业名称", { exact: true })
      .fill(companyName + " updated");
    await page
      .getByLabel("变更原因", { exact: true })
      .fill("浏览器测试核对名称后修正");
    await page
      .getByRole("button", { name: "保存企业修改", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: companyName + " updated",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByText("登记新的原文证据", { exact: true }).click();
    await page
      .getByLabel("支持的具体主张", { exact: true })
      .fill("合成资料中的人工证据");
    await page
      .getByLabel("原文摘录", { exact: true })
      .fill("本条证据用于自动化验证定位与人工核验，不代表真实企业经营事实。");
    await page.getByRole("button", { name: "保存证据", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "合成资料中的人工证据", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "检查疑似重复", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "归入本主档案的候选", exact: true })
      .selectOption({ label: duplicateName });
    await page
      .getByLabel("人工确认依据", { exact: true })
      .fill("仅在测试中确认两个合成档案关联");
    await page.getByRole("checkbox").check();
    await page
      .getByRole("button", { name: "确认合并并保留原档案", exact: true })
      .click();
    await expect(
      page.getByText("关联原始档案：", { exact: false }),
    ).toBeVisible();
    await page
      .getByLabel("撤销合并原因", { exact: true })
      .fill("验证可以撤销并恢复原始档案");
    await page.getByRole("button", { name: "撤销此合并", exact: true }).click();
    await expect(page.getByLabel("撤销合并原因", { exact: true })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("heading", { name: "合成资料中的人工证据", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const viewer = await viewerContext.newPage();
    await login(viewer, account.viewer_email, account.password);
    await viewer.goto(`/companies/${id}`);
    await expect(
      viewer.getByRole("heading", {
        name: companyName + " updated",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      viewer.getByRole("button", { name: "编辑企业", exact: true }),
    ).toHaveCount(0);
    await viewer.goto("/catalog");
    await expect(
      viewer.getByText("公共数据发布需要部署管理员授予", { exact: false }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await viewerContext.close();
    fixture("cleanup", account.key);
  }
});
