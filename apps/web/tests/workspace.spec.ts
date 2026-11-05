import { expect, test } from "@playwright/test";

test("shows live API readiness and refreshes without browser errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "让研究有据可循",
  );
  await expect(page.getByRole("status")).toHaveText(
    "前端已连接 API，所有依赖就绪",
  );
  await expect(page.locator(".service .healthy")).toHaveCount(3);
  await page.getByRole("button", { name: /刷新状态/ }).click();
  await expect(page.getByRole("button", { name: /刷新状态/ })).toBeEnabled();
  await expect(page.getByRole("status")).toContainText("所有依赖就绪");
  expect(errors).toEqual([]);
});

test("navigation and viewport fit remain usable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /功能规划/ }).click();
  await expect(page).toHaveURL(/#modules$/);
  await expect(
    page.getByRole("heading", { name: "研究工作空间" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("link", { name: /开发路线/ })
    .first()
    .click();
  await expect(page).toHaveURL(/#roadmap$/);
});
