'use strict';
/**
 * 组测验（背诵 × 英译中）逻辑自检 —— 直接抽取 static/app.js 的真实函数体在 vm 中运行，
 * 不复制实现，保证测的是线上代码本身。
 *
 * 覆盖红线用例：
 *   1. 中途点、本份未拉完 → 先补拉整份再出题（含「在途请求」不空转）
 *   2. 测「本份全部词」而非「已背词」
 *   3. 出题顺序随机
 *   4. 选项完整性（4 项 / 去重 / 含正确答案 / answer_index 指向正确）
 *   5. 答题推进 → 无缝恢复背诵（不丢预加载队列）
 *   6. 拉取无进展 → 止损不死循环
 *   7. 空本份 → 回退背诵态并原样恢复计时
 *   8. 防重入（准备中重复点击不重复开测）
 *
 * 用法：node .ai-skills/test_group_quiz.js   （退出码 0 = 全通过）
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP_PATH = path.join(__dirname, '..', 'static', 'app.js');
const source = fs.readFileSync(APP_PATH, 'utf8');

// ============ 源码抽取：状态感知扫描（跳过字符串 / 模板 / 注释） ============
function skipString(s, i) {
  const quote = s[i];
  i += 1;
  while (i < s.length) {
    const c = s[i];
    if (c === '\\') { i += 2; continue; }
    if (quote === '`' && c === '$' && s[i + 1] === '{') {
      const end = matchBrace(s, i + 1);            // 跳过 ${ ... } 插值
      i = end < 0 ? s.length : end + 1;
      continue;
    }
    if (c === quote) return i + 1;
    i += 1;
  }
  return i;
}

function matchBrace(s, open) {
  let depth = 0;
  let i = open;
  while (i < s.length) {
    const c = s[i];
    const n = s[i + 1];
    if (c === '/' && n === '/') { const nl = s.indexOf('\n', i); if (nl < 0) return -1; i = nl; continue; }
    if (c === '/' && n === '*') { const e = s.indexOf('*/', i + 2); if (e < 0) return -1; i = e + 2; continue; }
    if (c === "'" || c === '"' || c === '`') { i = skipString(s, i); continue; }
    if (c === '{') depth += 1;
    else if (c === '}') { depth -= 1; if (depth === 0) return i; }
    i += 1;
  }
  return -1;
}

function extractFunc(s, name) {
  const re = new RegExp('(?:^|\\n)((?:async\\s+)?function\\s+' + name + '\\s*\\([^)]*\\))');
  const m = re.exec(s);
  if (!m) throw new Error('extractFunc: not found -> ' + name);
  const bodyStart = s.indexOf('{', m.index + m[0].length - 1);
  if (bodyStart < 0) throw new Error('extractFunc: no body -> ' + name);
  const bodyEnd = matchBrace(s, bodyStart);
  if (bodyEnd < 0) throw new Error('extractFunc: unbalanced -> ' + name);
  const head = m.index + (m[0][0] === '\n' ? 1 : 0);
  return s.slice(head, bodyEnd + 1);
}

const FUNCS = [
  'shuffleArray', '_meaningBody', 'buildGroupTestCards', 'collectTestCandidates',
  'ensureReciteFull', 'startGroupTest', 'resumeAfterTest', 'nextGroupTestCard',
  'renderGroupTestCard',
];
const extracted = FUNCS.map((n) => extractFunc(source, n)).join('\n\n');

// ============ 夹具 ============
// 干净夹具：45 个词均含释义，词根唯一
function cleanFixture() {
  const all = [];
  for (let i = 1; i <= 45; i += 1) {
    all.push({ base: 'w' + i, phonetic: 'f' + i, short_meaning: 'n. meaning' + i });
  }
  return all;
}

// 边界夹具：40 有释义 + 3 无释义 + 1 组同词根重复 = 41 张卡（45 条记录）
function edgeFixture() {
  const all = [];
  for (let i = 1; i <= 40; i += 1) {
    all.push({ base: 'e' + i, phonetic: '', short_meaning: 'n. em' + i });
  }
  all.push({ base: 'n1', short_meaning: '' });
  all.push({ base: 'n2', short_meaning: '' });
  all.push({ base: 'n3', short_meaning: '' });
  all.push({ base: 'dup', short_meaning: 'n. firstdup' });
  all.push({ base: 'dup', short_meaning: 'n. seconddup' });
  return all;
}

// ============ 运行沙箱 ============
function build(opts) {
  const o = opts || {};
  const els = new Map();
  const ctx = {
    console,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    MODE_RECITE: 'RECITE',
    MODE_TEST: 'TEST',
    // 对应 app.js 顶层可变状态
    reciteWords: (o.words || []).slice(),
    reciteIndex: o.reciteIndex || 0,
    reciteChunkIndex: 1,
    reciteChunkTotal: o.total || 0,
    reciteFetchDone: o.done === true,
    reciteStarted: false,
    isFetching: o.isFetching === true,
    reciteShuffleSeed: 0,
    reciteIntervalSec: 5,
    reciteRemain: 5,
    reciteTimer: null,
    reciteRunning: o.running === true,
    appMode: 'RECITE',
    gTestCards: [],
    gTestIndex: 0,
    gTestLocked: false,
    currentReciteTagId: 1,
    // 探针
    toasts: [], shows: [], hides: [],
    startCount: 0, stopCount: 0, fetchCalls: 0,
  };

  ctx.$ = (id) => {
    if (!els.has(id)) {
      const node = {
        id, disabled: false, textContent: '', innerHTML: '',
        cls: new Set(),
        classList: {
          add: (c) => node.cls.add(c),
          remove: (c) => node.cls.delete(c),
          toggle: () => {},
          contains: (c) => node.cls.has(c),
        },
        querySelector: () => null,
        addEventListener: () => {},
      };
      els.set(id, node);
    }
    return els.get(id);
  };
  ctx.el = els;

  ctx.escapeHtml = (v) => (v == null ? '' : String(v));
  ctx.spkBtn = () => '';
  ctx.toast = (m) => ctx.toasts.push(m);
  ctx.show = (id) => ctx.shows.push(id);
  ctx.hide = (id) => ctx.hides.push(id);
  ctx.resetCountdown = () => { ctx.reciteRemain = ctx.reciteIntervalSec; };
  ctx.startCountdown = () => { ctx.startCount++; ctx.reciteRunning = true; };
  ctx.stopCountdown = () => { ctx.stopCount++; ctx.reciteRunning = false; };
  ctx.sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // 模拟后端：mode = ok | fail（异常无进展）| stall（空本份不置 done）
  const backend = { all: o.all || [], total: (o.all || []).length, batchSize: 10, mode: o.mode || 'ok', delayMs: o.delayMs == null ? 3 : o.delayMs };
  ctx.backend = backend;
  ctx.fetchReciteBatch = async function () {
    if (ctx.isFetching || ctx.reciteFetchDone) return;
    ctx.isFetching = true;
    ctx.fetchCalls += 1;
    try {
      await ctx.sleep(backend.delayMs);
      if (backend.mode === 'fail' || backend.mode === 'stall') return;
      const offset = ctx.reciteWords.length;
      ctx.reciteWords = ctx.reciteWords.concat(backend.all.slice(offset, offset + backend.batchSize));
      if (backend.total > 0) ctx.reciteChunkTotal = backend.total;
      if (ctx.reciteWords.length >= backend.total) ctx.reciteFetchDone = true;
      // 与真实 fetchReciteBatch 一致：首批到位即启动倒计时（供「补拉期间重启计时」用例）
      if (!ctx.reciteStarted && ctx.reciteWords.length) { ctx.reciteStarted = true; ctx.startCountdown(); }
    } finally {
      ctx.isFetching = false;
    }
  };

  vm.createContext(ctx);
  vm.runInContext(extracted, ctx, { filename: 'app.js:extracted' });
  ctx.fn = (name) => vm.runInContext(name, ctx);
  return ctx;
}

function checkCardIntegrity(cards) {
  const problems = [];
  for (const c of cards) {
    if (!Array.isArray(c.options) || c.options.length !== 4) {
      problems.push(c.lemma + ' options=' + (c.options ? c.options.length : 'none'));
      continue;
    }
    if (new Set(c.options).size !== c.options.length) problems.push(c.lemma + ' duplicate options');
    if (!c.options.includes(c.short_meaning)) problems.push(c.lemma + ' missing correct option');
    if (c.options[c.answer_index] !== c.short_meaning) problems.push(c.lemma + ' answer_index mismatch');
  }
  return problems;
}

let pass = 0;
let fail = 0;
function ok(cond, label, extra) {
  if (cond) { pass += 1; console.log('  PASS  ' + label); }
  else { fail += 1; console.log('  FAIL  ' + label + (extra != null ? '  -> ' + extra : '')); }
}

(async function main() {
  // ---- 用 1：中途点、本份未拉完 → 含「在途请求」也要补拉整份 ----
  console.log('[1] mid-chunk click: wait in-flight then backfill whole chunk');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all.slice(0, 20), total: 45, done: false, reciteIndex: 7, running: true });
    // 模拟水位线已发出的在途请求：3ms 后把词补到 30 并释放锁
    ctx.isFetching = true;
    const inFlight = (async () => {
      await ctx.sleep(3);
      ctx.reciteWords = ctx.reciteWords.concat(all.slice(20, 30));
      ctx.reciteChunkTotal = 45;
      ctx.isFetching = false;
    })();
    await Promise.all([inFlight, ctx.fn('startGroupTest')()]);
    ok(ctx.reciteFetchDone === true, 'chunk fully fetched');
    ok(ctx.reciteWords.length === 45, 'queue holds all 45 words', ctx.reciteWords.length);
    ok(ctx.appMode === 'TEST', 'mode switched to TEST', ctx.appMode);
    ok(ctx.gTestCards.length === 45, 'all 45 words become cards', ctx.gTestCards.length);
    ok(ctx.reciteRunning === false, 'recite timer stopped', ctx.reciteRunning);
    ok(checkCardIntegrity(ctx.gTestCards).length === 0, 'card options integrity', JSON.stringify(checkCardIntegrity(ctx.gTestCards)));
    ok(ctx.shows.filter((s) => s === 'reciteTest').length === 1, 'test panel shown once');
  }

  // ---- 用 2：测「本份全部词」而非「已背词」 ----
  console.log('[2] candidate pool = whole chunk, not recited-so-far');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all, total: 45, done: true, reciteIndex: 7 });
    await ctx.fn('startGroupTest')();
    ok(ctx.gTestCards.length === 45, '45 cards though only 8 words viewed', ctx.gTestCards.length);
  }

  // ---- 用 3：出题顺序随机 ----
  console.log('[3] card order is randomized');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all, total: 45, done: true });
    const orders = new Set();
    for (let i = 0; i < 5; i += 1) {
      await ctx.fn('startGroupTest')();
      orders.add(ctx.gTestCards.map((c) => c.lemma).join(','));
      ctx.fn('resumeAfterTest')();
    }
    ok(orders.size > 1, 'distinct orders across runs', orders.size);
  }

  // ---- 用 4：答题推进 → 无缝恢复（预加载队列不丢） ----
  console.log('[4] answer through -> seamless resume, queue preserved');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all, total: 45, done: true, reciteIndex: 12, running: true });
    await ctx.fn('startGroupTest')();
    const cardsAtStart = ctx.gTestCards.length;
    let guard = 0;
    while (ctx.appMode === 'TEST' && guard < 200) { ctx.fn('nextGroupTestCard')(); guard += 1; }
    ok(ctx.appMode === 'RECITE', 'back to RECITE', ctx.appMode);
    ok(ctx.gTestCards.length === 0, 'test state cleared', ctx.gTestCards.length);
    ok(ctx.shows.includes('reciteRun'), 'recite panel restored');
    ok(ctx.reciteWords.length === 45, 'queue intact after test', ctx.reciteWords.length);
    ok(ctx.reciteRunning === true, 'countdown resumed', ctx.reciteRunning);
    ok(guard === cardsAtStart, 'advanced exactly card count', guard + '/' + cardsAtStart);
  }

  // ---- 用 5：补拉无进展 → 立即止损（不空转、不挂死） ----
  // 注：本用例模拟「补拉失败但已有部分词」——真实 fetchReciteBatch 的 catch 会 toast 网络错误，
  // 此处只校验控制流：必须迅速返回，并以已加载的词优雅降级出题。
  console.log('[5] no-progress fetch returns promptly (no hang)');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all.slice(0, 20), total: 45, done: false, mode: 'fail', running: true });
    const res = await Promise.race([
      ctx.fn('startGroupTest')().then(() => 'DONE'),
      ctx.sleep(2000).then(() => 'TIMEOUT'),
    ]);
    ok(res === 'DONE', 'returned instead of hanging', res);
    ok(ctx.isFetching === false, 'fetch lock released', ctx.isFetching);
    ok(ctx.appMode === 'TEST', 'degrades to available words', ctx.appMode);
    ok(ctx.gTestCards.length === 20, 'quiz built from loaded subset', ctx.gTestCards.length);
  }

  // ---- 用 6：空本份 → 回退 + 原样恢复计时 ----
  console.log('[6] empty chunk reverts and restores play state');
  {
    const ctx = build({ all: [], words: [], total: 0, done: false, mode: 'stall', running: true });
    await ctx.fn('startGroupTest')();
    ok(ctx.appMode === 'RECITE', 'reverted to RECITE', ctx.appMode);
    ok(ctx.gTestCards.length === 0, 'no cards built', ctx.gTestCards.length);
    ok(ctx.reciteRunning === true, 'was-running countdown restored', ctx.reciteRunning);
    ok(ctx.toasts.includes('本份暂无可测验的词'), 'empty-chunk toast shown');
  }

  // ---- 用 7：防重入 ----
  console.log('[7] re-entry during preparation is ignored');
  {
    const all = cleanFixture();
    const ctx = build({ all, words: all, total: 45, done: true, delayMs: 5 });
    const p1 = ctx.fn('startGroupTest')();
    const p2 = ctx.fn('startGroupTest')();
    await Promise.all([p1, p2]);
    ok(ctx.shows.filter((s) => s === 'reciteTest').length === 1, 'test opened exactly once');
    ok(ctx.gTestCards.length === 45, 'single card set', ctx.gTestCards.length);
  }

  // ---- 用 8：边界夹具（无释义剔除 + 同词根去重） ----
  console.log('[8] edge fixture: drop meaning-less, dedupe same base');
  {
    const all = edgeFixture();
    const ctx = build({ all, words: all, total: 45, done: true });
    await ctx.fn('startGroupTest')();
    ok(ctx.gTestCards.length === 41, '41 cards from 45 records', ctx.gTestCards.length);
    const lemmas = new Set(ctx.gTestCards.map((c) => c.lemma));
    ok(lemmas.size === ctx.gTestCards.length, 'no duplicate lemma', lemmas.size);
    ok(!lemmas.has('n1') && !lemmas.has('n2') && !lemmas.has('n3'), 'meaning-less words excluded');
    ok(checkCardIntegrity(ctx.gTestCards).length === 0, 'edge cards integrity', JSON.stringify(checkCardIntegrity(ctx.gTestCards)));
  }

  console.log('\nRESULT: ' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail === 0 ? 0 : 1);
})().catch((e) => { console.error('HARNESS ERROR:', e); process.exit(2); });
