import {Suspense} from "react";
import { AppShell } from "../../components/app-shell";
import { ProfilesView } from "../../components/profiles-view";

export default function ProfilesPage() {
  return <AppShell active="profiles"><Suspense fallback={<div className="page-wrap">正在读取联系人…</div>}><ProfilesView /></Suspense></AppShell>;
}
