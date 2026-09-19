// Synthetic, read-only fixtures. This server never opens a database or an archive.
import http from 'node:http';
import { spawn } from 'node:child_process';

const apiPort = Number(process.env.DEMO_API_PORT || 4311);
const webPort = Number(process.env.DEMO_PORT || 4310);
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const name = n => `联系人 ${String(n).padStart(2, '0')}`;
const summaries = ['一起探索新的想法 · 设计与创作', '周末散步与城市观察 · 兴趣小组', '分享读书笔记 · 长期保持联系', '开源项目与技术交流 · 社区伙伴'];
const people = Array.from({ length: 24 }, (_, i) => ({ id: id(i + 1), display_name: name(i + 1), profile_type: 'person', summary: summaries[i % 4] }));
const tags = ['创作伙伴', '读书小组', '开源社区', '周末同行', '保持联系', '新朋友'].map((name, i) => ({ id: id(500 + i), name, people: 4, sources: ['manual'] }));
const monthly = [42, 57, 48, 68, 79, 63, 86, 95, 72].map((count, i) => ({ month: `2026-${String(i + 1).padStart(2, '0')}`, count }));
const leaders = [1, 7, 12, 4, 9].map((n, i) => ({ name: name(n), profile_id: id(n), value: 368 - 53 * i }));
const stats = {
  people: 128, authors: 86, posts: 610, likes: 2460, comments: 384, local_photo_posts: 256,
  first: '2026-01-01', latest: '2026-09-18', monthly, leaders, charts: [],
};
const timeline = [
  ['wechat', '周末的留白', '把周末留给散步、阅读和新的灵感。这里的文字是专为开源展示编写的虚构示例。'],
  ['instagram', '收集日常的颜色', '一些关于颜色、光线与日常观察的小记录。演示动态不对应任何真实账号。'],
  ['linkedin', '一起把想法变成作品', '完成了一次社区项目分享。很高兴看见新的想法从讨论走向实践。'],
  ['wechat', '下一次见面', '为下一次读书小组准备了一份小小的清单。期待继续交换有趣的想法。'],
].map(([provider, title, summary], i) => ({ id: `demo-event-${i}`, profile_id: id(i + 1), profile_name: name(i + 1), provider, title, summary, occurred_at: `2026-09-${18 - i}T12:00:00Z`, cursor: `demo-${i}`, media: [], like_count: 12 + i * 7, comment_count: 3 + i }));
const graphNodes = Array.from({ length: 72 }, (_, i) => ({ u: `demo-${i}`, hash: id(i + 1), name: name(i + 1), known: true, community: Math.floor(i / 12), x: Math.cos(i * 2.4) * (0.09 + i % 12 / 80), y: Math.sin(i * 2.4) * (0.09 + i % 12 / 80), deg: 5, facts: [24, 8, 3, 0, 0, 0] }));
const graphEdges = graphNodes.flatMap((_, i) => [1, 2, 4].map(offset => ({ a: i, b: Math.floor(i / 12) * 12 + (i + offset) % 12, direct: 4 + i % 8, w: 4 + i % 8, group: 0, ab: [3, 1, 0, 0], ba: [2, 1, 0, 0] })));
for (let i = 0; i < 5; i++) graphEdges.push({ a: i * 12, b: (i + 1) * 12, direct: 3, w: 3, group: 0, ab: [1, 1, 0, 0], ba: [1, 0, 0, 0] });

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  let body;
  if (req.method !== 'GET') {
    res.writeHead(405, { 'Content-Type': 'application/json', Allow: 'GET' });
    return res.end(JSON.stringify({ detail: 'Read-only synthetic demo. Changes are disabled.' }));
  }
  switch (url.pathname) {
    case '/api/v1/me': body = { id: id(999), email: 'demo@example.test' }; break;
    case '/api/v1/metrics/people-overview': body = { people: 128, groups: 12, companies: [{ name: '示例设计工作室', count: 18 }, { name: '示例开源社区', count: 12 }], schools: [{ name: '示例艺术学院', count: 16 }, { name: '示例科技学院', count: 9 }] }; break;
    case '/api/v1/metrics/social': body = { as_of: '2026-09-18T12:00:00Z', scope: 'synthetic-demo', providers: { wechat: { ...stats, groups: 12, conversations: 64, indexed_messages: 4200, chat: { contacts: 64, messages: 4200, sent: 1900, received: 2300, leaders, group_leaders: leaders.map((r, i) => ({ ...r, name: `兴趣小组 ${i + 1}`, value: 280 - i * 36 })) } }, instagram: { ...stats, people: 64, authors: 42, posts: 312, likes: 1800 }, linkedin: { ...stats, people: 48, authors: 24, posts: 186, charts: [{ title: '工作领域', denominator: 48, filter: 'company', rows: [{ name: '示例设计工作室', profile_id: id(1), count: 18 }, { name: '示例开源社区', profile_id: id(2), count: 12 }] }] } } }; break;
    case '/api/v1/metrics/locations': body = { points: [], people: 0, place_count: 0, located_records: 0, post_records: 0, profile_records: 0, years: [], unresolved: [] }; break;
    case '/api/v1/timeline': body = timeline.filter(row => !url.searchParams.has('provider') || row.provider === url.searchParams.get('provider')); break;
    case '/api/v1/profiles': {
      const q = (url.searchParams.get('q') || '').toLowerCase();
      const tag = tags.findIndex(row => row.id === url.searchParams.get('tag'));
      body = url.searchParams.get('profile_type') === 'group' ? [] : people.filter((row, i) => `${row.display_name} ${row.summary}`.toLowerCase().includes(q) && (tag < 0 || i % tags.length === tag));
      break;
    }
    case '/api/v1/tags': body = tags; break;
    case '/api/v1/relationships/graph': body = { nodes: graphNodes, edges: graphEdges, self_wxid: 'demo-owner' }; break;
    default: {
      const event = timeline.find(row => url.pathname === `/api/v1/timeline/${row.id}`);
      if (event) body = { ...event, content: { text: event.summary }, interactions: [] };
      else { res.writeHead(404, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify({ detail: 'This endpoint is outside the synthetic showcase.' })); }
    }
  }
  res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
});

server.listen(apiPort, '127.0.0.1', () => {
  const web = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', 'apps/web', '--hostname', '127.0.0.1', '--port', String(webPort)], {
    stdio: 'inherit', env: { ...process.env, API_INTERNAL_URL: `http://127.0.0.1:${apiPort}`, NEXT_PUBLIC_DEMO_MODE: '1', NEXT_TELEMETRY_DISABLED: '1' },
  });
  console.log(`Synthetic showcase: http://127.0.0.1:${webPort}/dashboard`);
  const stop = () => { web.kill('SIGTERM'); server.close(); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  web.on('exit', code => { server.close(); process.exitCode = code || 0; });
});
