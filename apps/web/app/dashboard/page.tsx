import {Suspense} from "react";
import { AppShell } from "../../components/app-shell";
import { Dashboard } from "../../components/dashboard";

export default function DashboardPage() {
  return <AppShell active="dashboard"><Suspense fallback={<p>正在读取近况…</p>}><Dashboard /></Suspense></AppShell>;
}
