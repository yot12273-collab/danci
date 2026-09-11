// ============ 英语词汇学习助手 · 前端逻辑 ============
// 单页应用：查词 / 生词本 / 历史 / 标签 / docx 导入
'use strict';

const $ = (id) => document.getElementById(id);

// ---------- 工具 ----------
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
function show(id) { $(id).classList.remove('hidden'); }
function hide(id) { $(id).classList.add('hidden'); }

let toastTimer;
function toast(msg, ok = true) {
  let el = $('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = 'toast ' + (ok ? 'ok' : 'err');
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1800);
}

// ---------- 登录态（token 存 localStorage，请求统一注入 Authorization） ----------
const TOKEN_KEY = 'vocab_token';
const USERNAME_KEY = 'vocab_username';

function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(token) { localStorage.setItem(TOKEN_KEY, token); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USERNAME_KEY); }

// 组装带鉴权的请求头；FormData 场景不设 Content-Type（由浏览器自动生成边界）
function authHeaders(extra = {}) {
  const h = { ...extra };
  if (getToken()) h['Authorization'] = 'Bearer ' + getToken();
  return h;
}

// ---------- 请求封装（统一响应信封 {code,message,data}） ----------
async function api(path, options = {}) {
  options.headers = authHeaders(options.headers);
  let res;
  try {
    res = await fetch(path, options);
  } catch (e) {
    // 网络层失败（服务未启动 / 断网等）
    throw new Error('无法连接服务器，请确认服务已启动');
  }
  // 登录态失效：清本地 token，回到登录门禁（覆盖层盖住应用，避免泄露已加载数据）
  if (res.status === 401) {
    clearToken();
    showLogin();
    throw new Error('请先登录');
  }
  let json;
  try {
    json = await res.json();
  } catch (e) {
    // 返回体不是 JSON（如网关 HTML、纯文本错误页）
    throw new Error(`服务器响应异常（HTTP ${res.status}）`);
  }
  if (json.code !== 0) {
    // 业务错误取 message；若后端返回 FastAPI 默认错误（如 404 的 detail），
    // 给出含 HTTP 状态码的提示，便于定位（如「接口不存在」多半是后端未重启）
    const msg = json.message
      || (json.detail ? `接口错误（HTTP ${res.status}）：${json.detail}` : `请求失败（HTTP ${res.status}）`);
    throw new Error(msg);
  }
  return json.data;
}

// ---------- 登录 / 登出 ----------
function showLogin() {
  // 关闭所有业务覆盖层，只留登录门禁；聚焦账号输入方便直接键入
  ['tagDetailPanel', 'quizPanel', 'recitePanel'].forEach(hide);
  $('loginError').classList.add('hidden');
  $('userBox').classList.add('hidden');
  show('loginPanel');
  $('loginUsername').focus();
}

async function tryLogin() {
  const username = $('loginUsername').value.trim();
  const password = $('loginPassword').value;
  if (!username || !password) {
    const el = $('loginError');
    el.textContent = '请输入账号和密码';
    el.classList.remove('hidden');
    return;
  }
  $('loginBtn').disabled = true;
  hide('loginError');
  try {
    // 登录接口本身无需 token，且账号错误返回 401（code 40102），
    // 用裸 fetch 以展示「账号或密码错误」而非被 api() 的 401 门禁逻辑吞掉
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const json = await res.json();
    if (json.code !== 0) throw new Error(json.message || '登录失败');
    setToken(json.data.token);
    localStorage.setItem(USERNAME_KEY, json.data.username);
    enterApp(json.data.username);
  } catch (e) {
    const el = $('loginError');
    el.textContent = e.message;
    el.classList.remove('hidden');
  } finally {
    $('loginBtn').disabled = false;
  }
}

// 登录成功：隐藏门禁、显示账号并进入生词本
function enterApp(username) {
  hide('loginPanel');
  $('userName').textContent = username;
  $('userBox').classList.remove('hidden');
  switchTab('words');
}

async function doLogout() {
  try {
    // 通知后端删除会话；即便失败也一律本地登出（幂等）
    await api('/api/auth/logout', { method: 'POST' });
  } catch (e) { /* 忽略：本地 token 照常清除 */ }
  clearToken();
  showLogin();
  toast('已退出登录');
}

$('loginBtn').addEventListener('click', tryLogin);
$('loginPassword').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') tryLogin();
});
$('logoutBtn').addEventListener('click', doLogout);

// ---------- 状态 ----------
let currentTagId = null;   // 生词本当前标签过滤（null=全部）
let lastAnalyze = null;    // 最近一次查词结果（供卡片/抽屉复用）
let currentDetailTagId = null;   // 标签详情当前标签
let currentDetailTagName = '';
let quizCards = [];              // 闪卡测试卡片序列
let quizIndex = 0;               // 当前题号
let quizMode = 'en2zh';          // 出题模式
let quizLocked = false;          // 当前题是否已判定（防重复作答）
let quizTimer = null;            // 答对自动跳题计时器
let quizAnswers = [];            // 中译英逐格答案（含提示字母预填）
let quizEditable = [];           // 中译英可编辑位索引（空白槽位）

// ---------- Tab 切换 ----------
document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach((b) =>
    b.classList.toggle('active', b.dataset.tab === tab));
  ['words', 'history', 'tags', 'import'].forEach((t) =>
    $(`tab-${t}`).classList.toggle('hidden', t !== tab));
  if (tab === 'words') { loadTags(); loadWords(); }
  if (tab === 'history') loadHistory();
  if (tab === 'tags') loadTags();
}

// ---------- 查词 ----------
$('searchBtn').addEventListener('click', () => search($('searchInput').value));
$('searchInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') search($('searchInput').value);
});

async function search(word) {
  word = (word || '').trim();
  if (!word) return;
  $('searchInput').value = word;
  hide('searchError');
  try {
    const data = await api('/api/words/analyze?word=' + encodeURIComponent(word));
    lastAnalyze = data;
    renderResultCard(data);
    if (data.is_saved) loadWords();
  } catch (e) {
    const el = $('searchError');
    el.textContent = e.message;
    show('searchError');
  }
}

function renderResultCard(d) {
  const el = $('searchResult');
  show('searchResult');
  el.innerHTML = `
    <div class="rc-inner fade-in">
      <div class="rc-head">
        <div>
          <span class="rc-word">${escapeHtml(d.base)}</span>
          <span class="rc-phonetic">${d.phonetic ? '/' + escapeHtml(d.phonetic) + '/' : ''}</span>
        </div>
        <button class="btn ghost small" data-action="detail">详情</button>
      </div>
      <div class="rc-highlight">💡 ${escapeHtml(d.highlight)}</div>
      <div class="rc-meaning">${escapeHtml(d.short_meaning || '') || '<span class="muted">暂无中文释义</span>'}</div>
      <div class="rc-actions">
        <button class="btn primary" data-action="save" ${d.is_saved ? 'disabled' : ''}>
          ${d.is_saved ? '✓ 已在生词本' : '＋ 加入生词本'}
        </button>
      </div>
    </div>`;
  el.dataset.word = d.base;
}

$('searchResult').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  if (btn.dataset.action === 'detail') openDrawer(lastAnalyze);
  if (btn.dataset.action === 'save') saveWord(lastAnalyze.base);
});

// ---------- 生词本 ----------
async function loadWords() {
  let url = '/api/words?page=1&page_size=200';
  if (currentTagId) url += '&tag_id=' + currentTagId;
  try {
    const data = await api(url);
    renderWords(data.items);
  } catch (e) { toast(e.message, false); }
}

function renderWords(items) {
  const list = $('wordList');
  $('wordEmpty').classList.toggle('hidden', items.length > 0);
  list.innerHTML = items.map((w) => `
    <li class="word-item" data-lemma="${escapeHtml(w.lemma)}">
      <div class="wi-main">
        <div class="wi-top">
          <span class="wi-word">${escapeHtml(w.lemma)}</span>
          ${w.phonetic ? `<span class="wi-phonetic">/${escapeHtml(w.phonetic)}/</span>` : ''}
        </div>
        <div class="wi-meaning">${escapeHtml(w.short_meaning || '—')}</div>
        ${w.tags.length ? `<div class="wi-tags">${w.tags.map(t => `<span class="mini-tag">${escapeHtml(t.name)}</span>`).join('')}</div>` : ''}
      </div>
      <button class="wi-del" data-action="delete" data-id="${w.id}" aria-label="删除">✕</button>
    </li>`).join('');
}

$('wordList').addEventListener('click', (e) => {
  const del = e.target.closest('[data-action="delete"]');
  if (del) { deleteWord(del.dataset.id); return; }
  const item = e.target.closest('.word-item');
  if (item) openDrawerForWord(item.dataset.lemma);
});

async function saveWord(word) {
  try {
    await api('/api/words', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word, tag_ids: currentTagId ? [currentTagId] : [] }),
    });
    toast('已加入生词本');
    lastAnalyze = { ...lastAnalyze, is_saved: true };
    renderResultCard(lastAnalyze);
    loadWords();
  } catch (e) { toast(e.message, false); }
}

async function deleteWord(id) {
  try {
    await api('/api/words/' + id, { method: 'DELETE' });
    toast('已删除');
    loadWords();
  } catch (e) { toast(e.message, false); }
}

// ---------- 标签 chips（生词本过滤） ----------
async function loadTags() {
  try {
    const tags = await api('/api/tags');
    renderTagChips(tags);
    renderTagList(tags);
  } catch (e) { /* 静默失败 */ }
}

function renderTagChips(tags) {
  const el = $('tagChips');
  const chips = [`<button class="chip ${currentTagId === null ? 'active' : ''}" data-tag="">全部</button>`];
  tags.forEach((t) => chips.push(
    `<button class="chip ${currentTagId === t.id ? 'active' : ''}" data-tag="${t.id}">${escapeHtml(t.name)}</button>`));
  el.innerHTML = chips.join('');
}

$('tagChips').addEventListener('click', (e) => {
  const btn = e.target.closest('.chip');
  if (!btn) return;
  currentTagId = btn.dataset.tag ? Number(btn.dataset.tag) : null;
  loadTags();
  loadWords();
});

// ---------- 标签管理 ----------
function renderTagList(tags) {
  const el = $('tagList');
  el.innerHTML = tags.map((t) => `
    <li class="tag-item" data-id="${t.id}" data-name="${escapeHtml(t.name)}">
      <span class="tag-dot" style="background:${t.color || '#3b82f6'}"></span>
      <span class="tag-name">${escapeHtml(t.name)}</span>
      <span class="tag-count">${t.word_count} 词</span>
      <button class="tag-edit" data-action="rename" data-id="${t.id}" data-name="${escapeHtml(t.name)}">改</button>
      <button class="tag-del" data-action="delete" data-id="${t.id}">✕</button>
    </li>`).join('') || '<div class="empty small">暂无标签</div>';
}

$('tagForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('tagName').value.trim();
  if (!name) return;
  try {
    await api('/api/tags', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    $('tagName').value = '';
    toast('标签已创建');
    loadTags();
  } catch (e) { toast(e.message, false); }
});

$('tagList').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (btn) {
    const id = Number(btn.dataset.id);
    if (btn.dataset.action === 'delete') {
      if (!confirm('删除该标签？（不会删除单词）')) return;
      try { await api('/api/tags/' + id, { method: 'DELETE' }); loadTags(); loadWords(); }
      catch (err) { toast(err.message, false); }
    } else if (btn.dataset.action === 'rename') {
      const name = prompt('新标签名', btn.dataset.name);
      if (!name || !name.trim()) return;
      try {
        await api('/api/tags/' + id, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name.trim() }),
        });
        loadTags();
      } catch (err) { toast(err.message, false); }
    }
    return;
  }
  // 点击标签主体 → 进入标签详情
  const item = e.target.closest('.tag-item');
  if (item) openTagDetail(Number(item.dataset.id), item.dataset.name);
});

// ---------- 历史 ----------
async function loadHistory() {
  try {
    const data = await api('/api/history?page=1&page_size=200');
    renderHistory(data.items);
  } catch (e) { toast(e.message, false); }
}

function renderHistory(items) {
  const list = $('historyList');
  $('historyEmpty').classList.toggle('hidden', items.length > 0);
  list.innerHTML = items.map((h) => `
    <li class="hist-item" data-query="${escapeHtml(h.query)}">
      <div class="hist-main">
        <span class="hist-word">${escapeHtml(h.query)}</span>
        ${h.lemma && h.lemma !== h.query ? `<span class="hist-lemma">→ ${escapeHtml(h.lemma)}</span>` : ''}
      </div>
      <button class="hist-del" data-action="delete" data-id="${h.id}" aria-label="删除">✕</button>
    </li>`).join('');
}

$('historyList').addEventListener('click', async (e) => {
  const del = e.target.closest('[data-action="delete"]');
  if (del) {
    try { await api('/api/history/' + del.dataset.id, { method: 'DELETE' }); loadHistory(); }
    catch (err) { toast(err.message, false); }
    return;
  }
  const item = e.target.closest('.hist-item');
  if (item) search(item.dataset.query);
});

$('clearHistory').addEventListener('click', async () => {
  if (!confirm('确定清空全部历史？')) return;
  try { await api('/api/history', { method: 'DELETE' }); loadHistory(); }
  catch (e) { toast(e.message, false); }
});

// ---------- 详情抽屉 ----------
function openDrawerForWord(word) {
  searchDrawer(word);
}

async function searchDrawer(word) {
  try {
    const data = await api('/api/words/analyze?word=' + encodeURIComponent(word));
    openDrawer(data);
  } catch (e) { toast(e.message, false); }
}

function openDrawer(d) {
  const content = $('drawerContent');
  content.innerHTML = buildWordDetailHtml(d);
  lastAnalyze = d;
  show('drawerMask');
  $('drawer').classList.add('open');
}

// 构建单词完整详情 HTML —— 搜索抽屉与背诵主体共用的唯一渲染函数。
// 返回与「单词搜索」详情完全一致的内容：高亮提示 / 中文释义 / 词形变化 / 形近词 / 外部链接。
// opts.readonly=true 时（背诵态）：隐藏收藏按钮、形近词退化为纯展示（不可点击跳转），避免打断背诵流程。
function buildWordDetailHtml(d, opts = {}) {
  const readonly = !!opts.readonly;

  const translations = (d.translations || []).map((t) => `
    <div class="trans-item">
      <span class="trans-pos">${escapeHtml(t.pos_label || t.pos)}</span>
      <span class="trans-meaning">${escapeHtml(t.meaning)}</span>
    </div>`).join('');

  const forms = renderDrawerForms(d);

  const similar = (d.similar || []).map((w) => readonly
    ? `<span class="chip similar-word">${escapeHtml(w)}</span>`
    : `<button class="chip similar-word" data-word="${escapeHtml(w)}">${escapeHtml(w)}</button>`).join('');

  const links = (d.links || []).map((l) =>
    `<a class="ext-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.name)}</a>`).join('');

  // 背诵态不渲染收藏按钮（这些词本就在生词本中）
  const saveBtn = readonly ? '' :
    `<button class="btn primary small" data-dw-action="save" ${d.is_saved ? 'disabled' : ''}>${d.is_saved ? '已收藏' : '＋ 收藏'}</button>`;

  return `
    <div class="drawer-title">
      <div>
        <div class="dw-word">${escapeHtml(d.base)} ${spkBtn(d.base)} <span class="dw-phonetic">${d.phonetic ? '/' + escapeHtml(d.phonetic) + '/' : ''}</span></div>
        <div class="dw-pos">${escapeHtml(d.pos_label || '')}</div>
      </div>
      ${saveBtn}
    </div>
    <div class="dw-highlight">💡 ${escapeHtml(d.highlight)}</div>

    <div class="dw-section">
      <h3>中文释义</h3>
      ${translations || '<div class="muted">暂无中文释义</div>'}
    </div>

    <div class="dw-section">
      <h3>词形变化</h3>
      ${forms || '<div class="muted">无可展示变化</div>'}
    </div>

    <div class="dw-section">
      <h3>形近词 / 易混淆</h3>
      <div class="chip-row">${similar || '<span class="muted">无</span>'}</div>
    </div>

    <div class="dw-section">
      <h3>外部搜索</h3>
      <div class="ext-row">${links}</div>
    </div>`;
}

function renderDrawerForms(d) {
  const forms = d.forms || [];
  if (!forms.length) return '';
  const groups = {};
  forms.forEach((f) => (groups[f.upos_label] = groups[f.upos_label] || []).push(f));
  let html = '';
  for (const [pos, items] of Object.entries(groups)) {
    html += `<div class="form-group">${escapeHtml(pos)}</div><div class="form-table">`;
    items.forEach((f) => {
      const active = f.value === d.input;
      html += `<div class="form-row ${active ? 'active' : ''}"><span>${escapeHtml(f.label)}</span><b>${escapeHtml(f.value)}</b></div>`;
    });
    html += '</div>';
  }
  return html;
}

$('drawerContent').addEventListener('click', (e) => {
  if (e.target.closest('[data-dw-action="save"]')) { saveWord(lastAnalyze.base); return; }
  const sim = e.target.closest('.similar-word');
  if (sim) { closeDrawer(); search(sim.dataset.word); }
});

function closeDrawer() {
  hide('drawerMask');
  $('drawer').classList.remove('open');
}
$('drawerMask').addEventListener('click', closeDrawer);

// ---------- docx 导入 ----------
$('docxFile').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  $('uploadLabel').textContent = '已选择：' + file.name;
  const form = new FormData();
  form.append('file', file);
  const progress = $('importProgress');
  show('importProgress');
  progress.innerHTML = '<div class="muted">上传并解析中…</div>';
  try {
    const res = await fetch('/api/import/docx', { method: 'POST', headers: authHeaders(), body: form });
    const json = await res.json();
    if (json.code !== 0) throw new Error(json.message);
    pollJob(json.data.job_id);
  } catch (err) {
    progress.innerHTML = `<div class="err">导入失败：${escapeHtml(err.message)}</div>`;
    resetUpload();
  }
});

function resetUpload() {
  $('docxFile').value = '';
  $('uploadLabel').textContent = '选择 .docx 文件';
}

async function pollJob(jobId) {
  const progress = $('importProgress');
  try {
    const job = await api('/api/import/' + jobId);
    const p = job.progress || {};
    if (job.status === 'done') {
      progress.innerHTML = `<div class="ok">✓ 导入完成：提取 ${p.scanned} 词，有效 ${p.valid}，新增 ${p.inserted}，重复 ${p.duplicates}，跳过 ${p.skipped}，标签「${escapeHtml(p.tag_name || '')}」</div>`;
      resetUpload();
      loadTags(); loadWords();
      toast('导入完成');
      return;
    }
    if (job.status === 'error') {
      progress.innerHTML = `<div class="err">导入失败：${escapeHtml(job.error || '未知错误')}</div>`;
      return;
    }
    progress.innerHTML = `<div class="muted">${job.status === 'queued' ? '排队中' : '处理中'}：已提取 ${p.scanned ?? 0} 词，有效 ${p.valid ?? 0} …</div>`;
    setTimeout(() => pollJob(jobId), 1000);
  } catch (e) {
    progress.innerHTML = `<div class="err">查询进度失败：${escapeHtml(e.message)}</div>`;
  }
}

// ---------- 标签详情（点击即查） ----------
async function openTagDetail(tagId, tagName) {
  currentDetailTagId = tagId;
  currentDetailTagName = tagName;
  $('tagDetailTitle').textContent = tagName;
  show('tagDetailPanel');
  await loadTagWords(tagId);
}

async function loadTagWords(tagId) {
  try {
    const words = await api('/api/tags/' + tagId + '/words');
    renderTagWords(words);
  } catch (e) { toast(e.message, false); }
}

function renderTagWords(words) {
  const list = $('tagWordList');
  $('tagWordEmpty').classList.toggle('hidden', words.length > 0);
  list.innerHTML = words.map((w) => `
    <li class="tag-word-item" data-lemma="${escapeHtml(w.lemma)}">
      <div class="twi-main">
        <span class="twi-word">${escapeHtml(w.lemma)}</span>
        ${spkBtn(w.lemma)}
        ${w.primary_pos ? `<span class="twi-pos">${escapeHtml(w.primary_pos)}</span>` : ''}
      </div>
      <span class="twi-meaning">${escapeHtml(w.short_meaning || '—')}</span>
    </li>`).join('');
}

$('tagWordList').addEventListener('click', (e) => {
  const item = e.target.closest('.tag-word-item');
  if (item) openDrawerForWord(item.dataset.lemma);
});

// ---------- 闪卡测试 ----------
$('startQuizBtn').addEventListener('click', openQuizSetup);
$('startReciteBtn').addEventListener('click', () => openRecite(currentDetailTagId, currentDetailTagName));

function openQuizSetup() {
  quizCards = []; quizIndex = 0;
  setQuizMode('en2zh');
  $('quizTitle').textContent = '测试 · ' + currentDetailTagName;
  $('quizTarget').value = '';
  show('quizSetup'); hide('quizRun'); hide('quizDone');
  show('quizPanel');
}

document.querySelectorAll('.mode-btn').forEach((btn) => {
  btn.addEventListener('click', () => setQuizMode(btn.dataset.mode));
});

function setQuizMode(mode) {
  quizMode = mode;
  document.querySelectorAll('.mode-btn').forEach((b) =>
    b.classList.toggle('active', b.dataset.mode === mode));
}

$('quizGoBtn').addEventListener('click', startQuiz);

async function startQuiz() {
  const raw = $('quizTarget').value.trim();
  const target = raw === '' ? null : Number(raw);
  if (target !== null && (!Number.isInteger(target) || target < 1)) {
    toast('题目数量无效', false); return;
  }
  try {
    const data = await api('/api/quiz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag_id: currentDetailTagId, target, mode: quizMode }),
    });
    quizCards = data.cards;
    quizIndex = 0;
    hide('quizSetup'); hide('quizDone'); show('quizRun');
    renderQuizCard();
  } catch (e) { toast(e.message, false); }
}

function renderQuizCard() {
  const card = quizCards[quizIndex];
  quizLocked = false;
  clearTimeout(quizTimer);
  hideFeedback();
  $('quizProgress').textContent = `${quizIndex + 1} / ${quizCards.length}`;
  const el = $('quizCard');
  if (card.direction === 'zh2en') renderSpellingCard(el, card);
  else renderChoiceCard(el, card);
}

// ---------- 中译英：拼写填空（单隐藏 input 映射多方块，规避焦点跳跃） ----------
function renderSpellingCard(el, card) {
  const slots = card.slots || [];
  // 可编辑位 = 空白槽位；提示字母 / 连字符锁定显示
  const editable = [];
  slots.forEach((s, i) => { if (s === '') editable.push(i); });
  quizEditable = editable;
  quizAnswers = slots.slice();  // 提示字母预填，可编辑位暂空

  el.innerHTML = `
    <div class="spell-meaning">${escapeHtml(card.short_meaning || '（无释义）')}</div>
    <div class="spell-grid">
      ${slots.map((s, i) => `
        <span class="spell-cell${s ? ' locked' : ''}" data-i="${i}">${escapeHtml(s)}</span>
      `).join('')}
      <input id="spellInput" class="spell-hidden-input" type="text"
             maxlength="${editable.length}" autocomplete="off"
             autocapitalize="off" autocorrect="off" spellcheck="false">
    </div>`;

  if (editable.length === 0) {
    // 全提示（极短单词）：无需输入，直接判对跳题
    quizLocked = true;
    toast('✓ 正确');
    quizTimer = setTimeout(nextCard, 600);
    return;
  }
  // 尝试聚焦拉起键盘（移动端若被拒绝，点方块仍可拉起）
  el.querySelector('#spellInput').focus();
}

function validateSpelling(card) {
  quizLocked = true;
  const lemma = card.lemma.toLowerCase();
  const cells = $('quizCard').querySelectorAll('.spell-cell');
  let allRight = true;
  for (const i of quizEditable) {
    if ((quizAnswers[i] || '').toLowerCase() !== lemma[i]) {
      allRight = false;
      cells[i].classList.add('err');  // 错误字母标红
    }
  }
  if (allRight) {
    toast('✓ 正确');
    quizTimer = setTimeout(nextCard, 600);
  } else {
    showFeedback(`正确答案：<b class="green">${escapeHtml(card.lemma)}</b> ${spkBtn(card.lemma)}`);
  }
}

// ---------- 英译中：单项选择 ----------
function renderChoiceCard(el, card) {
  const options = card.options || [];
  el.innerHTML = `
    <div class="choice-word">${escapeHtml(card.lemma)} ${spkBtn(card.lemma)}</div>
    ${card.phonetic ? `<div class="choice-phonetic">/${escapeHtml(card.phonetic)}/</div>` : ''}
    <div class="choice-options">
      ${options.map((opt, i) => `
        <button class="choice-opt" data-i="${i}">${escapeHtml(opt)}</button>
      `).join('')}
    </div>`;
}

// ---------- 事件委托：隐藏 input 统一接收键盘 + 选项点击 ----------
$('quizCard').addEventListener('input', (e) => {
  const input = e.target.closest('#spellInput');
  if (!input || quizLocked) return;
  let val = input.value.toLowerCase().replace(/[^a-z'-]/g, '');
  if (val !== input.value) input.value = val;   // 过滤非法字符
  const cells = $('quizCard').querySelectorAll('.spell-cell');
  quizEditable.forEach((i, j) => {
    const ch = j < val.length ? val[j] : '';
    quizAnswers[i] = ch;
    cells[i].textContent = ch;                   // 按序映射到空白方块
  });
  if (val.length === quizEditable.length) validateSpelling(quizCards[quizIndex]);
});

$('quizCard').addEventListener('click', (e) => {
  const opt = e.target.closest('.choice-opt');
  if (!opt || quizLocked) return;
  const card = quizCards[quizIndex];
  const i = Number(opt.dataset.i);
  quizLocked = true;
  if (i === card.answer_index) {
    opt.classList.add('ok');
    toast('✓ 正确');
    quizTimer = setTimeout(nextCard, 600);
  } else {
    opt.classList.add('err');
    const correct = $('quizCard').querySelector(`.choice-opt[data-i="${card.answer_index}"]`);
    if (correct) correct.classList.add('ok');
    showFeedback(`正确答案：<b class="green">${escapeHtml(card.options[card.answer_index])}</b>`);
  }
});

// ---------- 反馈 / 继续 / 下一题 ----------
function showFeedback(html) {
  const fb = $('quizFeedback');
  fb.innerHTML = `${html}<button id="quizContinueBtn" class="btn primary">继续</button>`;
  fb.classList.remove('hidden');
}

function hideFeedback() {
  const fb = $('quizFeedback');
  fb.classList.add('hidden');
  fb.innerHTML = '';
}

$('quizFeedback').addEventListener('click', (e) => {
  if (e.target.closest('#quizContinueBtn')) nextCard();
});

function nextCard() {
  clearTimeout(quizTimer);
  hideFeedback();
  quizIndex++;
  if (quizIndex >= quizCards.length) { finishQuiz(); return; }
  renderQuizCard();
}

function finishQuiz() {
  hide('quizRun'); show('quizDone');
  $('quizDoneText').textContent = `抽查完成！共 ${quizCards.length} 题`;
}

$('quizRestartBtn').addEventListener('click', startQuiz);

$('quizBackBtn').addEventListener('click', () => hide('quizPanel'));

// ---------- 返回按钮 ----------
document.querySelectorAll('.back-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const back = btn.dataset.back;
    if (back === 'tags') { hide('tagDetailPanel'); switchTab('tags'); }
    else if (back === 'quiz') { hide('quizPanel'); }
    else if (back === 'recite') { hide('recitePanel'); stopCountdown(); }
  });
});

// ---------- 语音朗读（有道 TTS，面向大陆学习者） ----------
let voiceType = 2;  // 2=美音(默认)，1=英音

// 小喇叭按钮（内联 SVG，data-word 存单词，点击仅发音不冒泡）
function spkBtn(word) {
  return `<button class="spk-btn" type="button" data-word="${escapeHtml(word)}" aria-label="朗读 ${escapeHtml(word)}">
    <svg class="spk-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05A4.5 4.5 0 0 0 16.5 12zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
    </svg>
  </button>`;
}

function speakWord(word) {
  if (!word) return;
  // 有道词典公开发音接口：type=1 英音 / type=2 美音
  const audio = new Audio(`https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=${voiceType}`);
  audio.play().catch(() => {});  // iOS 用户点击触发 play 允许；catch 防未处理 rejection
}

// 捕获阶段全局委托：点小喇叭只发音，阻止冒泡到「打开详情 / 选项」等父级事件
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.spk-btn');
  if (!btn) return;
  e.stopPropagation();
  speakWord(btn.dataset.word);
}, true);

// 发音音色切换（测试设置页）
document.querySelectorAll('.voice-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    voiceType = Number(btn.dataset.voice);
    document.querySelectorAll('.voice-btn').forEach((b) =>
      b.classList.toggle('active', Number(b.dataset.voice) === voiceType));
  });
});

// ============ 自动计时背诵（切片式自由选份） ============
// 三态切换：制定态（无计划）/ 列表态（分组按钮）/ 运行态（计时轮播）。
// 分组结构由后端快照持久化（重启后同标签仍见同一套切片）；前端只读「任意份」，
// 计时轮播仅在前端内存维护，绝不维护完成进度、绝不弹窗、绝不自动跳转。

// 「小步快跑」分批拉取参数：单批固定 10 词（约 4s 返回），缓冲 ≤ 3 词时静默补拉
const RECITE_BATCH_SIZE = 10;
const RECITE_WATERMARK = 3;

let currentPlanType = 'count';   // 当前选择的方案类型：count 按数量 / ratio 按比例
let recitePlanData = null;       // 当前计划摘要（含 chunks 分组，来自 GET /api/recite/plan?tag_id=）
let currentReciteTagId = null;   // 当前背诵所属标签 id
let currentReciteTagName = '';   // 当前背诵所属标签名
let reciteWords = [];            // 已加载的单词队列（完整详情，随批次静默增长）
let reciteIndex = 0;             // 当前展示下标（队列内）
let reciteChunkIndex = 1;        // 当前份序号（1 起）
let reciteChunkTotal = 0;        // 本份实际总词数（后端返回，用于尾词判定与进度显示）
let reciteFetchDone = false;     // 是否已拉完本份全部批次
let reciteStarted = false;       // 首批是否已渲染并启动倒计时
let isFetching = false;          // 拉取防抖锁（严禁并发请求）
let reciteShuffleSeed = 0;       // 切片内打乱种子（0=不打乱；非 0 时后端按此确定性洗牌）
let reciteIntervalSec = 5;       // 倒计时总秒数（来自计划 interval_seconds）
let reciteRemain = 5;            // 剩余秒数
let reciteTimer = null;          // setInterval 句柄
let reciteRunning = false;       // 计时是否在运行（false = 暂停）

// ---- 背诵 / 测验 双模式状态机（同容器 class 切换，无页面跳转） ----
const MODE_RECITE = 'RECITE';
const MODE_TEST = 'TEST';
let appMode = MODE_RECITE;        // 当前模式：RECITE 背诵 / TEST 测验
let currentGroupViewed = [];      // 本份已展示（背诵过）的词，作测验候选池；测验后清空 → 已测词不重复
let gTestCards = [];              // 组测验卡片序列（与全局 quizCards 完全隔离）
let gTestIndex = 0;               // 组测验当前题号
let gTestLocked = false;          // 当前题是否已判定

// 打开指定标签的背诵面板：记录当前标签 → 拉取计划 → 渲染列表态或制定态
async function openRecite(tagId, tagName) {
  currentReciteTagId = tagId;
  currentReciteTagName = tagName;
  $('reciteTitle').textContent = '背诵 · ' + tagName;
  show('recitePanel');
  stopCountdown();               // 关闭可能残留的计时器
  try {
    const plan = await api('/api/recite/plan?tag_id=' + tagId);
    recitePlanData = plan;
    if (plan) renderReciteList();
    else showReciteSetup();
  } catch (e) { toast(e.message, false); }
}

// 列表态：展示分组结构（「第 N 份 (X词)」按钮）+ 底部常驻「结束 / 重新制定」
function renderReciteList() {
  const plan = recitePlanData;
  hide('reciteRun'); hide('reciteSetup');
  show('reciteList');
  const shuffleNote = plan.shuffle_chunk ? ' · 切片内打乱' : '';
  // 背诵序列摘要：展示自定义播放顺序（如 1 2 1 2 3）与当前进行位置，便于用户把握进度
  const seq = (plan.sequence_list && plan.sequence_list.length) ? plan.sequence_list.join(' ') : '';
  const cur = (plan.sequence_list && plan.sequence_list.length)
    ? plan.sequence_list[((plan.current_sequence_index || 0) % plan.sequence_list.length)]
    : '';
  const seqNote = seq
    ? `<div class="rs-seq">序列：${escapeHtml(seq)}（下次进入第 ${cur} 份）</div>`
    : '';
  $('reciteSummary').innerHTML = `
    <div class="rs-title">${escapeHtml(currentReciteTagName)} · 共 ${plan.total_words} 词</div>
    <div class="rs-sub">分 ${plan.total_chunks} 份 · 每份约 ${plan.chunk_size} 词 · 轮播 ${plan.interval_seconds} 秒${shuffleNote}</div>${seqNote}`;
  $('reciteChunkList').innerHTML = plan.chunks.map((c) => `
    <li>
      <button class="chunk-btn" data-index="${c.index}">
        第 ${c.index} 份 <span class="chunk-count">(${c.word_count}词)</span>
      </button>
    </li>`).join('');
}

// 点击任意份按钮 → 开始该份背诵（事件委托，分组按钮动态渲染）
$('reciteChunkList').addEventListener('click', (e) => {
  const btn = e.target.closest('.chunk-btn');
  if (!btn) return;
  startReciteChunk(Number(btn.dataset.index));
});

// 同步方案类型按钮高亮与输入框文案（切换类型 / 回显编辑态共用）
function syncReciteMode() {
  document.querySelectorAll('.mode-btn[data-plan]').forEach((b) =>
    b.classList.toggle('active', b.dataset.plan === currentPlanType));
  const isCount = currentPlanType === 'count';
  $('reciteParamLabel').textContent = isCount ? '单次背诵数量（单词数）' : '单次背诵比例（%）';
  $('reciteParam').placeholder = isCount ? '例如 100' : '例如 10';
}

// 方案类型切换：按数量 / 按比例
document.querySelectorAll('.mode-btn[data-plan]').forEach((btn) => {
  btn.addEventListener('click', () => {
    currentPlanType = btn.dataset.plan;
    syncReciteMode();
  });
});

// 进入参数配置界面：编辑态回显上次的数量/比例与时间；新建态用默认值。
// 由「重新制定计划」或「无计划时打开背诵」触发。
function showReciteSetup() {
  hide('reciteList'); hide('reciteRun');
  show('reciteSetup');
  const plan = recitePlanData;
  if (plan) {
    // 编辑态：回显本地记录（内容参数 + 行为参数），方便用户看清要改哪个参数
    currentPlanType = plan.plan_type;
    $('reciteParam').value = plan.param == null ? '' : String(plan.param);
    $('reciteInterval').value = plan.interval_seconds;
    $('reciteShuffle').checked = !!plan.shuffle_chunk;
    // 按钮显隐开关回显：默认显示（字段缺失或 true 均视为显示）
    $('reciteShowNext').checked = plan.show_next_button !== false;
    // 背诵序列回显：把数组转回空格分隔串（如 "1 2 1 2 3"）；留空保持空（保存时降级默认顺序）
    $('reciteSequence').value = (plan.sequence_list && plan.sequence_list.length)
      ? plan.sequence_list.join(' ') : '';
    $('reciteCreateBtn').textContent = '确认保存';
  } else {
    // 新建态：默认按数量、5 秒轮播、不打乱、显示按钮、默认序列
    currentPlanType = 'count';
    $('reciteParam').value = '';
    $('reciteInterval').value = '5';
    $('reciteShuffle').checked = false;
    $('reciteShowNext').checked = true;
    $('reciteSequence').value = '';
    $('reciteCreateBtn').textContent = '创建背诵计划';
  }
  syncReciteMode();
}

// 提交参数：后端智能判定「局部更新 / 彻底重置 / 新建」，前端据此给出确认与提示
$('reciteCreateBtn').addEventListener('click', createRecitePlan);
async function createRecitePlan() {
  const paramRaw = $('reciteParam').value.trim();
  const param = Number(paramRaw);
  const interval = Number($('reciteInterval').value.trim()) || 5;
  const shuffle = $('reciteShuffle').checked;
  const showNext = $('reciteShowNext').checked;   // 背诵期间是否显示「下一个」按钮（行为参数）
  const sequence = $('reciteSequence').value.trim();   // 背诵序列原始文本（留空 → 后端降级默认顺序）
  if (!paramRaw || !(param > 0)) { toast('请输入有效的数量或比例', false); return; }
  if (currentPlanType === 'ratio' && param > 100) { toast('比例需在 0~100（%）之间', false); return; }

  // 情况 B 前端预判：仅「内容参数（方案类型 / 数量比例）」与本地记录不一致才弹确认；
  // 「行为参数（间隔 / 打乱开关 / 按钮显隐 / 背诵序列）」变化则静默保存（后端做局部更新）。
  const old = recitePlanData;
  if (old && (old.plan_type !== currentPlanType || Number(old.param) !== param)) {
    if (!confirm('修改数量/比例将重置当前背诵进度，是否继续？')) return;
  }

  try {
    const data = await api('/api/recite/plan?tag_id=' + currentReciteTagId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_type: currentPlanType, param, interval_seconds: interval, shuffle_chunk: shuffle, sequence, show_next_button: showNext }),
    });
    recitePlanData = data;
    // 依据后端 action 区分提示（A=静默更新行为参数 / B=重新制定 / 新建）
    if (data.action === 'updated') toast('已更新背诵设置');
    else if (data.action === 'reset') toast('已重新制定计划');
    else toast('背诵计划已创建');
    renderReciteList();
  } catch (e) { toast(e.message, false); }
}

// 结束本次背诵：单纯退出背诵模式（返回标签详情），保留当前计划分组
$('reciteExitBtn').addEventListener('click', () => {
  stopCountdown();
  hide('recitePanel');
});

// 重新制定计划：退回参数配置界面（自动回显上次参数），由用户确认要改哪个参数后再智能保存
$('reciteRebuildBtn').addEventListener('click', () => showReciteSetup());

// 开始某一份背诵：重置本份加载态，先拉首批 10 词进入运行态，后续批次按水位线静默补齐
async function startReciteChunk(index) {
  hide('reciteSetup'); hide('reciteList');
  show('reciteRun');
  stopCountdown();
  // 重置本份全部加载态，避免残留上一份的队列/锁/种子
  reciteChunkIndex = index;
  reciteWords = [];
  reciteIndex = 0;
  reciteChunkTotal = 0;
  reciteFetchDone = false;
  reciteStarted = false;
  isFetching = false;
  // 重置背诵/测验状态机，避免残留上一份的测验态与候选池
  appMode = MODE_RECITE;
  currentGroupViewed = [];
  gTestCards = []; gTestIndex = 0; gTestLocked = false;
  // 切片内打乱：每次进入本份生成新随机种子，后端据此确定性洗牌（同一次进入内各批顺序一致）
  reciteShuffleSeed = (recitePlanData && recitePlanData.shuffle_chunk)
    ? Math.floor(Math.random() * 2147483646) + 1
    : 0;
  $('reciteProgress').textContent = '正在准备第 ' + index + ' 份…';
  $('reciteCountdown').textContent = '…';
  $('reciteBody').innerHTML = '<div class="muted" style="padding:40px 0;text-align:center;">正在加载本份单词，请稍候…</div>';

  await fetchReciteBatch();
}

// 静默拉取下一批（固定 10 词）：isFetching 防抖锁保证绝不并发；新批次推入队列尾，
// 不打断当前播放。首批到位后渲染第一张卡片并启动倒计时，后续批次仅静默入队。
async function fetchReciteBatch() {
  if (isFetching || reciteFetchDone) return;
  isFetching = true;
  const offset = reciteWords.length;   // 已加载词数即下一批的起始下标
  try {
    const data = await api(
      '/api/recite/chunk?tag_id=' + currentReciteTagId + '&index=' + reciteChunkIndex +
      '&offset=' + offset + '&limit=' + RECITE_BATCH_SIZE + '&seed=' + reciteShuffleSeed
    );
    reciteChunkTotal = data.chunk_total || 0;
    reciteIntervalSec = data.interval_seconds || 5;
    reciteWords = reciteWords.concat(data.words || []);
    if (reciteChunkTotal > 0 && reciteWords.length >= reciteChunkTotal) reciteFetchDone = true;

    // 首批到位：渲染第一张卡片并启动倒计时（仅在未启动过时执行一次）
    if (!reciteStarted) {
      reciteStarted = true;
      if (!reciteWords.length) { toast('本份暂无单词', false); return; }
      renderReciteCard();
      startCountdown();
      maybeFetchRecite();
    }
  } catch (e) {
    toast(e.message, false);
    $('reciteBody').innerHTML = `<div class="muted" style="padding:40px 0;text-align:center;">${escapeHtml(e.message)}</div>`;
  } finally {
    isFetching = false;
  }
}

// 水位线触发：已加载但未展示的缓冲 ≤ 3 词时，静默补拉下一批，保证播放连贯。
// 仅在有后续批次且无进行中请求时触发（isFetching 锁由 fetchReciteBatch 内部再次校验）。
function maybeFetchRecite() {
  if (reciteFetchDone || isFetching) return;
  if (reciteWords.length - reciteIndex <= RECITE_WATERMARK) fetchReciteBatch();
}

// 渲染当前单词：从内存缓存 reciteWords 取出完整详情并复用「单词搜索」UI（零网络）
function renderReciteCard() {
  const d = reciteWords[reciteIndex];
  currentGroupViewed.push(d);   // 每词展示即入组（测验候选池）；测验后清空实现「已测词不重复」
  $('reciteProgress').textContent = `第 ${reciteChunkIndex} 份 · 本份 ${reciteIndex + 1} / ${reciteChunkTotal}`;
  $('reciteBody').innerHTML = buildWordDetailHtml(d, { readonly: true });
  syncAdvanceButton();      // 依据当前下标同步推进按钮文字（下一个 ↔ 进入下一份）
  resetCountdown();         // 复位倒计时数字显示
  // 尾词（本份最后一个词，按总词数判定，与已加载进度无关）：立即清除定时器、停止自动跳转，
  // 界面无限期停留在尾词上，把进入下一份的控制权交还用户手动点击「进入下一份」按钮。
  if (reciteIndex >= reciteChunkTotal - 1) {
    stopCountdown();
  }
}

// ---------- 倒计时控制 ----------
function resetCountdown() {
  reciteRemain = reciteIntervalSec;
  $('reciteCountdown').textContent = reciteRemain;
}
function startCountdown() {
  // 尾词不启动自动轮播：最后一个单词由用户手动点击「进入下一份」接管，绝不自动跳转。
  // 防御性守卫：fetchReciteBatch 在 renderReciteCard 之后无条件调用本函数，
  // 单份仅 1 词时 renderReciteCard 已停止定时器，此处再次拦截以防被误重启。
  if (reciteChunkTotal > 0 && reciteIndex >= reciteChunkTotal - 1) {
    stopCountdown();
    return;
  }
  reciteRunning = true;
  $('recitePauseBtn').textContent = '暂停';
  clearInterval(reciteTimer);
  reciteTimer = setInterval(reciteTick, 1000);
}
function stopCountdown() {
  clearInterval(reciteTimer);
  reciteTimer = null;
  reciteRunning = false;
}
function reciteTick() {
  reciteRemain -= 1;
  if (reciteRemain <= 0) {
    reciteNext();                // 倒计时结束 → 切到下一词（尾词时定时器已被强制清除，绝不会走到这里）
  } else {
    $('reciteCountdown').textContent = reciteRemain;
  }
}

// 暂停 / 继续
$('recitePauseBtn').addEventListener('click', () => {
  if (reciteRunning) {
    reciteRunning = false;
    clearInterval(reciteTimer);
    $('recitePauseBtn').textContent = '继续';
  } else {
    startCountdown();
  }
});

// 手动推进（单键）：点击与定时器倒计时结束都走 reciteNext
$('reciteNextBtn').addEventListener('click', reciteNext);

// 防误触：运行面板背景区双击快进（当「下一个」按钮被隐藏时，仍提供替代推进手势）。
// 事件委托到整个运行面板；回调内严格判定安全区，命中即 return 拦截，绝不误触。
$('reciteRun').addEventListener('dblclick', (e) => {
  // 严禁触发区：单词本身 + 发音小喇叭的整行容器。
  // .dw-word 是 buildWordDetailHtml 中承载「单词 + 小喇叭 + 音标」的那一行，
  // 用户双击此处多为连点喇叭发音，必须直接拦截，不做快进。
  if (e.target.closest('.dw-word')) return;
  // 交互控件区：任何按钮 / 外链（暂停、返回列表、推进按钮、外部搜索链接）不响应双击快进，
  // 避免与单击动作（暂停切换、返回、跳转）叠加造成误触。
  if (e.target.closest('button, a')) return;
  // 尾词不响应双击快进：进入下一份的唯一触发途径是手动点击「进入下一份」按钮。
  if (reciteChunkTotal > 0 && reciteIndex >= reciteChunkTotal - 1) return;
  // 其余大面积空白处 → 快进到下一词。
  reciteNext();
});

// 返回列表（放弃本份 / 手动回到分组列表）
$('reciteBackListBtn').addEventListener('click', () => {
  stopCountdown();
  renderReciteList();
});

// 动态推进按钮：依据「当前单词是否尾词」+「显示开关」联合决定显隐与文字。
// - 尾词：无论开关状态，强制显示并切换为「进入下一份」（尾词绝对覆盖）；
// - 非尾词：开关开启显示「下一个」，关闭则彻底隐藏（改由双击空白区快进）。
function syncAdvanceButton() {
  const btn = $('reciteNextBtn');
  const isTail = reciteChunkTotal > 0 && reciteIndex >= reciteChunkTotal - 1;
  if (isTail) {
    // 尾词态：强制显示，语义切换为「进入下一份」
    btn.textContent = '进入下一份';
    btn.classList.remove('hidden');
    return;
  }
  // 常规态：依据「显示下一个按钮」开关决定显示/隐藏
  const showNext = recitePlanData ? recitePlanData.show_next_button !== false : true;
  btn.textContent = '下一个';
  btn.classList.toggle('hidden', !showNext);
}

// 单键推进：按钮点击 / 非尾词时的双击快进 / 非尾词计时结束都走这里。
// 非尾词 → 内存切到下一词；尾词 → 等同点击【进入下一份】触发循环序列。
// 注意：尾词时定时器已被强制清除、双击也被拦截，因此尾词只能由「进入下一份」按钮触发本函数。
function reciteNext() {
  if (appMode !== MODE_RECITE) return;   // 测验中忽略背诵推进（run 面板已隐藏，防御性兜底）
  if (!reciteWords.length) return;   // 首批尚未加载完成时忽略推进（防止加载中双击/连点误触）
  // 越界守卫：下一词尚未入队且本份未拉完 → 静默补拉并保持当前卡片（不推进、不重置计时）。
  // 正常阅读速度下水位线已提前拉取，几乎不会走到；极端高频连点跳过时以此兜底，绝不越界取到 undefined。
  if (reciteIndex + 1 >= reciteWords.length && !reciteFetchDone) {
    fetchReciteBatch();
    return;
  }
  clearInterval(reciteTimer); reciteTimer = null;
  if (reciteIndex >= reciteChunkTotal - 1) {
    goNextChunk();              // 尾词 → 进入下一份（仅由手动点击「进入下一份」触发，无强制终点）
    return;
  }
  reciteIndex += 1;
  renderReciteCard();
  maybeFetchRecite();           // 推进后检查水位线，必要时静默补拉下一批，保证连贯
  if (reciteRunning) startCountdown();
}

// 进入下一份：按「背诵序列」无限循环路由（后端取模前进指针），加载下一份并立即开始倒计时
async function goNextChunk() {
  try {
    // 后端执行 (current_sequence_index + 1) % len，返回下一个切片序号与更新后的指针
    const adv = await api('/api/recite/advance?tag_id=' + currentReciteTagId, { method: 'POST' });
    // 同步本地序列指针镜像（供列表摘要展示「下次进入第 N 份」）
    if (recitePlanData) {
      recitePlanData.current_sequence_index = adv.current_sequence_index;
      recitePlanData.sequence_list = adv.sequence_list;
    }
    // 无缝衔接：直接加载下一份并立即进入计时轮播；startReciteChunk 内仍会严格判断切片内是否打乱
    await startReciteChunk(adv.chunk_index);
  } catch (e) { toast(e.message, false); }
}

// ============ 组测验（英译中 · 本份内干扰 · 与背诵同容器切换） ============
// 「测验本份」手动触发：测「本份已背、有释义、未测过」的词；本份内其它词释义作干扰项。
// 测验结束清空 currentGroupViewed（即「已测词不重复」），无缝切回背诵、恢复当前词计时，
// 绝不刷新页面、绝不丢 pendingQueue 预加载数据。

// Fisher-Yates 洗牌（返回新数组）：本地出题打乱选项 / 干扰项用
function shuffleArray(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// 剥离词性前缀（如 "n. 苹果" → "苹果"），用于干扰项语义去重（与后端 _meaning_body 同义）
function _meaningBody(m) {
  const s = (m || '');
  const i = s.indexOf(' ');
  return i === -1 ? s : s.slice(i + 1);
}

// 本地出题：词已在内存（reciteWords）里，零网络、零加载态；干扰项取自本份已加载词
function buildGroupTestCards(candidates) {
  const pool = reciteWords.filter((w) => w.short_meaning);
  return candidates.map((w) => {
    const correct = w.short_meaning;
    const seen = new Set([_meaningBody(correct)]);
    const distractors = [];
    const shuffled = shuffleArray(pool.filter((x) => x.base !== w.base));
    for (const x of shuffled) {
      if (distractors.length >= 3) break;
      const b = _meaningBody(x.short_meaning);
      if (seen.has(b)) continue;
      seen.add(b);
      distractors.push(x.short_meaning);
    }
    const options = shuffleArray([correct, ...distractors]);
    return {
      lemma: w.base, phonetic: w.phonetic, short_meaning: correct,
      options, answer_index: options.indexOf(correct),
    };
  });
}

// 进入测验：暂停计时、切 TEST 态、同容器 class 切换显隐
function startGroupTest() {
  if (appMode === MODE_TEST) return;
  const candidates = currentGroupViewed.filter((w) => w.short_meaning);   // 无释义词无法出英译中，跳过
  if (!candidates.length) { toast('本份暂无可测验的词', false); return; }
  gTestCards = buildGroupTestCards(candidates);
  if (!gTestCards.length) { toast('本份暂无可测验的词', false); return; }
  gTestIndex = 0;
  gTestLocked = false;
  appMode = MODE_TEST;
  stopCountdown();                 // 暂停轮播计时
  hide('reciteRun');
  show('reciteTest');
  renderGroupTestCard();
}

function renderGroupTestCard() {
  const card = gTestCards[gTestIndex];
  gTestLocked = false;
  $('reciteTestProgress').textContent = `测验 ${gTestIndex + 1} / ${gTestCards.length}`;
  $('reciteTestFeedback').classList.add('hidden');
  $('reciteTestCard').innerHTML = `
    <div class="choice-word">${escapeHtml(card.lemma)} ${spkBtn(card.lemma)}</div>
    ${card.phonetic ? `<div class="choice-phonetic">/${escapeHtml(card.phonetic)}/</div>` : ''}
    <div class="choice-options">
      ${card.options.map((o, i) => `<button class="choice-opt" data-i="${i}">${escapeHtml(o)}</button>`).join('')}
    </div>`;
}

// 测验结束：清空本组（已测词不重复）→ 切回背诵 → 恢复当前词计时，无缝继续
function resumeAfterTest() {
  currentGroupViewed = [];         // 关键：清空候选池，已测词不再重复出现
  appMode = MODE_RECITE;
  gTestCards = []; gTestIndex = 0; gTestLocked = false;
  hide('reciteTest');
  show('reciteRun');
  // 无缝恢复：当前词（reciteIndex）仍在队列里，直接重开其倒计时；不刷新、不丢预加载
  resetCountdown();
  startCountdown();
}

function nextGroupTestCard() {
  gTestIndex += 1;
  if (gTestIndex >= gTestCards.length) { resumeAfterTest(); return; }
  renderGroupTestCard();
}

// 手动触发「测验本份」
$('reciteTestNowBtn').addEventListener('click', () => {
  if (appMode === MODE_TEST) return;
  if (!currentGroupViewed.length) { toast('本份暂无可测验的词', false); return; }
  startGroupTest();
});

// 组测验答题（事件委托，独立状态；答对自动跳题，答错显示反馈 + 继续）
$('reciteTestCard').addEventListener('click', (e) => {
  const opt = e.target.closest('.choice-opt');
  if (!opt || gTestLocked) return;
  gTestLocked = true;
  const card = gTestCards[gTestIndex];
  if (Number(opt.dataset.i) === card.answer_index) {
    opt.classList.add('ok');
    setTimeout(nextGroupTestCard, 450);
  } else {
    opt.classList.add('err');
    const correct = $('reciteTestCard').querySelector(`.choice-opt[data-i="${card.answer_index}"]`);
    if (correct) correct.classList.add('ok');
    $('reciteTestFeedback').innerHTML =
      `正确答案：<b class="green">${escapeHtml(card.options[card.answer_index])}</b>` +
      `<button id="gTestNextBtn" class="btn primary">继续</button>`;
    $('reciteTestFeedback').classList.remove('hidden');
  }
});

$('reciteTestFeedback').addEventListener('click', (e) => {
  if (e.target.closest('#gTestNextBtn')) nextGroupTestCard();
});

// ---------- 启动 ----------
// 门禁：无 token 直接进登录；有 token 先校验 /api/auth/me（失效时 api() 自动清 token 并弹登录层）
async function bootstrap() {
  if (!getToken()) { showLogin(); return; }
  try {
    const user = await api('/api/auth/me');
    enterApp(user.username);
  } catch (e) {
    // token 校验失败：api() 已清 token 并 showLogin；此处兜底网络错误等异常
    if (getToken()) showLogin();
  }
}
bootstrap();
