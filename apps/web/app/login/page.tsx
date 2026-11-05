"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return (
    <main className="login-page">
      <Link href="/" className="brand">
        PEClaw<span className="brand-dot">.</span>
      </Link>
      <div className="login-card">
        <div className="eyebrow">PRIVATE WORKSPACE</div>
        <h1>登录机构工作空间</h1>
        <p>使用已由管理员开通的账号，访问你获授权的项目。</p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setError("");
            setPending(true);
            const data = new FormData(event.currentTarget);
            try {
              await api("auth/login", {
                method: "POST",
                body: JSON.stringify({
                  email: data.get("email"),
                  password: data.get("password"),
                }),
              });
              router.replace("/projects");
            } catch (error) {
              setError(error instanceof Error ? error.message : "登录失败");
            } finally {
              setPending(false);
            }
          }}
        >
          <label>
            邮箱
            <input
              name="email"
              type="email"
              autoComplete="username"
              required
              maxLength={254}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
            />
          </label>
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={pending}>
            {pending ? "登录中…" : "登录"}
          </button>
        </form>
        <p className="form-note">
          尚无账号？请联系部署管理员开通。本系统不开放自行注册。
        </p>
      </div>
      <Link href="/" className="back-link">
        ← 返回工作台
      </Link>
    </main>
  );
}
