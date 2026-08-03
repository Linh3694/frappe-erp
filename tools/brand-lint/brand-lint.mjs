#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// ⚠️  BẢN SAO. Nguồn: tools/brand-lint/brand-lint.mjs (thư mục gốc Codebase).
//     SỬA Ở NGUỒN rồi chạy `node tools/brand-lint/sync.mjs` để đồng bộ 5 bản.
//     Đừng sửa trực tiếp file này — lần sync sau sẽ ghi đè.
// ─────────────────────────────────────────────────────────────────────────────
/**
 * brand-lint — chặn hardcode thương hiệu lọt vào codebase (GD2-01 · PLAN-03 §2).
 *
 *   node brand-lint.mjs                       # mode=diff (mặc định) — chỉ soi dòng THÊM MỚI
 *   node brand-lint.mjs --mode=count          # đếm toàn bộ nợ hiện có, exit 0
 *   node brand-lint.mjs --mode=full           # soi toàn bộ, exit 1 nếu có error
 *   node brand-lint.mjs --base=origin/develop # nhánh so sánh cho mode=diff
 *   node brand-lint.mjs --json                # xuất JSON cho CI
 *
 * Bỏ qua một dòng cụ thể: thêm comment `brand-lint-disable-next-line <rule-id> — <lý do>`
 * ở dòng ngay trước. BẮT BUỘC ghi lý do — reviewer sẽ soi.
 */
import { execSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIG = JSON.parse(readFileSync(join(HERE, 'brand-lint.config.json'), 'utf8'));

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, v] = a.replace(/^--/, '').split('=');
    return [k, v ?? true];
  }),
);
const MODE = args.mode || 'diff';
const BASE = args.base || process.env.BRAND_LINT_BASE || 'origin/main';
const AS_JSON = Boolean(args.json);
const ROOT = resolve(args.root || process.cwd());

/* ------------------------- khớp glob đơn giản ------------------------- */
const DEEP = '\u0001';   // moc tam cho '**/' (khop 0..n cap thu muc)
const STAR = '\u0002';   // moc tam cho '**'  (khop bat ky, ke ca dau '/')

/**
 * Chuyen glob -> RegExp voi ngu nghia chuan:
 *   '** /'  khop 0 HOAC NHIEU cap thu muc  -> '** /tools/**' khop ca 'tools/x' o goc repo
 *   '**'    khop bat ky chuoi nao (ke ca '/')
 *   '*'     khop trong MOT cap (khong vuot '/')
 *   '?'     khop dung 1 ky tu
 */
function globToRegExp(glob) {
  const escaped = glob
    .replace(/\*\*\//g, DEEP)                  // '**/' truoc, de khong bi '**' nuot mat
    .replace(/\*\*/g, STAR)
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')      // escape ky tu regex (khong dung toi * ? da thay)
    .replace(/\*/g, '[^/]*')
    .replace(/\?/g, '.')
    .split(DEEP).join('(?:.*/)?')               // 0..n cap thu muc
    .split(STAR).join('.*');
  return new RegExp(`^${escaped}$`);
}
const ALLOW = CONFIG.allowlistPaths.map(globToRegExp);
const ALLOW_BY_RULE = Object.fromEntries(
  Object.entries(CONFIG.allowlistPathsByRule || {}).map(([k, v]) => [k, v.map(globToRegExp)]),
);

function isAllowed(file, ruleId) {
  const p = file.replace(/\\/g, '/');
  if (ALLOW.some((re) => re.test(p))) return true;
  const byRule = ALLOW_BY_RULE[ruleId];
  return Boolean(byRule && byRule.some((re) => re.test(p)));
}

/* ------------------------- thu thập dòng cần soi ------------------------- */
const TEXT_EXT = /\.(tsx?|jsx?|mjs|cjs|css|scss|html|json|md|py|ya?ml|sh)$/i;

function sh(cmd) {
  return execSync(cmd, { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

/** mode=diff: chỉ lấy dòng THÊM MỚI so với BASE — nợ cũ không chặn PR */
function collectDiffLines() {
  let raw;
  try {
    raw = sh(`git diff --unified=0 ${BASE}...HEAD -- .`);
  } catch {
    console.error(`[brand-lint] Không diff được với "${BASE}". Thử: git fetch origin`);
    process.exit(2);
  }
  const out = [];
  let file = null;
  let lineNo = 0;
  for (const line of raw.split('\n')) {
    if (line.startsWith('+++ b/')) { file = line.slice(6); continue; }
    const hunk = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) { lineNo = parseInt(hunk[1], 10); continue; }
    if (line.startsWith('+') && !line.startsWith('+++')) {
      if (file && TEXT_EXT.test(file)) out.push({ file, line: lineNo, text: line.slice(1) });
      lineNo += 1;
    }
  }
  return out;
}

/** mode=full/count: quét mọi file đang được git theo dõi */
function collectAllLines() {
  const files = sh('git ls-files').split('\n').filter((f) => f && TEXT_EXT.test(f));
  const out = [];
  for (const file of files) {
    const abs = join(ROOT, file);
    if (!existsSync(abs)) continue;
    let content;
    try { content = readFileSync(abs, 'utf8'); } catch { continue; }
    if (content.length > 2_000_000) continue;   // bỏ file khổng lồ (locales, bundle)
    content.split('\n').forEach((text, i) => out.push({ file, line: i + 1, text }));
  }
  return out;
}

/* ------------------------- chạy rule ------------------------- */
const rules = CONFIG.rules.map((r) => ({ ...r, re: new RegExp(r.pattern, r.flags || '') }));

/**
 * Đọc dòng ngay trước để tìm marker inline ignore.
 *
 * Ở mode=diff, chỉ mục chỉ chứa dòng THÊM MỚI — comment ignore đã có sẵn từ
 * trước sẽ không nằm trong diff và trở nên vô hình. Không xử lý thì dev viết
 * ignore kèm lý do, lần sau sửa dòng ngay dưới là CI đỏ oan. Nên khi chỉ mục
 * không có, đọc thẳng từ file trên đĩa.
 */
const fileLinesCache = new Map();
function prevLineFromDisk(file, lineNo) {
  if (lineNo < 2) return '';
  if (!fileLinesCache.has(file)) {
    const abs = join(ROOT, file);
    let lines = null;
    if (existsSync(abs)) {
      try { lines = readFileSync(abs, 'utf8').split('\n'); } catch { lines = null; }
    }
    fileLinesCache.set(file, lines);
  }
  const lines = fileLinesCache.get(file);
  return lines ? (lines[lineNo - 2] ?? '') : '';
}

function lint(entries) {
  const findings = [];
  // Dựng chỉ mục dòng-trước để hỗ trợ inline ignore
  const byFile = new Map();
  for (const e of entries) {
    if (!byFile.has(e.file)) byFile.set(e.file, new Map());
    byFile.get(e.file).set(e.line, e.text);
  }

  for (const e of entries) {
    const prev = byFile.get(e.file)?.get(e.line - 1) ?? prevLineFromDisk(e.file, e.line);
    for (const rule of rules) {
      if (isAllowed(e.file, rule.id)) continue;
      if (prev.includes(`${CONFIG.inlineIgnoreMarker} ${rule.id}`)) continue;
      const m = e.text.match(rule.re);
      if (m) {
        findings.push({
          rule: rule.id, severity: rule.severity, file: e.file, line: e.line,
          match: m[0], message: rule.message, snippet: e.text.trim().slice(0, 160),
        });
      }
    }
  }
  return findings;
}

/* ------------------------- xuất kết quả ------------------------- */
const entries = MODE === 'diff' ? collectDiffLines() : collectAllLines();
const findings = lint(entries);
const errors = findings.filter((f) => f.severity === 'error');
const warns = findings.filter((f) => f.severity === 'warn');

if (AS_JSON) {
  console.log(JSON.stringify({ mode: MODE, total: findings.length, errors: errors.length, warns: warns.length, findings }, null, 2));
} else if (MODE === 'count') {
  const byRule = {};
  for (const f of findings) byRule[f.rule] = (byRule[f.rule] || 0) + 1;
  const byFile = {};
  for (const f of findings) byFile[f.file] = (byFile[f.file] || 0) + 1;
  const top = Object.entries(byFile).sort((a, b) => b[1] - a[1]).slice(0, 15);

  console.log(`\n📊 NỢ HARDCODE THƯƠNG HIỆU — ${relative(process.cwd(), ROOT) || '.'}\n`);
  console.log(`   Tổng: ${findings.length}  (error: ${errors.length}, warn: ${warns.length})\n`);
  console.log('   Theo rule:');
  for (const [rule, n] of Object.entries(byRule).sort((a, b) => b[1] - a[1])) {
    console.log(`     ${String(n).padStart(5)}  ${rule}`);
  }
  console.log(`\n   15 file nặng nhất (tổng ${Object.keys(byFile).length} file dính):`);
  for (const [file, n] of top) console.log(`     ${String(n).padStart(5)}  ${file}`);
  console.log('');
} else {
  for (const f of findings) {
    const icon = f.severity === 'error' ? '❌' : '⚠️ ';
    console.log(`${icon} ${f.file}:${f.line}  [${f.rule}]  "${f.match}"`);
    console.log(`     ${f.message}`);
    console.log(`     → ${f.snippet}\n`);
  }
  if (!findings.length) console.log('✅ brand-lint: không phát hiện hardcode thương hiệu mới.\n');
  else console.log(`Tổng: ${errors.length} lỗi, ${warns.length} cảnh báo.\n`);
}

// Dùng process.exitCode, KHÔNG process.exit(): khi stdout là pipe hoặc file,
// process.exit() cắt cụt phần chưa flush — `--json > report.json` sẽ ra JSON hỏng.
// Đặt exitCode để Node tự thoát sau khi ghi xong.
process.exitCode = MODE === 'count' ? 0 : errors.length > 0 ? 1 : 0;
