import { Suspense } from "react";
import { AppShell } from "../../components/app-shell";
import { SearchView } from "../../components/search-view";
export default function SearchPage(){return <AppShell active="search"><Suspense fallback={<p className="data-loading">正在读取搜索…</p>}><SearchView/></Suspense></AppShell>}
