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
test("reports: manual template, numeric gate, independent review, real downloads and revocation", async ({
  page,
  browser,
}, info) => {
  test.slow();
  const a = JSON.parse(fixture("create-reports"));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const peerContext = await browser.newContext({
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
    const response = await page.request.post(
      `/api/organizations/${a.org_id}/projects`,
      { headers, data: { name: "报告审核流程（合成演示）" } },
    );
    expect(response.status()).toBe(201);
    const project = await response.json();
    expect(
      (
        await page.request.put(
          `/api/organizations/${a.org_id}/projects/${project.id}/members`,
          { headers, data: { user_id: a.viewer_id, role: "editor" } },
        )
      ).ok(),
    ).toBeTruthy();
    const docBase = `/api/organizations/${a.org_id}/projects/${project.id}/documents`;
    const quote = "2025年营业收入为1.2亿元人民币。仅为合成演示，未经业务核实。";
    const uploaded = await page.request.post(docBase, {
      headers,
      data: {
        title: "财务原文（合成演示）",
        filename: "synthetic-financial.txt",
        content_base64: Buffer.from(quote).toString("base64"),
        idempotency_key: crypto.randomUUID(),
      },
    });
    expect(uploaded.status()).toBe(202);
    const doc = await uploaded.json();
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`${docBase}/${doc.id}`)).json())
            .current.status,
        { timeout: 30000 },
      )
      .toBe("indexed");
    await page.goto("/reports");
    await page.getByLabel("当前机构").selectOption(a.org_id);
    await page
      .getByLabel("报告标题", { exact: true })
      .fill("财务核验研究（合成演示）");
    await page
      .getByLabel("报告模板", { exact: true })
      .selectOption("company_profile");
    await page.getByRole("checkbox", { name: /财务原文（合成演示）/ }).check();
    await page
      .getByRole("button", { name: "创建报告草稿", exact: true })
      .click();
    await expect(page.locator(".report-detail")).toContainText("财务核验研究");
    await page.getByText("编辑报告正文", { exact: true }).click();
    await page
      .getByLabel("摘要内容", { exact: true })
      .fill("营业收入为1.2亿元。");
    await page
      .getByLabel("摘要分类", { exact: true })
      .selectOption("unverified");
    await page
      .getByLabel("摘要引用", { exact: true })
      .selectOption({ index: 0 });
    await page
      .getByRole("button", { name: "保存正文并撤销旧批准", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "报告质量闸" }),
    ).toContainText("正文数字");
    await expect(
      page.getByLabel("导出用途").locator('option[value="formal"]'),
    ).toHaveJSProperty("disabled", true);
    let downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载报告", exact: true }).click();
    let downloaded = await downloadPromise;
    expect(downloaded.suggestedFilename()).toMatch(/draft.*\.md$/);
    expect(readFileSync((await downloaded.path())!, "utf8")).toContain(
      "未审核",
    );
    await page.getByLabel("数字名称", { exact: true }).fill("营业收入");
    await page.getByLabel("数值（不适用时留空）", { exact: true }).fill("1.2");
    await page.getByLabel("单位", { exact: true }).fill("亿元");
    await page.getByLabel("币种", { exact: true }).selectOption("CNY");
    await page.getByLabel("期间", { exact: true }).fill("2025年");
    await page
      .getByLabel("数字来源", { exact: true })
      .selectOption({ index: 1 });
    await page.getByLabel("精确引用原文", { exact: true }).fill(quote);
    await page
      .getByLabel("登记备注", { exact: true })
      .fill("合成数据，仅用于验证审核流程。");
    await page
      .getByRole("button", { name: "登记关键数字", exact: true })
      .click();
    await expect(page.locator(".report-metric")).toContainText("未核验");
    await page
      .getByLabel("指定独立审核人", { exact: true })
      .selectOption(a.viewer_id);
    await page.getByRole("button", { name: "保存审核人", exact: true }).click();
    await page
      .getByRole("button", { name: "提交当前修订审核", exact: true })
      .click();
    await expect(page.locator(".report-detail")).toContainText("待独立审核");
    const peer = await peerContext.newPage();
    peer.on("pageerror", (e) => errors.push(e.message));
    await login(peer, a.viewer_email, a.password);
    await peer.goto("/reports");
    await peer.getByRole("button", { name: "打开报告", exact: true }).click();
    await expect(
      peer.getByRole("button", { name: "质量闸未通过，不能批准", exact: true }),
    ).toBeDisabled();
    await peer
      .getByLabel("营业收入核验结论", { exact: true })
      .selectOption("verified");
    await peer
      .getByLabel("数字核验说明", { exact: true })
      .fill("已逐项对照原文检查数值、单位、币种和期间。");
    await peer
      .getByRole("button", { name: "保存数字核验", exact: true })
      .click();
    await expect(
      peer.getByRole("region", { name: "报告质量闸" }),
    ).toContainText("机械质量检查通过");
    for (const name of [
      "已逐条核对引用与原文定位",
      "已核对事实与推断分类",
      "已确认关键数字登记完整且逐项核验",
      "已核对来源冲突并处理缺口",
      "已确认没有静默补全或虚构数据",
    ])
      await peer.getByRole("checkbox", { name, exact: true }).check();
    await peer
      .getByLabel("审核意见", { exact: true })
      .fill("已完成合成资料的独立审核，仅验证流程，不代表真实企业结论。");
    await peer
      .getByRole("button", { name: "保存审核结论", exact: true })
      .click();
    await expect(peer.locator(".report-detail")).toContainText(
      "已批准正式导出",
    );
    await page.getByRole("button", { name: "刷新报告", exact: true }).click();
    await expect(page.locator(".report-detail")).toContainText(
      "已批准正式导出",
    );
    await page.getByLabel("导出用途", { exact: true }).selectOption("formal");
    await page.getByLabel("文件格式", { exact: true }).selectOption("docx");
    downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载报告", exact: true }).click();
    downloaded = await downloadPromise;
    expect(downloaded.suggestedFilename()).toMatch(/formal.*\.docx$/);
    const xml = execFileSync(
      "python",
      [
        "-c",
        'import sys,zipfile;print(zipfile.ZipFile(sys.argv[1]).read("word/document.xml").decode())',
        (await downloaded.path())!,
      ],
      { encoding: "utf8" },
    );
    expect(xml).toContain("正式导出");
    expect(xml).toContain("1.2");
    await expect(page.locator(".report-detail")).toContainText("已正式导出");
    await page
      .getByRole("button", { name: "查看该次审核快照", exact: true })
      .last()
      .click();
    await expect(page.locator(".report-review-snapshot")).toContainText(
      "财务核验研究（合成演示）",
    );
    await expect(page.locator(".report-review-snapshot")).toContainText(
      "已核验",
    );
    mkdirSync(path.join(artifactRoot, "stage6"), { recursive: true });
    await page.screenshot({
      path: path.join(
        artifactRoot,
        "stage6",
        `reports-author-${info.project.name}.png`,
      ),
      fullPage: true,
    });
    await peer.screenshot({
      path: path.join(
        artifactRoot,
        "stage6",
        `reports-reviewer-${info.project.name}.png`,
      ),
      fullPage: true,
    });
    await page
      .getByLabel("修改报告标题", { exact: true })
      .fill("修改后的报告（合成演示）");
    await page
      .getByRole("button", { name: "保存正文并撤销旧批准", exact: true })
      .click();
    await expect(
      page.getByLabel("导出用途").locator('option[value="formal"]'),
    ).toHaveJSProperty("disabled", true);
    expect(
      (
        await page.request.put(`${docBase}/${doc.id}/permissions`, {
          headers,
          data: {
            expected_revision: 1,
            access_scope: "restricted",
            grants: [{ user_id: me.user.id, role: "editor" }],
          },
        })
      ).ok(),
    ).toBeTruthy();
    await peer.getByRole("button", { name: "刷新报告", exact: true }).click();
    await expect(peer.locator(".report-detail")).toHaveCount(0);
    await expect(
      peer.getByRole("alert").filter({ hasText: "资源不存在" }),
    ).toBeVisible();
    expect(errors).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  } finally {
    await peerContext.close();
    fixture("cleanup", a.key);
  }
});
