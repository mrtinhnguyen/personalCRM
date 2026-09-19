import type { Metadata } from "next";
import "./globals.css";
import "./notebook.css";
import { PwaRegister } from "../components/pwa-register";

export const metadata: Metadata = {
  title: "Monica Next CRM",
  description: "A private relationship CRM with source-aware history",
  manifest: "/manifest.webmanifest"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><PwaRegister />{children}</body></html>;
}
