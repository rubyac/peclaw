import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, copyFileSync } from "node:fs";
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
test("evaluation: real retrieval score, unavailable model excluded, attributed feedback and live revocation", async ({
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
      { headers, data: { name: "试点评测（合成演示）" } },
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
    const upload = await page.request.post(docBase, {
      headers,
      data: {
        title: "评测原文（合成演示）",
        filename: "evaluation.txt",
        content_base64: Buffer.from(
          "客户验证评测独有词。本文为合成演示材料，结论尚需核实。",
        ).toString("base64"),
        idempotency_key: crypto.randomUUID(),
      },
    });
    expect(upload.status()).toBe(202);
    const doc = await upload.json();
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`${docBase}/${doc.id}`)).json())
            .current.status,
        { timeout: 30000 },
      )
      .toBe("indexed");
    await page.goto("/evaluation");
    await page.getByLabel("当前机构").selectOption(a.org_id);
    await page
      .getByLabel("查询或企业名称关键词", { exact: true })
      .fill("客户验证评测独有词");
    await page.getByLabel("返回上限 k", { exact: true }).fill("1");
    await page.getByLabel("明确相关", { exact: true }).selectOption(doc.id);
    await page
      .getByRole("button", { name: "添加评测案例", exact: true })
      .click();
    await page
      .getByLabel("案例类型", { exact: true })
      .selectOption("bp_screening");
    await page
      .getByLabel("预期陈述原文", { exact: true })
      .fill("尚无可评分的初筛结果，不编造结论。");
    await page
      .getByRole("button", { name: "添加评测案例", exact: true })
      .click();
    await page.getByLabel("评测集名称", { exact: true }).fill("合成试点评测");
    await page
      .getByLabel("指定独立评审", { exact: true })
      .selectOption(a.viewer_id);
    await page
      .getByLabel("来源、范围与标注说明", { exact: true })
      .fill("合成语料，仅用于检索评分和未配置模型状态回归，不代表客户效果。");
    await page
      .getByRole("checkbox", { name: /我确认有权在本项目中使用/ })
      .check();
    await page.getByRole("button", { name: /^保存评测集/ }).click();
    await expect(page.locator(".evaluation-dataset")).toContainText(
      "合成试点评测",
    );
    await page
      .getByRole("button", { name: "运行固定版本评测", exact: true })
      .click();
    await expect(page.locator(".evaluation-run")).toContainText("已完成测量", {
      timeout: 30000,
    });
    await expect(
      page.locator(".evaluation-case-result").filter({ hasText: "知识检索" }),
    ).toContainText("P@k");
    await expect(
      page.locator(".evaluation-case-result").filter({ hasText: "BP 初筛" }),
    ).toContainText("模型未配置，没有可评分结果");
    await expect(
      page
        .locator(".evaluation-metrics article")
        .filter({ hasText: "独立事实正确率" }),
    ).toContainText("未评测／未知");
    await page.getByLabel("业务可用性", { exact: true }).selectOption("true");
    await page
      .getByLabel("反馈依据与改进建议", { exact: true })
      .fill("作者自评：合成检索能定位，不能将缺少初筛结果当作模型通过。");
    await page.getByRole("button", { name: "提交反馈", exact: true }).click();
    await expect(page.locator(".evaluation-run")).toContainText("作者自评");
    const peer = await peerContext.newPage();
    peer.on("pageerror", (e) => errors.push(e.message));
    await login(peer, a.viewer_email, a.password);
    await peer.goto("/evaluation");
    await peer.getByRole("button", { name: "打开评测集", exact: true }).click();
    await peer
      .getByRole("button", { name: "查看本次结果", exact: true })
      .click();
    await peer.getByLabel("业务可用性", { exact: true }).selectOption("true");
    await peer
      .getByLabel("反馈依据与改进建议", { exact: true })
      .fill("独立反馈：已对照合成原文，检索相关；模型案例仍需真实结果再评。");
    await peer.getByRole("button", { name: "提交反馈", exact: true }).click();
    await expect(peer.locator(".evaluation-run")).toContainText("独立评审");
    await expect(
      peer
        .locator(".evaluation-metrics article")
        .filter({ hasText: "独立可用率" }),
    ).toContainText("未评测／未知");
    await page.getByRole("button", { name: "刷新评测", exact: true }).click();
    await expect(page.locator(".evaluation-run")).toContainText("独立反馈");
    mkdirSync(path.join(artifactRoot, "stage7"), { recursive: true });
    const exported = page.waitForEvent("download");
    await page
      .getByRole("link", { name: "下载评测证据 JSON", exact: true })
      .click();
    const file = await exported;
    const downloadPath = (await file.path())!;
    const evidence = JSON.parse(readFileSync(downloadPath, "utf8"));
    expect(evidence.data_kind).toBe("synthetic");
    expect(evidence.summary.measured_count).toBe(1);
    expect(
      evidence.records.find((r: { kind: string }) => r.kind === "bp_screening")
        .status,
    ).toBe("blocked");
    copyFileSync(
      downloadPath,
      path.join(
        artifactRoot,
        "stage7",
        `evaluation-result-${info.project.name}.json`,
      ),
    );

    await page.screenshot({
      path: path.join(
        artifactRoot,
        "stage7",
        `evaluation-${info.project.name}.png`,
      ),
      fullPage: true,
    });
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
    await peer.getByRole("button", { name: "刷新评测", exact: true }).click();
    await expect(peer.locator(".evaluation-run")).toHaveCount(0);
    await expect(
      peer.getByRole("alert").filter({ hasText: "资源不存在" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "撤销评审访问", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "撤销评审访问", exact: true }),
    ).toHaveCount(0);
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
