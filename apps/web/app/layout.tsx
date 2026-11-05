import type { Metadata } from "next";
import "./globals.css";
import "./auth.css";
import "./catalog.css";
import "./knowledge.css";
import "./agents.css";
import "./reports.css";
import "./evaluation.css";
export const metadata: Metadata = {
  title: "PEClaw · 产业情报与投资工作台",
  description: "可追溯的产业情报与机构私有知识工作台",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
