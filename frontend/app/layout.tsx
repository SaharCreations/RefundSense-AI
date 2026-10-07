import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "RefundSense · Review workspace",
  description:
    "Policy evidence, deterministic refund assessments, and human approval.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
