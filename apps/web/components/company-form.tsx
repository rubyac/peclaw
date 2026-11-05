"use client";
import { type FormEvent } from "react";
import {
  type Company,
  type Source,
  type Taxonomy,
  labels,
} from "@/lib/catalog";
export function CompanyForm({
  record,
  sources,
  taxonomy,
  busy,
  onSubmit,
}: {
  record?: Company;
  sources: Source[];
  taxonomy: Taxonomy;
  busy: boolean;
  onSubmit: (data: FormData) => Promise<void>;
}) {
  return (
    <form
      className="catalog-form"
      onSubmit={(e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        void onSubmit(new FormData(e.currentTarget));
      }}
    >
      <label>
        标准企业名称
        <input
          name="canonical_name"
          required
          maxLength={200}
          defaultValue={record?.canonical_name}
        />
      </label>
      <label>
        登记名称
        <input
          name="registration_name"
          maxLength={200}
          defaultValue={record?.registration_name || ""}
        />
      </label>
      <label className="wide">
        别名（使用 | 分隔）
        <input name="aliases" defaultValue={record?.aliases.join("|") || ""} />
      </label>
      <label>
        统一社会信用代码
        <input
          name="unified_social_credit_code"
          maxLength={18}
          defaultValue={record?.unified_social_credit_code || ""}
        />
      </label>
      <label>
        官网地址
        <input
          name="website"
          type="url"
          defaultValue={record?.website || ""}
          placeholder="https://..."
        />
      </label>
      <label>
        国家或地区
        <input
          name="country"
          required
          maxLength={80}
          defaultValue={record?.country || "unknown"}
        />
      </label>
      <label>
        省份
        <input
          name="province"
          maxLength={80}
          defaultValue={record?.province || ""}
          placeholder="例如：江苏"
        />
      </label>
      <label>
        城市
        <input name="city" maxLength={80} defaultValue={record?.city || ""} />
      </label>
      <label>
        成立日期
        <input
          name="founded_on"
          type="date"
          defaultValue={record?.founded_on || ""}
        />
      </label>
      <label>
        上市状态
        <select
          name="listing_status"
          defaultValue={record?.listing_status || "unknown"}
        >
          {["unknown", "listed", "unlisted", "delisted"].map((v) => (
            <option key={v} value={v}>
              {labels[v]}
            </option>
          ))}
        </select>
      </label>
      <label>
        企业发展阶段
        <select
          name="company_stage"
          defaultValue={record?.company_stage || "unknown"}
        >
          {[
            "unknown",
            "research",
            "prototype",
            "pilot",
            "commercial",
            "scaled",
          ].map((v) => (
            <option key={v} value={v}>
              {labels[v]}
            </option>
          ))}
        </select>
      </label>
      <label>
        融资阶段
        <select
          name="financing_stage"
          defaultValue={record?.financing_stage || "unknown"}
        >
          {["unknown", "seed", "angel", "A", "B", "C", "pre_ipo", "other"].map(
            (v) => (
              <option key={v} value={v}>
                {labels[v]}
              </option>
            ),
          )}
        </select>
      </label>
      <label>
        产业节点（可多选）
        <select
          name="industry_ids"
          multiple
          size={3}
          defaultValue={record?.industry_ids || []}
        >
          {taxonomy.industries.map((n) => (
            <option key={n.id} value={n.id}>
              {"　".repeat(n.level - 1)}
              {n.name}
            </option>
          ))}
        </select>
      </label>
      <label className="wide">
        企业简介
        <textarea
          name="description"
          maxLength={10000}
          defaultValue={record?.description || ""}
        />
      </label>
      <label>
        资料来源
        <select
          name="source_id"
          required
          defaultValue={record?.source_id || sources[0]?.id || ""}
        >
          <option value="" disabled>
            请先登记公开来源
          </option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.source_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        变更原因
        <input
          name="reason"
          required
          minLength={3}
          maxLength={1000}
          placeholder="记录录入或修改依据"
        />
      </label>
      <p className="form-note wide">
        没有来源支持的字段请保留未知或留空。保存后仍为待核验档案；具体事实需另行登记原文证据，不会自动认定企业已具备量产能力。
      </p>
      <button className="primary" disabled={busy || !sources.length}>
        {busy ? "保存中…" : record ? "保存企业修改" : "创建企业档案"}
      </button>
    </form>
  );
}
