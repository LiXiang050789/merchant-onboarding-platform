import type {Metadata} from "next";
import "./globals.css";
import {QueryProvider} from "@/shared/query/query-client";

export const metadata: Metadata = {
  title: "Merchant Onboarding Platform",
  description: "B-side merchant onboarding operations console"
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="zh-CN">
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
