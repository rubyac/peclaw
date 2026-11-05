import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "../..");
const script = readFileSync(
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
    { cwd: root, input: script, encoding: "utf8" },
  );
}
async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByLabel("当前机构")).toBeEnabled();
}

test("authenticated workspace: tenant switch, project permissions, revocation and audit", async ({
  page,
  browser,
}) => {
  const account = JSON.parse(fixture("create"));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const viewerContext = await browser.newContext({
    viewport: page.viewportSize() || undefined,
    baseURL: process.env.WEB_BASE_URL || "http://localhost:3000",
  });
  try {
    await login(page, account.email, account.password);
    await page.getByLabel("当前机构").selectOption(account.org_id);
    await expect(
      page.getByText("暂无获授权的项目。", { exact: false }),
    ).toBeVisible();
    await page.getByLabel("项目名称", { exact: true }).fill("先进封装测试项目");
    await page
      .getByLabel("项目说明", { exact: true })
      .fill("仅用于自动化浏览器验证");
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page.getByRole("button", { name: /先进封装测试项目/ }).click();
    await page
      .getByLabel("修改项目名称", { exact: true })
      .fill("已更新的研究项目");
    await page.getByRole("button", { name: "保存项目", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "已更新的研究项目", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("combobox", { name: "机构成员", exact: true })
      .selectOption(account.viewer_id);
    await page
      .getByRole("combobox", { name: "项目角色", exact: true })
      .selectOption("viewer");
    await page
      .getByRole("button", { name: "保存项目权限", exact: true })
      .click();
    await expect(page.locator(".people-list")).toContainText(
      account.viewer_email,
    );
    const viewer = await viewerContext.newPage();
    await login(viewer, account.viewer_email, account.password);
    await expect(
      viewer.getByRole("button", { name: /已更新的研究项目/ }),
    ).toBeVisible();
    await expect(
      viewer.getByRole("button", { name: "创建项目", exact: true }),
    ).toHaveCount(0);
    await viewer.getByRole("button", { name: /已更新的研究项目/ }).click();
    await expect(
      viewer.getByLabel("修改项目名称", { exact: true }),
    ).toHaveCount(0);
    await page.getByLabel("当前机构").selectOption(account.other_org_id);
    await expect(
      page.getByText("暂无获授权的项目。", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /已更新的研究项目/ }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "机构成员", exact: false }).click();
    await page.getByLabel("当前机构").selectOption(account.org_id);
    const member = page
      .locator(".member-row")
      .filter({ hasText: account.viewer_email });
    await member.getByRole("button", { name: "停用成员", exact: true }).click();
    await expect(member.getByText("已停用", { exact: true })).toBeVisible();
    await viewer.reload();
    await expect(
      viewer.getByText("尚无可访问的机构，请联系管理员。", { exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: /操作审计/ }).click();
    await page.getByLabel("当前机构").selectOption(account.org_id);
    await expect(page.locator(".audit-list")).toContainText(
      "membership.update",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("button", { name: "退出登录", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/projects");
    await expect(page).toHaveURL(/\/login$/);
    expect(errors).toEqual([]);
  } finally {
    await viewerContext.close();
    fixture("cleanup", account.key);
  }
});

test("anonymous UI redirects and BFF rejects an untrusted login origin", async ({
  page,
  request,
}) => {
  await page.goto("/members");
  await expect(page).toHaveURL(/\/login$/);
  const response = await request.post("/api/auth/login", {
    headers: { Origin: "https://evil.example" },
    data: { email: "missing@example.com", password: "not-an-account-password" },
  });
  expect(response.status()).toBe(403);
  expect((await response.json()).error.code).toBe("INVALID_ORIGIN");
  expect((await request.get("/api/unknown-path")).status()).toBe(404);
});
