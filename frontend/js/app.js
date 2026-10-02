// 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
/* 矿地智预 - 前端应用（Vue3 零构建） */
/* 作者水印：控制台可见（打开开发者工具即可看到） */
const APP_AUTHOR = 'by zhuoer mengzhuoda 9.20';
console.log('%c矿地智预 MineGeoAI-Pre%c ' + APP_AUTHOR,
  'background:#059669;color:#fff;padding:2px 8px;border-radius:4px 0 0 4px;font-weight:700',
  'background:#18181b;color:#a7f3d0;padding:2px 8px;border-radius:0 4px 4px 0');
const { createApp, ref, reactive, computed, nextTick, watch, onMounted, onUnmounted } = Vue;

/* ================= 通用工具 ================= */
const TOKEN_KEY = "kdzy_token", DS_KEY = "kdzy_dataset";
let onUnauthorized = null;   // 由根组件注册：401 时切回登录页

async function api(path, body) {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers["Authorization"] = "Bearer " + token;
  const ds = localStorage.getItem(DS_KEY);
  if (ds) headers["X-Dataset"] = ds;
  const opt = body !== undefined
    ? { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { headers };
  const res = await fetch("/api" + path, opt);
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    if (onUnauthorized) onUnauthorized();
    throw new Error("登录已过期，请重新登录");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || `请求失败 (${res.status})`);
    err.status = res.status;        // 供调用方区分冲突(409)、编码(400/code)等情形
    err.data = data;
    throw err;
  }
  return data;
}
const fmt = (n, d = 1) => (n === null || n === undefined || isNaN(n)) ? "-" : Number(n).toLocaleString("zh-CN", { maximumFractionDigits: d });

/* 文件上传（multipart） */
async function apiUpload(path, formData) {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch("/api" + path, { method: "POST", headers, body: formData });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    if (onUnauthorized) onUnauthorized();
    throw new Error("登录已过期，请重新登录");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "上传失败");
  return data;
}

/* 图片、文本等非 JSON 资源请求（复用 Token 与数据集头，返回原始 Response） */
async function apiFetch(path) {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers["Authorization"] = "Bearer " + token;
  const ds = localStorage.getItem(DS_KEY);
  if (ds) headers["X-Dataset"] = ds;
  const res = await fetch("/api" + path, { headers });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    if (onUnauthorized) onUnauthorized();
    throw new Error("登录已过期，请重新登录");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `请求失败 (${res.status})`);
  }
  return res;
}

/* 用户偏好云同步（服务端持久化，登录任意设备自动恢复） */
function pushPref(key, value) {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return;
  fetch("/api/user/prefs", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ key, value }),
  }).catch(() => {});
}

/* 用户头像：存 localStorage 并随账号云同步（data URL，128×128 方形裁切） */
const userAvatar = ref(localStorage.getItem("kdzy_avatar") || "");
/* 站内消息：未读数（Dock 角标）与面板开关 */
const msgUnread = ref(0);
const msgOpen = ref(false);
function setUserAvatar(dataUrl) {
  userAvatar.value = dataUrl || "";
  if (dataUrl) localStorage.setItem("kdzy_avatar", dataUrl);
  else localStorage.removeItem("kdzy_avatar");
  pushPref("avatar", dataUrl || "");
}
/* 选图 → 居中方形裁切 → 128×128 PNG data URL（不新开接口，也不要额外的文件管理） */
function pickAvatarFile(file, done) {
  if (!file) return;
  if (!/^image\//.test(file.type)) { toast("请选择图片文件", "err"); return; }
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    const S = 128, cv = document.createElement("canvas");
    cv.width = cv.height = S;
    const ctx = cv.getContext("2d");
    const side = Math.min(img.width, img.height);
    ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, S, S);
    URL.revokeObjectURL(url);
    setUserAvatar(cv.toDataURL("image/png"));
    if (done) done();
  };
  img.onerror = () => { URL.revokeObjectURL(url); toast("图片读取失败", "err"); };
  img.src = url;
}

/* 跨应用传参：文件管理里对栅格影像点「去检测」时暂存目标文件 */
const detectTarget = ref(null);

/* 读取本地存储里的 JSON 值：键值可能被外部写坏（如 "[object Object]"），
   解析失败时清掉该键并回退默认值——绝不让一处坏数据把整个应用卡死在登录页 */
function lsJSON(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch (e) {
    console.warn("[kdzy] 本地存储 " + key + " 内容损坏，已重置");
    localStorage.removeItem(key);
    return fallback;
  }
}

const toasts = reactive([]);
function toast(msg, type = "ok") {
  const id = Date.now() + Math.random();
  toasts.push({ id, msg, type });
  setTimeout(() => toasts.splice(toasts.findIndex(t => t.id === id), 1), 4200);
}

/* ============ 线性图标系统（替代 emoji） ============ */
const _svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const ICONS = {
  home: _svg('<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  database: _svg('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>'),
  funnel: _svg('<path d="M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z"/>'),
  crosshair: _svg('<circle cx="12" cy="12" r="10"/><line x1="22" x2="18" y1="12" y2="12"/><line x1="6" x2="2" y1="12" y2="12"/><line x1="12" x2="12" y1="6" y2="2"/><line x1="12" x2="12" y1="22" y2="18"/>'),
  trend: _svg('<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m19 9-5 5-4-4-3 3"/>'),
  compass: _svg('<circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/>'),
  report: _svg('<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
  user: _svg('<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  logout: _svg('<path d="m16 17 5-5-5-5"/><path d="M21 12H9"/><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'),
  play: _svg('<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>'),
  download: _svg('<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>'),
  check: _svg('<path d="M20 6 9 17l-5-5"/>'),
  globe: _svg('<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>'),
  gear: _svg('<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>'),
  sliders: _svg('<path d="M10 5H3"/><path d="M12 19H3"/><path d="M14 3v4"/><path d="M16 17v4"/><path d="M21 12h-9"/><path d="M21 19h-5"/><path d="M21 5h-7"/><path d="M8 10v4"/><path d="M8 12H3"/>'),
  activity: _svg('<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'),
  image: _svg('<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>'),
  folder: _svg('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
  upload: _svg('<path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'),
  grid: _svg('<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>'),
  winmin: _svg('<path d="M5 12h14"/>'),
  winmax: _svg('<rect width="18" height="18" x="3" y="3" rx="2"/>'),
  winrestore: _svg('<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'),
  winclose: _svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
  search: _svg('<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>'),
  chevron: _svg('<path d="m6 9 6 6 6-6"/>'),
  help: _svg('<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'),
  bolt: _svg('<path d="M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z"/>'),
  shield: _svg('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>'),
  scale: _svg('<path d="M12 3v18"/><path d="m19 8 3 8a5 5 0 0 1-6 0zV7"/><path d="M3 7h1a17 17 0 0 0 8-2 17 17 0 0 0 8 2h1"/><path d="m5 8 3 8a5 5 0 0 1-6 0zV7"/><path d="M7 21h10"/>'),
  layers: _svg('<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>'),
};

/* 当前图标风格（响应式，切换后无需刷新即可换图标） */
const iconStyle = ref(localStorage.getItem("kdzy_icons") || "tech");

const IcComp = {
  props: ["n"],
  computed: { svg() { return ICONS[this.n] || ""; } },
  template: '<span class="ic" v-html="svg"></span>',
};

const CLASS_COLORS = { "耕地": "#d9a821", "林地": "#3e7c42", "建设用地": "#8457a8", "采矿用地": "#c9452e", "水域": "#3568b0", "未利用地": "#c19a6b" };

/* 切换主题会整页重载（图表调色板在脚本加载时就定死了）：重载前把桌面上的窗口记到
   sessionStorage，重载后原样恢复，避免用户切一次主题就丢掉所有已打开的窗口 */
const REOPEN_KEY = "kdzy_reopen";
function rememberOpen() {
  const list = [...document.querySelectorAll(".win[data-appid]")]
    .map(el => ({ id: el.dataset.appid, max: el.classList.contains("maximized"),
                  z: parseInt(getComputedStyle(el).zIndex, 10) || 0 }))
    .sort((a, b) => a.z - b.z);
  if (list.length) sessionStorage.setItem(REOPEN_KEY, JSON.stringify(list));
}

/* 主题化图表调色板 */
const THEME_ID = localStorage.getItem("kdzy_theme") || "saas";   // 默认主题：SaaS 风格
const PALETTES = {
  atlas: {
    text: "#5f6b62", title: "#2c3830",
    tipBg: "rgba(255,255,252,.97)", tipBorder: "#d5cebc", tipText: "#33453a",
    split: "rgba(90,105,92,.16)", font: "Times New Roman, Microsoft YaHei", titleFont: "SimHei, Microsoft YaHei",
    heatA: ["#f0eee2", "#7fae94", "#1e4634"], heatB: ["#f0eee2", "#a9bd7e", "#2f6b4f"],
    heatLabel: "#33453a", heatLabelBorder: "#fff",
    pos: "#3d7a52", neg: "#b3473f", warn: "#b98a1e",
  },
  console: {
    text: "#8ba2bd", title: "#d7ecff",
    tipBg: "rgba(6,14,26,.94)", tipBorder: "rgba(34,211,238,.4)", tipText: "#d7e6f5",
    split: "rgba(56,189,248,.12)", font: "Consolas, Microsoft YaHei", titleFont: "Microsoft YaHei",
    heatA: ["#081426", "#0e7490", "#67e8f9"], heatB: ["#081426", "#15803d", "#bef264"],
    heatLabel: "#eaf6ff", heatLabelBorder: "#04121f",
    pos: "#34d399", neg: "#fb7185", warn: "#fbbf24",
  },
  saas: {
    text: "#6b7280", title: "#111827",
    tipBg: "rgba(251,253,249,.98)", tipBorder: "#dde8d8", tipText: "#17251b",
    text: "#5b6b5d", title: "#17251b",
    split: "rgba(23,37,27,.10)", font: "Microsoft YaHei", titleFont: "Microsoft YaHei",
    heatA: ["#eef2ff", "#818cf8", "#312e81"], heatB: ["#eef2ff", "#6ee7b7", "#065f46"],
    heatLabel: "#1f2937", heatLabelBorder: "#fff",
    pos: "#059669", neg: "#dc2626", warn: "#d97706",
  },
  ubuntu: {
    text: "#5e5c5b", title: "#2c2c2c",
    tipBg: "rgba(255, 255, 253, .97)", tipBorder: "#e3e0de", tipText: "#2c2c2c",
    split: "rgba(44, 44, 44, .10)", font: "Ubuntu, Microsoft YaHei", titleFont: "Ubuntu, Microsoft YaHei",
    heatA: ["#f7f6f5", "#f0a58a", "#e95420"], heatB: ["#f7f6f5", "#b58fbf", "#772953"],
    heatLabel: "#2c2c2c", heatLabelBorder: "#ffffff",
    pos: "#0e8420", neg: "#c7162b", warn: "#f5b32a",
  },
};
const PAL = PALETTES[THEME_ID] || PALETTES.atlas;
const CHART_TEXT = { color: PAL.text, fontSize: 11.5, fontFamily: PAL.font };

function baseChart(title) {
  return {
    title: title ? { text: title, left: "center", textStyle: { color: PAL.title, fontSize: 13.5, fontWeight: 600, fontFamily: PAL.titleFont } } : undefined,
    backgroundColor: "transparent",
    textStyle: CHART_TEXT,
    tooltip: { trigger: "axis", backgroundColor: PAL.tipBg, borderColor: PAL.tipBorder, textStyle: { color: PAL.tipText, fontSize: 12, fontFamily: PAL.font } },
    legend: { bottom: 0, textStyle: CHART_TEXT, itemWidth: 14, itemHeight: 9 },
    grid: { left: 62, right: 26, top: title ? 42 : 30, bottom: 44 },
  };
}

/* 简易 ECharts 生命周期管理 */
/* 数字滚动：把 0 缓动到目标值（首页指标卡用）。
   目标值可能在挂载后才随 /api/meta 到达，所以暴露 set() 供 watch 再次触发。 */
function useCountUp(ms = 900) {
  const val = ref(0);
  let raf = 0, timer = 0, start = 0, from = 0, to = 0, done = false;
  const ease = t => 1 - Math.pow(1 - t, 3);          // easeOutCubic
  function step(ts) {
    if (done) return;
    if (!start) start = ts;
    const t = Math.min(1, (ts - start) / ms);
    val.value = from + (to - from) * ease(t);
    if (t < 1) raf = requestAnimationFrame(step);
  }
  function finish() { done = true; val.value = to; }
  function set(target) {
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    done = false;
    from = val.value;
    to = Number(target) || 0;
    start = 0;
    // 尊重"减少动态效果"偏好：直接给终值
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish(); return;
    }
    // 后台/被节流的标签页里 requestAnimationFrame 可能一直不回调，
    // 只靠 rAF 会让数字停在 0——所以再挂一个定时器兜底到终值。
    timer = setTimeout(finish, ms + 150);
    raf = requestAnimationFrame(step);
  }
  return { val, set, stop: () => { cancelAnimationFrame(raf); clearTimeout(timer); done = true; } };
}

function useChart(getEl) {
  let inst = null;
  return {
    render(option) {
      nextTick(() => {
        const el = getEl();
        if (!el) return;
        if (!inst) inst = echarts.init(el);
        inst.setOption(option, true);
        inst.resize();
      });
    },
    /* 增量更新：只改局部（如年份标记线），不重放整张图的入场动画 */
    merge(option) {
      if (!inst) return;
      inst.setOption(option);
    },
    dispose() { if (inst) { inst.dispose(); inst = null; } },
  };
}

/* ================= 登录页 ================= */
const LoginView = {
  setup() {
    const username = ref(""), password = ref(""), loading = ref(false), err = ref("");
    // 演示导航页预填：入口链接带 ?u=账号&p=密码 时自动填充（仅显式传参才生效，
    // 直接访问 / 的行为不变）；预填后立刻清掉地址栏里的凭据再渲染
    try {
      const q = new URLSearchParams(location.search);
      const u = q.get("u"), p = q.get("p");
      if (u) username.value = u;
      if (p) password.value = p;
      if (u || p) history.replaceState(null, "", location.pathname);
    } catch (e) { /* 预填失败不影响登录 */ }
    async function doLogin() {
      if (!username.value || !password.value) { err.value = "请输入用户名和密码"; return; }
      loading.value = true; err.value = "";
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username.value, password: password.value }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "登录失败");
        localStorage.setItem(TOKEN_KEY, data.token);
        try {   // 恢复该用户的云端偏好（主题/图标/壁纸等）
          const pr = await fetch("/api/user/prefs", { headers: { Authorization: "Bearer " + data.token } });
          if (pr.ok) {
            const prefs = (await pr.json()).prefs || {};
            const map = { theme: "kdzy_theme", icons: "kdzy_icons", iconsize: "kdzy_iconsize", wall: "kdzy_wall", autohome: "kdzy_autohome", glass: "kdzy_glass", iconlabel: "kdzy_iconlabel", avatar: "kdzy_avatar" };
            for (const [k, ls] of Object.entries(map)) {
              const v = prefs[k];
              if (v === undefined) continue;
              // 服务端保存的就是客户端写入的字符串，原样写回；
              // 早期版本这里写的是 JSON.parse 结果，对象会被转成 "[object Object]" 而搞坏 localStorage
              localStorage.setItem(ls, typeof v === "string" ? v : JSON.stringify(v));
            }
          }
        } catch (e) { /* 离线容错 */ }
        window.location.reload();
      } catch (e) { err.value = e.message; }
      loading.value = false;
    }
    return { username, password, loading, err, doLogin };
  },
  template: `
  <div class="login-wrap">
    <div class="login-card">
      <span class="logo-slot login-seal"><img src="assets/logo.png" alt="LOGO" onerror="this.parentElement.style.display='none'"></span>
      <div class="login-title">矿地智预</div>
      <div class="login-sub">MineGeoAI-Pre · 矿区土地利用智能预测系统</div>
      <div class="login-line"></div>
      <div class="login-form">
        <div class="field"><label>用户名</label>
          <input type="text" v-model="username" placeholder="请输入用户名" @keyup.enter="doLogin"></div>
        <div class="field"><label>密码</label>
          <input type="password" v-model="password" placeholder="请输入密码" @keyup.enter="doLogin"></div>
        <div class="login-err" v-if="err">{{ err }}</div>
        <button class="btn primary" style="width:100%; padding:11px;" :disabled="loading" @click="doLogin">
          {{ loading ? "认证中…" : "登 录" }}</button>
      </div>
      <div class="login-foot">离线超级账号：admin / 123 · 认证服务运行于本机，离线可用<template v-if="meta && meta.version"> · v{{ meta.version }}</template></div>
    </div>
  </div>`,
};

/* ================= 根组件 · Web 工作桌面（窗口管理器） ================= */
const APPS = [
  { id: "home", icon: "home", label: "系统概览", desc: "系统总览与业务闭环", w: 960, h: 660 },
  { id: "data", icon: "database", label: "数据管理", desc: "多矿区时序数据集管理", w: 1040, h: 640 },
  { id: "preprocess", icon: "funnel", label: "数据预处理", desc: "辐射定标 · 大气校正 · 去云", w: 1040, h: 680 },
  { id: "classify", icon: "crosshair", label: "分类分析", desc: "机器学习土地利用分类", w: 1120, h: 680 },
  { id: "change", icon: "trend", label: "变化分析", desc: "转移矩阵 · 动态度 · 热点", w: 1120, h: 680 },
  { id: "predict", icon: "compass", label: "预测建模", desc: "CA-Markov + CLUE-S 多情景预测", w: 1200, h: 720 },
  { id: "assistant", icon: "assistant", label: "图图", desc: "图图 · AI 助手 · 双击打开对话浮窗", w: 420, h: 560 },
  { id: "ai-settings", icon: "sliders", label: "图图设置", desc: "模型方案 · 知识库 · 参数", w: 760, h: 620 },
  { id: "detect", icon: "image", label: "图像检测", desc: "导入 GeoTIFF/影像 · 结合所选矿区数据库检测", w: 1180, h: 720 },
  { id: "files", icon: "folder", label: "文件管理", desc: "个人存储空间 · 10GB 配额", w: 1120, h: 660 },
  { id: "report", icon: "report", label: "报告生成", desc: "八类行业标准 Word 报告", w: 980, h: 620 },
  { id: "settings", icon: "gear", label: "系统设置", desc: "桌面壁纸 · 个性化", w: 900, h: 560 },
];
const APP_ICON = { home: "home", data: "database", preprocess: "funnel", classify: "crosshair", change: "trend", predict: "compass", report: "report", detect: "image", assistant: "assistant" };

ICONS.help = _svg('<circle cx="12" cy="12" r="8.6"/><path d="M9.7 9.4a2.5 2.6 0 1 1 3.5 2.3c-.8.4-1.2.9-1.2 1.8v.3"/><path d="M12 17.1h.01"/>');
ICONS.mail = _svg('<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="m3.5 7 7.6 5.4a1.6 1.6 0 0 0 1.8 0L20.5 7"/>');
ICONS.assistant = _svg('<path d="M12 3v2M12 19v2M5 12H3M21 12h-2"/><circle cx="12" cy="12" r="4.2"/><path d="M18.4 5.6 17 7M7 17l-1.4 1.4M18.4 18.4 17 17M7 7 5.6 5.6"/>');
ICONS.bolt = _svg('<path d="M13.2 2.6 4.8 13.4h5.4l-.6 8 8.4-10.8h-5.4l.6-8Z"/>');
ICONS.shield = _svg('<path d="M12 2.9 5 5.8v6.1c0 4.4 3 7.5 7 9.2 4-1.7 7-4.8 7-9.2V5.8l-7-2.9Z"/><path d="m9.2 11.8 2 2 3.6-3.6"/>');
ICONS.search = _svg('<circle cx="11" cy="11" r="6.3"/><path d="m15.7 15.7 4.5 4.5"/>');
ICONS.plus = _svg('<path d="M12 5.2v13.6"/><path d="M5.2 12h13.6"/>');
ICONS.chevron = _svg('<path d="m7.6 9.9 4.4 4.4 4.4-4.4"/>');
ICONS.folder = _svg('<path d="M3.5 6.8c0-1.1.9-2 2-2h3.4l2.1 2.4h7.5c1.1 0 2 .9 2 2v8.3c0 1.1-.9 2-2 2h-13c-1.1 0-2-.9-2-2V6.8Z"/>');
ICONS.upload = _svg('<path d="M12 15.5V4"/><path d="m7.5 8.5 4.5-4.5L16.5 8.5"/><path d="M4 20h16"/>');
ICONS.sliders = _svg('<path d="M5 5.5v13M12 5.5v13M19 5.5v13"/><circle cx="8.5" cy="10" r="2"/><circle cx="15.5" cy="15" r="2"/>');
ICONS.activity = _svg('<path d="M3 12h4l3-8 4 16 3-8h4"/>');
ICONS.image = _svg('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-4.5-4.5L8 19"/>');
ICONS.winmin = _svg('<path d="M5 12h14"/>');
ICONS.winmax = _svg('<rect x="4.5" y="4.5" width="15" height="15" rx="1.5"/>');
ICONS.winrestore = _svg('<rect x="4" y="8" width="12" height="12" rx="1.5"/><path d="M8 4h12v12"/>');
ICONS.winclose = _svg('<path d="m6 6 12 12M18 6 6 18"/>');
ICONS.grid = _svg('<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>');
/* 在线查看器图标 */
ICONS.zoomIn = _svg('<circle cx="11" cy="11" r="6.3"/><path d="m15.7 15.7 4.5 4.5"/><path d="M11 8.6v4.8M8.6 11h4.8"/>');
ICONS.zoomOut = _svg('<circle cx="11" cy="11" r="6.3"/><path d="m15.7 15.7 4.5 4.5"/><path d="M8.6 11h4.8"/>');
ICONS.fitScreen = _svg('<path d="M4 9.5V5.5c0-.8.7-1.5 1.5-1.5h4"/><path d="M20 14.5v4c0 .8-.7 1.5-1.5 1.5h-4"/><path d="M15 4h4c.8 0 1.5.7 1.5 1.5v4"/><path d="M9 20H5c-.8 0-1.5-.7-1.5-1.5v-4"/>');
ICONS.rotate = _svg('<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 3.5v5.5h-5.5"/>');
ICONS.wrapText = _svg('<path d="M3 6h18"/><path d="M3 12h15a3 3 0 1 1 0 6h-4"/><path d="m16 16-2 2 2 2"/><path d="M3 18h7"/>');
ICONS.listOrdered = _svg('<path d="M10 6h11M10 12h11M10 18h11"/><path d="M4 5.5 5.6 4.5V9"/><path d="M4 13.6c.5-.6 2-.8 2 .4 0 1-2 1.6-2 3h2.4"/>');
ICONS.copy = _svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4.5c-.8 0-1.5-.7-1.5-1.5V4.5C3 3.7 3.7 3 4.5 3h9C14.3 3 15 3.7 15 4.5V5"/>');
ICONS.external = _svg('<path d="M14 4h6v6"/><path d="M20 4 11.5 12.5"/><path d="M20 14.5v4c0 .8-.7 1.5-1.5 1.5h-13c-.8 0-1.5-.7-1.5-1.5v-13c0-.8.7-1.5 1.5-1.5h4"/>');
ICONS.prev = _svg('<path d="m15 5.5-6.5 6.5 6.5 6.5"/>');
ICONS.next = _svg('<path d="m9 5.5 6.5 6.5L9 18.5"/>');
ICONS.fileText = _svg('<path d="M13.5 3H6.5c-.8 0-1.5.7-1.5 1.5v15c0 .8.7 1.5 1.5 1.5h11c.8 0 1.5-.7 1.5-1.5V8.5z"/><path d="M13.5 3v5.5H19"/><path d="M8.5 13h7M8.5 16.5h4.5"/>');
ICONS.plus = _svg('<path d="M12 5.5v13M5.5 12h13"/>');
ICONS.minus = _svg('<path d="M5.5 12h13"/>');
ICONS.pencil = _svg('<path d="M12.5 20H21"/><path d="M16.4 3.6a2 2 0 0 1 2.8 2.8L7.6 18l-4 1.1L4.7 15z"/>');
ICONS.save = _svg('<path d="M14.5 3H5.8C4.8 3 4 3.8 4 4.8v14.4c0 1 .8 1.8 1.8 1.8h12.4c1 0 1.8-.8 1.8-1.8V7.2z"/><path d="M8 3v6h7V3"/><path d="M8 21v-6.5h8V21"/>');

const RootApp = {
  components: { LoginView },
  setup() {
    const authed = ref(!!localStorage.getItem(TOKEN_KEY));
    const user = ref(null);
    const meta = ref(null);
    const metaError = ref("");
    const dsId = ref(localStorage.getItem(DS_KEY) || "");
    const theme = ref(localStorage.getItem("kdzy_theme") || "saas");
    document.body.dataset.theme = theme.value;
    document.body.dataset.icons = iconStyle.value;   // 与响应式图标集保持同步

    /* AI 助手（桌面浮窗） */
    const chatOpen = ref(false);

    /* 使用说明 */
    const helpOpen = ref(false);
    const helpSections = [
      { icon: "home", title: "桌面操作", items: [
        "双击桌面图标打开应用；左下角开始菜单可查看全部应用",
        "拖动窗口标题栏移动窗口，拖右下角拉伸大小，双击标题栏最大化",
        "Dock 上的图标点击可切换焦点，再点一次最小化（会收进 Dock）",
        "右上角控制中心按钮可查看服务状态（CPU / 内存 / 在线用户）",
      ]},
      { icon: "bolt", title: "推荐分析流程", items: [
        "① 数据预处理 —— 辐射定标、大气校正、去云去噪与质量检验",
        "② 分类分析 —— 随机森林 / SVM / KNN 分类，输出精度与混淆矩阵",
        "③ 变化分析 —— 转移矩阵、动态度、变化热点识别",
        "④ 预测建模 —— CA-Markov / CLUE-S 多情景推演 + 独立精度验证",
        "⑤ 报告生成 —— 自动整合图表与结论，导出规范 Word 报告",
      ]},
      { icon: "compass", title: "预测建模要点", items: [
        "「单情景预测」：选模型、训练期与目标年，12 项参数可微调",
        "「多情景对比」：一次推演常规开采 / 强化开采 / 生态优先 / 综合平衡",
        "「精度验证」：用历史数据训练、独立预测有实测数据的年份并对比 Kappa",
      ]},
      { icon: "database", title: "数据与账户", items: [
        "右下角数据选择器可切换矿区（支持关键词搜索），未来矿区会持续增加",
        "文件管理：个人云存储（标准用户 10 GB），文件与偏好保存在服务端",
        "文件管理里点击文件名即可在线查看：图片可缩放/旋转，txt、csv、log 等文本自动识别编码（GBK 也不乱码）",
        "查看器是 macOS 风格窗口：左上角红黄绿灯＝关闭 / 最小化 / 铺满屏幕，Esc 也能关闭",
        "文本可直接在线编辑：点「编辑」改完按 Ctrl/⌘+S 或点蓝色「保存」，按原编码与原行尾写回（GBK、CRLF 都不会被改掉）",
        "「图像检测」可导入自己的影像（GeoTIFF/TIFF 或 jpg/png）：上传或从个人文件选，结合当前矿区的数据库做扰动检测、用数据库真值分类、与数据库对比变化",
        "预处理、分类、变化、精度验证也都能换用自己的数据：面板顶部「数据来源」可选 数据库 / 上传 / 个人文件",
        "系统设置：界面主题、图标风格与大小、桌面壁纸均可自定义",
        "偏好设置会随账号同步，换设备登录自动恢复",
      ]},
      { icon: "shield", title: "数据说明", items: [
        "当前平朔 / 安家岭为示范数据集，按矿区演化规律合成，用于演示与教学",
        "接入真实数据：参见项目文档《路线A-真实数据接入指南》",
      ]},
    ];
    const themes = [
      { id: "atlas", label: "清新简约", desc: "shadcn 风格 · 中性色 + 翡翠强调", c1: "#059669", c2: "#fafafa" },
      { id: "console", label: "深空大屏", desc: "指挥调度大屏风格 · 智慧矿山场景", c1: "#22d3ee", c2: "#0a1220" },
      { id: "saas", label: "极简工作台", desc: "现代 SaaS 风格 · 企业科研作业场景", c1: "#4f46e5", c2: "#f6f7f9" },
      { id: "ubuntu", label: "Ubuntu 风", desc: "Linux 发行版设计语言 · 暖灰纸面 + 标志性橙", c1: "#e95420", c2: "#f7f6f5" },
    ];
    function setTheme(id) {
      rememberOpen();
      localStorage.setItem("kdzy_theme", id);
      window.location.reload();
    }
    function switchDataset(id) {
      const target = id || dsId.value;
      if (!target || target === dsId.value) return;
      localStorage.setItem(DS_KEY, target);
      window.location.reload();
    }

    /* ---------- 窗口管理器 ---------- */
    const wins = reactive([]);
    let zTop = 100;
    const focused = ref(null);
    const startOpen = ref(false);
    const selIcon = ref(null);
    const clock = ref("");
    const bouncing = ref({});          // Dock 启动弹跳

    function appOf(id) { return APPS.find(a => a.id === id) || APPS[0]; }

    /* Dock 图标弹跳（macOS 启动反馈） */
    function bounce(id) {
      bouncing.value = { ...bouncing.value, [id]: true };
      setTimeout(() => {
        const m = { ...bouncing.value }; delete m[id]; bouncing.value = m;
      }, 660);
    }

    /* 计算窗口动画的变换原点：优先 Dock 图标，其次桌面图标，兜底底部居中 */
    function originFrom(id, x, y, useDom) {
      let target = document.querySelector('.tk-app[data-appid="' + id + '"] .dock-tile')
                || document.querySelector('.desk-icon[data-appid="' + id + '"] .app-tile');
      if (!target) return "50% 100%";
      const r = target.getBoundingClientRect();
      if (useDom) {
        const winEl = document.querySelector('.win[data-appid="' + id + '"]');
        if (winEl) {
          const wr = winEl.getBoundingClientRect();
          x = wr.x; y = wr.y;
        }
      }
      return Math.round(r.x + r.width / 2 - x) + "px " + Math.round(r.y + r.height / 2 - y) + "px";
    }

    /* 窗口层级上限：Dock 固定 5000，窗口再被点也不能超过它，
       否则长时间使用后（每次聚焦 +1）窗口会盖住悬浮 Dock */
    const WIN_Z_MAX = 4900;
    function focusWin(id) {
      const w = wins.find(x => x.id === id);
      if (!w) return;
      w.z = Math.min(++zTop, WIN_Z_MAX);
      w.min = false;
      focused.value = id;
    }
    /* 浮窗不重叠：助手常驻最右，消息面板并排到它左侧（见 .msg-float.beside）；
       窗口太窄排不下时改成互斥——后开的那个顶掉先开的，绝不让两块面板叠在一起 */
    const FLOAT_MIN_W = 900;        // 并排所需最小宽度：22 + 396（助手）+ 14（间距）+ 380（消息）
    function toggleFloat(me, other) {
      if (!me.value && other.value && window.innerWidth < FLOAT_MIN_W) other.value = false;
      me.value = !me.value;
    }
    /* 必须包一层：模板里 msgOpen 取到的是解包后的布尔值，不能把 ref 当参数传出去 */
    function toggleMsg() { toggleFloat(msgOpen, chatOpen); }
    function toggleChat() { toggleFloat(chatOpen, msgOpen); }
    function openApp(id) {
      startOpen.value = false;
      if (id === "assistant") { toggleChat(); return; }
      const existing = wins.find(x => x.id === id);
      if (existing) {
        if (existing.min) {                       // 还原：从 Dock 位置放大浮现
          existing.origin = originFrom(id, existing.x, existing.y, true);
          existing.min = false;
          existing.anim = "opening";
          focusWin(id);
          setTimeout(() => { existing.anim = ""; }, 360);
        } else {
          focusWin(id);
        }
        return;
      }
      const app = APPS.find(a => a.id === id);
      if (!app) return;
      const n = wins.length;
      const w = Math.min(app.w, window.innerWidth - 60);
      const h = Math.min(app.h, window.innerHeight - 120);
      const x = Math.max(10, 70 + (n % 6) * 34);
      const y = Math.max(8, 40 + (n % 6) * 30);
      wins.push({
        id, x, y, w, h, z: Math.min(++zTop, WIN_Z_MAX), min: false, max: false,
        anim: "opening", origin: originFrom(id, x, y, false),
      });
      focused.value = id;
      bounce(id);
      const ref = wins[wins.length - 1];
      setTimeout(() => { ref.anim = ""; }, 360);
    }
    /* 主题切换重载后恢复桌面：返回是否恢复过（恢复过就不再叠加默认的系统概览） */
    function restoreOpen() {
      let list = [];
      try { list = JSON.parse(sessionStorage.getItem(REOPEN_KEY) || "[]"); } catch (e) { list = []; }
      sessionStorage.removeItem(REOPEN_KEY);
      for (const it of list) {
        if (!it || !APPS.find(a => a.id === it.id)) continue;
        openApp(it.id);
        const w = wins.find(x => x.id === it.id);
        if (w && it.max) { w.max = true; focusWin(it.id); }
      }
      return list.length > 0;
    }
    function closeApp(id) {
      const w = wins.find(x => x.id === id);
      if (!w || w.anim === "closing") return;
      w.origin = originFrom(id, 0, 0, true);
      w.anim = "closing";
      setTimeout(() => {
        const i = wins.findIndex(x => x.id === id);
        if (i >= 0) wins.splice(i, 1);
        if (focused.value === id) focused.value = wins.length ? wins[wins.length - 1].id : null;
      }, 210);
    }
    function toggleMin(id) {
      const w = wins.find(x => x.id === id);
      if (!w || w.anim) return;
      if (!w.min) {                                // 最小化：向 Dock 图标收缩
        w.origin = originFrom(id, 0, 0, true);
        w.anim = "minimizing";
        setTimeout(() => { w.min = true; w.anim = ""; }, 300);
      } else {                                     // 还原
        w.origin = originFrom(id, w.x, w.y, true);
        w.min = false;
        w.anim = "opening";
        focusWin(id);
        setTimeout(() => { w.anim = ""; }, 360);
      }
    }
    function toggleMax(id) {
      const w = wins.find(x => x.id === id);
      if (!w || w.anim) return;
      w.anim = "resizing";
      w.max = !w.max;
      if (!w.max) focusWin(id);
      setTimeout(() => { w.anim = ""; }, 320);
    }
    function taskClick(id) {
      const w = wins.find(x => x.id === id);
      if (!w) return;
      if (w.min || focused.value !== id) {
        if (w.min) { toggleMin(id); } else { focusWin(id); }
      } else {
        toggleMin(id);
      }
    }
    function dragStart(e, w) {
      if (w.max) return;
      focusWin(w.id);
      const sx = e.clientX, sy = e.clientY, ox = w.x, oy = w.y;
      const move = (ev) => {
        w.x = Math.max(120 - w.w, Math.min(window.innerWidth - 90, ox + ev.clientX - sx));
        w.y = Math.max(0, Math.min(window.innerHeight - 110, oy + ev.clientY - sy));
      };
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }
    function resizeStart(e, w) {
      e.stopPropagation();
      focusWin(w.id);
      const sx = e.clientX, sy = e.clientY, ow = w.w, oh = w.h;
      const move = (ev) => {
        w.w = Math.max(560, Math.min(window.innerWidth - w.x - 6, ow + ev.clientX - sx));
        // 下边距按胶囊 Dock 的实际高度留（14 底距 + 78 高 + 12 间隙），避免窗口被 Dock 压住一截
        w.h = Math.max(380, Math.min(window.innerHeight - w.y - 104, oh + ev.clientY - sy));
      };
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }

    /* ---------- 桌面壁纸 ---------- */
    const WALL_PRESETS = [
      { id: "sage", label: "远山黛", css: "linear-gradient(165deg,#eef1e6 0%,#c9dac6 48%,#8fae9d 100%)" },
      { id: "forest", label: "林海", css: "linear-gradient(160deg,#134e5e 0%,#3f7a58 55%,#71b280 100%)" },
      { id: "nebula", label: "深空", css: "linear-gradient(150deg,#0f2027 0%,#203a43 50%,#2c5364 100%)" },
      { id: "dusk", label: "暮色", css: "linear-gradient(135deg,#355c7d 0%,#6c5b7b 55%,#c06c84 100%)" },
      { id: "sky", label: "晴空", css: "linear-gradient(180deg,#a1c4fd 0%,#c2e9fb 100%)" },
      { id: "sunset", label: "斜阳", css: "linear-gradient(135deg,#ff9966 0%,#ff5e62 100%)" },
      { id: "graphite", label: "石墨", css: "linear-gradient(145deg,#2b2f36 0%,#414750 55%,#5a616b 100%)" },
      { id: "mist", label: "薄雾", css: "linear-gradient(160deg,#e8ecf1 0%,#d5dde6 50%,#b8c4d0 100%)" },
      // ── 照片壁纸（来源 pexels.com，Pexels License 免费可商用）──
      { id: "p-neon", label: "霓虹光带", kind: "photo", img: "assets/wallpapers/neon-magenta.jpg", credit: "摄影 thales13 / pexels.com" },
      { id: "p-boat", label: "落日归舟", kind: "photo", img: "assets/wallpapers/dusk-boat.jpg", credit: "摄影 Tu N Vu / pexels.com" },
      { id: "p-prism", label: "蓝紫棱镜", kind: "photo", img: "assets/wallpapers/prism-blue.jpg", credit: "摄影 thales13 / pexels.com" },
      { id: "p-rose", label: "玫瑰几何", kind: "photo", img: "assets/wallpapers/rose-geometry.jpg", credit: "摄影 Steve / pexels.com" },
    ];
    const DEFAULT_WALL = { atlas: "sage", console: "nebula", saas: "mist", ubuntu: "sunset" };
    const wall = ref(lsJSON("kdzy_wall", null));
    const deskWall = computed(() => {
      let css;
      if (!wall.value) {
        const p = WALL_PRESETS.find(x => x.id === DEFAULT_WALL[theme.value]);
        if (p && p.img) {
          return { backgroundImage: `url(${p.img})`, backgroundSize: "cover", backgroundPosition: "center" };
        }
        css = (p && p.css) || "linear-gradient(165deg,#eef1e6,#8fae9d)";
      } else if (wall.value.kind === "preset") {
        const p = WALL_PRESETS.find(x => x.id === wall.value.id);
        if (p && p.img) {                       // 照片壁纸
          return { backgroundImage: `url(${p.img})`, backgroundSize: "cover", backgroundPosition: "center" };
        }
        css = (p && p.css) || "#cfd8cf";
      } else {
        return { backgroundImage: `url(${wall.value.data})`, backgroundSize: "cover", backgroundPosition: "center" };
      }
      return { background: css };
    });
    window.addEventListener("kdzy-wall", () => {
      wall.value = lsJSON("kdzy_wall", null);
    });

    /* ---------- 控制中心 ---------- */
    const panelOpen = ref(false);
    const sysStats = ref(null);
    let pollTimer = null;
    async function fetchStats() {
      try { sysStats.value = await api("/system/stats"); } catch (e) { /* 静默重试 */ }
    }
    function togglePanel() {
      panelOpen.value = !panelOpen.value;
      if (panelOpen.value) { fetchStats(); pollTimer = setInterval(fetchStats, 5000); }
      else if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }
    function fmtUptime(s) {
      if (s < 60) return s + " 秒";
      if (s < 3600) return Math.floor(s / 60) + " 分钟";
      if (s < 86400) return Math.floor(s / 3600) + " 小时 " + Math.floor(s % 3600 / 60) + " 分";
      return Math.floor(s / 86400) + " 天 " + Math.floor(s % 86400 / 3600) + " 小时";
    }

    /* 窗口被拖窄到放不下并排时，收起消息面板——保证两块浮窗任何时候都不重叠 */
    function onFloatResize() {
      if (chatOpen.value && msgOpen.value && window.innerWidth < FLOAT_MIN_W) msgOpen.value = false;
    }
    onMounted(() => window.addEventListener("resize", onFloatResize));
    onUnmounted(() => window.removeEventListener("resize", onFloatResize));

    /* 时钟 */
    function tick() {
      const d = new Date();
      clock.value = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    }
    tick();
    setInterval(tick, 15000);

    /* 未读消息轮询（Dock 角标；15 秒一次，未登录不请求） */
    async function pollUnread() {
      if (!authed.value) return;
      try { msgUnread.value = (await api("/msg/unread")).unread || 0; } catch (e) { /* 离线忽略 */ }
    }
    pollUnread();
    setInterval(pollUnread, 15000);

    function loadMeta() {
      api("/meta").then(m => {
        meta.value = m;
        if (!dsId.value) dsId.value = m.dataset_id;
      }).catch(e => { metaError.value = e.message; });
      api("/auth/me").then(r => { user.value = r.user; }).catch(() => {});
    }
    if (authed.value) {
      loadMeta();
      // 主题切换重载后先恢复桌面，其次才回到系统概览
      if (!restoreOpen() && localStorage.getItem("kdzy_autohome") !== "0") openApp("home");  // 可在系统设置关闭
    }
    onUnauthorized = () => { authed.value = false; meta.value = null; wins.length = 0; };

    async function logout() {
      try { await api("/auth/logout", {}); } catch (e) { /* 忽略 */ }
      localStorage.removeItem(TOKEN_KEY);
      authed.value = false;
      meta.value = null;
      wins.length = 0;
    }

    return {
      authed, user, meta, metaError, logout, toasts,
      dsId, switchDataset, theme, themes, setTheme,
      deskWall, panelOpen, sysStats, togglePanel, fmtUptime,
      helpOpen, helpSections, chatOpen, userAvatar, msgOpen, msgUnread, toggleMsg,
      apps: APPS, wins, focused, startOpen, selIcon, clock, bouncing,
      appOf, openApp, closeApp, focusWin, toggleMin, toggleMax, taskClick, dragStart, resizeStart,
    };
  },
  template: `
  <LoginView v-if="!authed" />
  <div v-else class="desktop" :style="deskWall" @pointerdown.self="startOpen = false">
    <!-- 桌面图标 -->
    <div class="desk-icons">
      <div v-for="a in apps" :key="a.id" class="desk-icon"
        :class="{ sel: selIcon === a.id, launching: bouncing[a.id] }"
        :data-appid="a.id" :title="a.desc" @click="selIcon = a.id" @dblclick="openApp(a.id)">
        <div class="app-tile" :class="'app-grad-' + a.id"><ic :n="a.icon"></ic></div>
        <div class="di-name">{{ a.label }}</div>
      </div>
    </div>
    <!-- 使用说明 -->
    <button class="help-btn" :class="{ on: helpOpen }" title="使用说明" @click="helpOpen = !helpOpen">
      <ic n="help"></ic><span>使用说明</span>
    </button>
    <div class="help-backdrop" v-if="helpOpen" @pointerdown="helpOpen = false"></div>
    <div class="help-panel" v-if="helpOpen" @pointerdown.stop>
      <div class="hp-head"><ic n="help"></ic> 使用说明
        <button class="hp-close" title="收起" @click="helpOpen = false"><ic n="winclose"></ic></button>
      </div>
      <div class="hp-body">
        <div class="hp-sec" v-for="s in helpSections" :key="s.title">
          <div class="hp-title"><ic :n="s.icon"></ic>{{ s.title }}</div>
          <ul class="hp-list">
            <li v-for="(t, i) in s.items" :key="i">{{ t }}</li>
          </ul>
        </div>
      </div>
      <div class="hp-foot">矿地智预 MineGeoAI-Pre · 矿区土地利用智能预测系统<template v-if="meta && meta.version"> · v{{ meta.version }}</template></div>
    </div>

    <!-- 应用窗口 -->
    <div v-for="w in wins" :key="w.id" class="win"
      :class="[w.max ? 'maximized' : '', w.min ? 'minimized' : '', w.anim ? 'win-' + w.anim : '', focused === w.id ? 'focused' : '']"
      :data-appid="w.id"
      :style="Object.assign({ transformOrigin: w.origin || '50% 100%', zIndex: w.z },
        w.max ? { left: '0px', top: '0px', width: '100%', height: '100%' }
              : { left: w.x + 'px', top: w.y + 'px', width: w.w + 'px', height: w.h + 'px' })"
      @pointerdown="focusWin(w.id)">
      <div class="win-titlebar" @pointerdown="dragStart($event, w)" @dblclick="toggleMax(w.id)">
        <div class="tl-group">
          <button class="tl tl-close" title="关闭" @click.stop="closeApp(w.id)"><ic n="winclose"></ic></button>
          <button class="tl tl-min" :title="w.min ? '还原' : '最小化'" @click.stop="toggleMin(w.id)"><ic n="winmin"></ic></button>
          <button class="tl tl-max" :title="w.max ? '还原' : '最大化'" @click.stop="toggleMax(w.id)"><ic :n="w.max ? 'winrestore' : 'winmax'"></ic></button>
        </div>
        <span class="wt-ic"><ic :n="appOf(w.id).icon"></ic></span>
        <span class="win-title">{{ appOf(w.id).label }}</span>
      </div>
      <div class="win-body" :data-app="w.id">
        <component :is="'page-' + w.id" :meta="meta" :user="user" @goto="openApp"></component>
      </div>
      <div class="win-resize" v-if="!w.max" @pointerdown="resizeStart($event, w)"></div>
    </div>

    <!-- 开始菜单 -->
    <div class="start-menu" v-if="startOpen" @pointerdown.stop>
      <div class="sm-head"><ic n="grid"></ic> 全部应用</div>
      <div class="start-grid">
        <div v-for="a in apps" :key="a.id" class="sm-app" :data-appid="a.id" @click="openApp(a.id)">
          <div class="sm-ic"><ic :n="a.icon"></ic></div>
          <div class="sm-name">{{ a.label }}</div>
        </div>
      </div>
      <div class="sm-foot" v-if="user">
        <img v-if="userAvatar" class="uava" :src="userAvatar" alt="">
        <ic v-else n="user"></ic> {{ user.username }}
        <span class="chip" style="margin-left:6px;">{{ user.role === 'super' ? '超级管理员' : user.role }}</span>
        <button class="btn small" style="margin-left:auto;" @click="logout"><ic n="logout"></ic>退出</button>
      </div>
    </div>

    <!-- 控制中心（右侧折叠栏） -->
    <div class="ctrl-panel" v-if="panelOpen" @pointerdown.stop>
      <div class="cp-head"><ic n="activity"></ic> 控制中心
        <button class="cp-close" title="收起" @click="togglePanel"><ic n="winclose"></ic></button>
      </div>
      <div class="cp-body" v-if="sysStats">
        <div class="cp-sec">服务状态</div>
        <div class="cp-meter">
          <div class="cp-mrow"><span>CPU 占用</span><b>{{ sysStats.cpu_percent }}%</b></div>
          <div class="progress-bar"><div :style="{ width: sysStats.cpu_percent + '%' }"></div></div>
        </div>
        <div class="cp-meter">
          <div class="cp-mrow"><span>内存</span><b>{{ sysStats.mem.percent }}%</b></div>
          <div class="progress-bar"><div :style="{ width: sysStats.mem.percent + '%' }"></div></div>
          <div class="cp-sub">{{ sysStats.mem.used_gb }} GB / {{ sysStats.mem.total_gb }} GB</div>
        </div>
        <div class="cp-meter">
          <div class="cp-mrow"><span>磁盘</span><b>{{ sysStats.disk.percent }}%</b></div>
          <div class="progress-bar"><div :style="{ width: sysStats.disk.percent + '%' }"></div></div>
          <div class="cp-sub">{{ sysStats.disk.used_gb }} GB / {{ sysStats.disk.total_gb }} GB</div>
        </div>
        <div class="kv"><span class="k">服务进程内存</span><span class="v">{{ sysStats.proc_mem_mb }} MB</span></div>
        <div class="kv"><span class="k">服务已运行</span><span class="v">{{ fmtUptime(sysStats.uptime_s) }}</span></div>
        <div class="kv"><span class="k">累计请求</span><span class="v">{{ sysStats.requests_served }}</span></div>
        <div class="cp-sec">用户与会话</div>
        <div class="cp-online">
          <b>{{ sysStats.online_users }}</b><span>在线用户</span>
          <b style="margin-left:auto;">{{ sysStats.users_total }}</b><span>注册账号</span>
        </div>
        <div class="cp-sec">数据服务</div>
        <div class="kv"><span class="k">矿区数据库</span><span class="v">{{ sysStats.datasets }} 个</span></div>
        <div class="kv"><span class="k">预测引擎</span><span class="v">就绪</span></div>
        <div class="cp-note">{{ sysStats.engine }}</div>
      </div>
      <div class="cp-body" v-else><div class="empty-tip">正在读取服务状态…</div></div>
    </div>

    <!-- AI 助手：桌面悬浮对话面板（毛玻璃） -->
    <assistant-chat v-if="chatOpen" @close="chatOpen = false"
      @settings="openApp('ai-settings')" @goto="openApp"></assistant-chat>

    <!-- 站内消息：Dock 图标弹出的浮窗（助手也开着时靠 left 挪到它左边，两块面板不重叠） -->
      <messages-panel v-if="msgOpen" :user="user" :class="{ beside: chatOpen }" @close="msgOpen = false"
        @read="pollUnread"></messages-panel>

    <!-- 任务栏 -->
    <div class="taskbar" @pointerdown.stop>
      <div class="tk-start" @click="startOpen = !startOpen" :class="{ on: startOpen }">
        <span class="logo-slot tk-logo"><img src="assets/logo.png" alt="LOGO" onerror="this.parentElement.style.display='none'"></span>
        <span class="tk-brand"><b>矿地智预</b><i>MineGeoAI-Pre</i></span>
        <ic n="grid"></ic>
      </div>
      <div class="tk-apps">
        <div v-for="w in wins" :key="w.id" class="tk-app"
          :class="{ active: focused === w.id && !w.min, bounce: bouncing[w.id] }"
          :data-appid="w.id" @click="taskClick(w.id)" :title="appOf(w.id).label">
          <span class="dock-tile" :class="'app-grad-' + w.id"><ic :n="appOf(w.id).icon"></ic></span>
          <span class="tk-dot"></span>
        </div>
      </div>
      <div class="tk-spacer"></div>
      <div class="tk-tray">
        <button class="tray-btn msg-btn" :class="{ on: msgOpen }" title="站内消息（私聊 / 系统通知）"
          @click="toggleMsg()">
          <ic n="mail"></ic>
          <span v-if="msgUnread" class="msg-badge">{{ msgUnread > 99 ? "99+" : msgUnread }}</span>
        </button>
        <button class="tray-btn" :class="{ on: panelOpen }" title="控制中心" @click="togglePanel"><ic n="activity"></ic></button>
        <ds-picker :datasets="meta ? meta.datasets : []" :current="dsId" @pick="switchDataset"></ds-picker>
        <span class="tk-clock">{{ clock }}</span>
        <span v-if="user" class="tk-user">
          <img v-if="userAvatar" class="uava" :src="userAvatar" alt="">
          <ic v-else n="user"></ic> {{ user.username }}</span>
      </div>
    </div>
  </div>`,
};

/* ================= 首页 ================= */
const PageHome = {
  props: ["meta"],
  emits: ["goto"],
  setup(props) {
    const entries = [
      { id: "preprocess", icon: "funnel", name: "数据预处理", desc: "辐射定标 · 大气校正 · 去云去噪", grad: "preprocess" },
      { id: "classify", icon: "crosshair", name: "分类分析", desc: "随机森林 / SVM / KNN 集成分类", grad: "classify" },
      { id: "change", icon: "trend", name: "变化分析", desc: "转移矩阵 · 动态度 · 变化热点", grad: "change" },
      { id: "predict", icon: "compass", name: "预测建模", desc: "CA-Markov + CLUE-S 多情景推演", grad: "predict" },
      { id: "detect", icon: "image", name: "图像检测", desc: "导入影像 · 扰动检测 · 与数据库比对", grad: "detect" },
      { id: "report", icon: "report", name: "报告生成", desc: "八类行业标准模板一键导出", grad: "report" },
      { id: "files", icon: "folder", name: "文件管理", desc: "个人存储 · 文本在线编辑 · 图片查看", grad: "files" },
      { id: "assistant", icon: "assistant", name: "图图", desc: "AI 助手 · 本地大模型 · 知识库问答", grad: "assistant" },
    ];
    const flow = ["数据获取", "辐射定标", "大气校正", "去云去噪", "特征构建", "监督分类", "变化检测", "多情景预测", "精度验证", "报告输出"];

    /* ---- 指标卡：数值滚动 ---- */
    const cArea = useCountUp(1000), cYears = useCountUp(700), cRes = useCountUp(900), cCls = useCountUp(600);
    const region = computed(() => (props.meta ? props.meta.dataset.region : ""));
    const areaKm2 = computed(() => (props.meta ? props.meta.dataset.area_km2 : 0));
    const resM = computed(() => (props.meta ? props.meta.dataset.resolution_m : 0));
    const years = computed(() => (props.meta ? props.meta.dataset.years : []));
    const nClasses = computed(() => (props.meta ? props.meta.dataset.classes.length : 0));

    /* ---- 真实数据派生：五期地类面积 + 最新一期结构 + 采矿用地 20 年变化 ---- */
    const lastYear = computed(() => (years.value.length ? years.value[years.value.length - 1] : null));
    const statsOf = (y) => (props.meta && props.meta.stats ? props.meta.stats[String(y)] : null);
    const miningPct = computed(() => {            // 采矿用地 首期→末期 相对变化（真实统计，不编造）
      const ys = years.value;
      if (ys.length < 2) return null;
      const pick = (y) => {
        const s = statsOf(y);
        const c = s && s.classes.find(x => x.name === "采矿用地");
        return c ? c.area_ha : null;
      };
      const a = pick(ys[0]), b = pick(ys[ys.length - 1]);
      if (a === null || b === null || a <= 0) return null;
      return (b - a) / a * 100;
    });

    /* ---- 两个图表：五期面积堆叠 + 最新一期结构环 ---- */
    const trendEl = ref(null), donutEl = ref(null);
    const trendChart = useChart(() => trendEl.value);
    const donutChart = useChart(() => donutEl.value);

    function renderCharts() {
      if (!props.meta) return;
      const ys = years.value, st = props.meta.stats || {};
      const names = props.meta.dataset.classes.map(c => c.name);
      /* 画"相对首期的面积变化量"而不是堆叠面积：本区采矿用地只占 2.5%，
         堆叠图里那条最关键的曲线会被林地/耕地压成看不见的一丝；
         换成以首期为 0 的变化量后，采矿用地 +141 ha 的变化一眼就能看到。 */
      const base0 = (st[String(ys[0])] || {}).classes || [];
      trendChart.render({
        ...baseChart(""),
        tooltip: { trigger: "axis", backgroundColor: PAL.tipBg, borderColor: PAL.tipBorder, textStyle: { color: PAL.tipText, fontSize: 12, fontFamily: PAL.font },
                   valueFormatter: v => (v > 0 ? "+" : "") + v + " ha" },
        legend: { show: false },
        grid: { left: 8, right: 14, top: 16, bottom: 4, containLabel: true },
        xAxis: { type: "category", data: ys, boundaryGap: false, axisLabel: CHART_TEXT, axisTick: { show: false }, axisLine: { lineStyle: { color: PAL.split } } },
        yAxis: { type: "value", name: "公顷", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT,
                 splitLine: { lineStyle: { color: PAL.split } } },
        series: names.map((n, idx) => {
          const b0 = (base0.find(x => x.name === n) || {}).area_ha || 0;
          const key = n === "采矿用地";
          return {
            name: n, type: "line", smooth: true, symbol: "circle", symbolSize: key ? 8 : 6,
            lineStyle: { width: key ? 3 : 1.8, color: CLASS_COLORS[n] },
            itemStyle: { color: CLASS_COLORS[n] },
            areaStyle: key ? { opacity: 0.16, color: CLASS_COLORS[n] } : undefined,
            emphasis: { focus: "series" },
            markLine: idx === 0 ? {
              silent: true, symbol: "none", label: { show: false },
              lineStyle: { color: PAL.split, type: "dashed", width: 1 },
              data: [{ yAxis: 0 }],
            } : undefined,
            data: ys.map(y => { const c = ((st[String(y)] || {}).classes || []).find(x => x.name === n);
                               return c ? +(c.area_ha - b0).toFixed(1) : 0; }),
          };
        }),
        animationDuration: 900, animationEasing: "cubicOut",
      });
      const sy = statsOf(lastYear.value);
      if (!sy) return;
      donutChart.render({
        ...baseChart(""),
        tooltip: { trigger: "item", backgroundColor: PAL.tipBg, borderColor: PAL.tipBorder, textStyle: { color: PAL.tipText, fontSize: 12, fontFamily: PAL.font },
                   formatter: p => `${p.name}<br/>${p.value} ha · ${p.percent}%` },
        legend: { show: false },
        series: [{
          type: "pie", radius: ["58%", "86%"], center: ["50%", "50%"], avoidLabelOverlap: true,
          itemStyle: { borderColor: PAL.tipBg, borderWidth: 2 },
          label: { show: false }, labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 6, itemStyle: { shadowBlur: 16, shadowColor: "rgba(20,32,24,.28)" } },
          data: sy.classes.map(c => ({ name: c.name, value: c.area_ha, itemStyle: { color: CLASS_COLORS[c.name] } })),
          animationType: "scale", animationDuration: 900, animationEasing: "cubicOut",
        }],
      });
    }

    onMounted(() => {
      cArea.set(areaKm2.value); cYears.set(years.value.length);
      cRes.set(resM.value); cCls.set(nClasses.value);
      renderCharts();
    });
    watch(() => props.meta, () => {          // 切换矿区数据库后：数字与图表一起重算
      cArea.set(areaKm2.value); cYears.set(years.value.length);
      cRes.set(resM.value); cCls.set(nClasses.value);
      renderCharts();
    });
    onUnmounted(() => { trendChart.dispose(); donutChart.dispose(); cArea.stop(); cYears.stop(); cRes.stop(); cCls.stop(); });

    return { entries, flow, region, areaKm2, resM, years, nClasses, miningPct,
             cArea, cYears, cRes, cCls, trendEl, donutEl, lastYear, fmtIsInt: (v) => Math.round(v) };
  },
  template: `
  <div class="home">
    <!-- 封面：等高线底纹 + 缓慢漂浮的光斑（纯 CSS，不增加依赖） -->
    <div class="hero hero-live">
      <span class="hero-orb o1"></span>
      <span class="hero-orb o2"></span>
      <div class="hero-inner rise" style="--d:0ms">
        <div class="hero-kicker">MineGeoAI-Pre · 矿区土地利用空间格局预测系统</div>
        <h1>矿地智预 · 矿区土地利用智能预测系统</h1>
        <p>基于 20 年 Landsat 时序遥感数据与改良 CLUE-S + CA-Markov 融合模型，贯通遥感数据预处理、
        高精度土地利用分类、历史变化分析、多情景预测建模、可视化展示与标准化报告输出的完整业务闭环，
        为矿山监管、生态修复与开采规划提供量化、可视化的科学决策依据。</p>
        <div class="hero-chips">
          <span class="chip green">预测精度 85%+</span>
          <span class="chip">改良 CLUE-S + CA-Markov 融合模型</span>
          <span class="chip">4 大情景 · 12 项可调参数</span>
          <span class="chip">离线可跑 · 本地大模型</span>
        </div>
      </div>
    </div>

    <!-- 指标卡：数字滚动 + 错峰入场 -->
    <div class="grid cols-4 kpi-row" v-if="meta">
      <div class="stat-card kpi rise" style="--d:60ms">
        <div class="kpi-bar" style="--c:#4f46e5"></div>
        <div class="kpi-head"><span class="kpi-ic"><ic n="globe"></ic></span><div class="label">示范区域</div></div>
        <div class="value" style="font-size:15px; font-family:inherit;">{{ region.length > 12 ? region.slice(0, 12) + '…' : region }}</div>
        <div class="kpi-foot">{{ meta.dataset.short_name || '示范数据集' }}</div>
      </div>
      <div class="stat-card kpi rise" style="--d:140ms">
        <div class="kpi-bar" style="--c:#059669"></div>
        <div class="kpi-head"><span class="kpi-ic"><ic n="layers"></ic></span><div class="label">研究区面积</div></div>
        <div class="value"><span class="num">{{ cArea.val.value.toFixed(2) }}</span><span class="unit">km²</span></div>
        <div class="kpi-foot">{{ (meta.dataset.area_km2 * 100).toFixed(0) }} 公顷 · EPSG:32649</div>
      </div>
      <div class="stat-card kpi rise" style="--d:220ms">
        <div class="kpi-bar" style="--c:#0891b2"></div>
        <div class="kpi-head"><span class="kpi-ic"><ic n="activity"></ic></span><div class="label">时序数据</div></div>
        <div class="value">{{ years[0] }}-{{ years[years.length-1] }}<span class="unit">{{ fmtIsInt(cYears.val.value) }} 期</span></div>
        <div class="kpi-foot">Landsat 30 m 多光谱 · 5 年一期</div>
      </div>
      <div class="stat-card kpi rise" style="--d:300ms">
        <div class="kpi-bar" style="--c:#d97706"></div>
        <div class="kpi-head"><span class="kpi-ic"><ic n="crosshair"></ic></span><div class="label">空间分辨率 / 地类</div></div>
        <div class="value"><span class="num">{{ fmtIsInt(cRes.val.value) }}</span><span class="unit">m</span>
          <span class="unit" style="margin-left:10px;">{{ fmtIsInt(cCls.val.value) }} 类</span></div>
        <div class="kpi-foot">耕地 · 林地 · 建设用地 · 采矿用地 · 水域 · 未利用地</div>
      </div>
    </div>

    <!-- 真实数据可视化：五期面积演化 + 最新一期结构 -->
    <div class="grid cols-3 home-charts" style="grid-template-columns: 1.5fr 1fr;" v-if="meta">
      <div class="panel rise" style="--d:360ms">
        <h3>地类面积变化 <span class="h3-note">相对 {{ years[0] }} 年基准 · 公顷</span></h3>
        <div class="mini-chart" ref="trendEl"></div>
        <div class="legend-row">
          <span v-for="c in meta.dataset.classes" :key="c.id" class="lg-item">
            <i class="lg-dot" :style="{ background: c.color }"></i>{{ c.name }}</span>
        </div>
      </div>
      <div class="panel rise" style="--d:440ms">
        <h3>{{ lastYear }} 年地类结构</h3>
        <div class="donut-wrap">
          <div class="mini-chart donut" ref="donutEl"></div>
          <div class="donut-center">
            <div class="dc-num">{{ (meta.stats[String(lastYear)] || {}).total_ha || '—' }}</div>
            <div class="dc-unit">公顷</div>
          </div>
        </div>
        <div class="kpi-callout" v-if="miningPct !== null">
          <ic n="bolt"></ic>
          <span>采矿用地 {{ years[0] }} → {{ lastYear }} 增长
            <b>+{{ Math.round(miningPct) }}%</b>，是本区土地利用变化的主导驱动</span>
        </div>
      </div>
    </div>

    <div class="grid cols-3" style="grid-template-columns: 1.35fr 1fr;">
      <div class="panel rise" style="--d:520ms">
        <h3>功能模块 <span class="h3-note">点击直达</span></h3>
        <div class="grid cols-2" style="gap:12px;">
          <div v-for="(e, i) in entries" :key="e.id" class="quick-entry qe-live" :data-appid="e.id"
               @click="$emit('goto', e.id)" :style="{ '--d': (560 + i * 45) + 'ms' }">
            <div class="qe-icon" :class="'app-grad-' + (e.grad || e.id)"><ic :n="e.icon"></ic></div>
            <div class="qe-text">
              <div class="qe-name">{{ e.name }}</div>
              <div class="qe-desc">{{ e.desc }}</div>
            </div>
            <span class="qe-go"><ic n="next"></ic></span>
          </div>
        </div>
      </div>
      <div class="panel rise" style="--d:600ms">
        <h3>全流程业务闭环 <span class="h3-note">10 步贯通</span></h3>
        <div class="pipe">
          <div v-for="(f, i) in flow" :key="f" class="pipe-node"
               :class="{ last: i === flow.length - 1 }" :style="{ '--i': i }">
            <span class="pipe-dot"></span>
            <span class="pipe-name">{{ f }}</span>
            <span class="pipe-line" v-if="i < flow.length - 1"></span>
          </div>
          <span class="pipe-pulse"></span>
        </div>
        <div class="panel-note">
          系统采用数据层 / 服务层 / 应用层三层架构：Python 科学计算栈承担遥感处理与模型运算，
          FastAPI 提供标准 REST 接口，Vue3 + ECharts 实现多终端可视化，
          与项目计划书中的 SaaS 化产品形态一致。
        </div>
      </div>
    </div>
  </div>`,
};

/* ================= 数据管理 ================= */
const PageData = {
  props: ["meta"],
  setup(props) {
    const selYear = ref(null);
    const chartEl = ref(null);
    const trend = useChart(() => chartEl.value);
    const years = computed(() => (props.meta ? props.meta.dataset.years : []));
    const stats = computed(() => (props.meta ? props.meta.stats : {}));
    const names = computed(() => (props.meta ? props.meta.dataset.classes.map(c => c.name) : []));

    function renderTrend() {
      if (!props.meta) return;
      const ys = years.value;
      const series = names.value.map(n => ({
        name: n, type: "line", stack: "total", areaStyle: { opacity: 0.28 },
        smooth: true, symbolSize: 5,
        lineStyle: { width: 2 },
        color: CLASS_COLORS[n],
        data: ys.map(y => stats.value[y].classes.find(c => c.name === n).area_ha),
      }));
      trend.render({ ...baseChart("各地类面积时序变化 (2000-2020)"),
        xAxis: { type: "category", data: ys, axisLabel: CHART_TEXT },
        yAxis: { type: "value", name: "公顷", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT, splitLine: { lineStyle: { color: "rgba(90,105,92,.16)" } } },
        series });
    }
    nextTick(renderTrend);

    /* ---------- 三种查看方式：专题图（时间轴）/ 两期对比 / 交互地图 ---------- */
    const view = ref("sheet");
    const IMG_SCALE = 3;                       // 原始栅格 256²，放大 3 倍后 816×990，投影不糊
    const imgUrl = (y) => `/api/map/landuse/${y}?scale=${IMG_SCALE}`;          // 专题图（带图名/图例）
    const mapUrl = (y) => `/api/map/landuse/${y}?scale=${IMG_SCALE}&plain=1`;  // 地图叠加：无留白，与坐标严格对齐
    const ready = ref({});                     // 预取完成标记：播放时不闪白
    const curStats = computed(() => (selYear.value && stats.value[selYear.value]) || null);

    /* ---------- 时间轴播放 ---------- */
    const playing = ref(false);
    const speed = ref(900);
    let timer = null;
    function prefetch() {
      years.value.forEach(y => {
        if (ready.value[y]) return;
        const im = new Image();
        im.onload = () => { ready.value = { ...ready.value, [y]: true }; };
        im.src = imgUrl(y);
      });
    }
    function stop() { playing.value = false; if (timer) { clearInterval(timer); timer = null; } }
    function play() {
      if (playing.value) { stop(); return; }
      playing.value = true;
      timer = setInterval(() => {
        const ys = years.value;
        const i = ys.indexOf(selYear.value);
        selYear.value = ys[(i + 1) % ys.length];
      }, speed.value);
    }
    function step(d) {
      const ys = years.value;
      const i = ys.indexOf(selYear.value);
      selYear.value = ys[Math.min(ys.length - 1, Math.max(0, i + d))];
    }
    function setSpeed(v) { speed.value = v; if (playing.value) { stop(); play(); } }

    /* ---------- 两期对比滑块 ---------- */
    const cmpA = ref(null), cmpB = ref(null);
    const cmpMode = ref("swipe");               // swipe | a | b | diff
    const pos = ref(50);
    const cmpEl = ref(null);
    let dragging = false;
    function moveTo(clientX) {
      const el = cmpEl.value;
      if (!el) return;
      const r = el.getBoundingClientRect();
      pos.value = Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100));
    }
    function startDrag(e) {
      if (cmpMode.value !== "swipe") return;
      dragging = true;
      moveTo(e.clientX);
      window.addEventListener("pointermove", onDrag);
      window.addEventListener("pointerup", endDrag);
    }
    function onDrag(e) { if (dragging) moveTo(e.clientX); }
    function endDrag() {
      dragging = false;
      window.removeEventListener("pointermove", onDrag);
      window.removeEventListener("pointerup", endDrag);
    }
    function nudge(d) { pos.value = Math.min(100, Math.max(0, pos.value + d)); }

    /* ---------- 交互地图（Leaflet，CRS.Simple：UTM 米制坐标直接当平面坐标） ---------- */
    const mapEl = ref(null), mapYear = ref(null), opacity = ref(90);
    const layers = reactive({ shade: true, land: true });
    const pick = ref(null);
    const mapBoundsText = ref("");
    let map = null, shadeLayer = null, landLayer = null;
    const ext = computed(() => (props.meta ? props.meta.dataset.extent : null));
    function rgbCss(c) { return Array.isArray(c) ? `rgb(${c[0]},${c[1]},${c[2]})` : "#888"; }
    function initMap() {
      if (!mapEl.value || !props.meta) return;
      if (map) {
        // 页签切走时 .map-canvas 被 v-if 销毁，切回来是全新节点：旧实例挂在游离节点上会让地图永远空白
        const sameNode = map.getContainer() === mapEl.value && map.getContainer().isConnected;
        if (sameNode) return;
        map.remove(); map = null; shadeLayer = landLayer = null;
      }
      const e = props.meta.dataset.extent;
      const b = [[e.ymin, e.xmin], [e.ymax, e.xmax]];
      map = L.map(mapEl.value, { crs: L.CRS.Simple, minZoom: -6, maxZoom: -3.25, zoomSnap: 0.25,
                                 attributionControl: false, zoomControl: false });
      map.fitBounds(b);
      shadeLayer = L.imageOverlay("/api/map/hillshade?scale=3", b, { opacity: 1 });
      landLayer = L.imageOverlay(mapUrl(mapYear.value), b, { opacity: opacity.value / 100 });
      if (layers.shade) shadeLayer.addTo(map);
      if (layers.land) landLayer.addTo(map);
      L.rectangle(b, { color: "#5a6b7a", weight: 1, dashArray: "4 3", fill: false }).addTo(map);  // 图幅范围
      // 比例尺放左上：窗口最大化时悬浮 Dock 会挡住地图底部
      L.control.scale({ imperial: false, position: "topleft" }).addTo(map);   // 单位就是米，比例尺准确
      map.on("click", onMapClick);
      mapBoundsText.value = `${e.xmin}–${e.xmax} × ${e.ymin}–${e.ymax} m`;
    }
    async function onMapClick(ev) {
      try {
        const r = await api(`/map/pick?x=${ev.latlng.lng.toFixed(1)}&y=${ev.latlng.lat.toFixed(1)}&year=${mapYear.value}`);
        pick.value = r;
      } catch (err) { toast(err.message, "err"); }
    }
    function zoomBy(d) { if (map) map.setZoom(map.getZoom() + d); }
    function resetView() {
      if (!map || !ext.value) return;
      const e = ext.value;
      map.fitBounds([[e.ymin, e.xmin], [e.ymax, e.xmax]]);
    }
    watch([mapYear, opacity], () => {
      if (!map) return;
      if (landLayer) { landLayer.setUrl(mapUrl(mapYear.value)); landLayer.setOpacity(opacity.value / 100); }
    });
    watch(layers, () => {
      if (!map) return;
      if (layers.shade) { if (!map.hasLayer(shadeLayer)) shadeLayer.addTo(map); }
      else if (map.hasLayer(shadeLayer)) map.removeLayer(shadeLayer);
      if (layers.land) { if (!map.hasLayer(landLayer)) landLayer.addTo(map); }
      else if (map.hasLayer(landLayer)) map.removeLayer(landLayer);
    }, { deep: true });
    watch(view, (v) => {
      if (v !== "map") return;
      nextTick(() => { initMap(); if (map) setTimeout(() => { map.invalidateSize(); resetView(); }, 120); });
    });

    function initYears() {
      const ys = years.value;
      if (!ys.length) return;
      selYear.value = ys[ys.length - 1];
      if (!cmpA.value) cmpA.value = ys[0];
      if (!cmpB.value) cmpB.value = ys[ys.length - 1];
      mapYear.value = ys[ys.length - 1];
      ready.value = {};
      prefetch();
    }
    onMounted(() => { initYears(); });
    watch(() => props.meta, () => {          // 切矿区数据库：数字、图、地图全部重建
      initYears();
      nextTick(renderTrend);
      if (map) { map.remove(); map = null; }
      if (view.value === "map") nextTick(() => { initMap(); if (map) setTimeout(() => { map.invalidateSize(); resetView(); }, 120); });
    });
    onUnmounted(() => { stop(); if (map) { map.remove(); map = null; } });

    return { selYear, chartEl, years, stats, names, fmt, CLASS_COLORS, curStats,
             view, imgUrl, ready, playing, speed, play, stop, step, setSpeed,
             cmpA, cmpB, cmpMode, pos, cmpEl, startDrag, nudge,
             mapEl, mapYear, opacity, layers, pick, rgbCss, zoomBy, resetView, mapBoundsText, mapUrl };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="database"></ic>数据管理</div>
    <div class="page-desc">{{ meta.dataset.short_name || meta.dataset.region }} · {{ meta.dataset.crs }} · {{ meta.dataset.note }}</div>

    <div class="grid cols-2">
      <div class="panel">
        <h3>时序面积统计</h3>
        <div ref="chartEl" class="chart" style="height:320px;"></div>
      </div>
      <div class="panel">
        <h3>数据集明细</h3>
        <table class="data">
          <thead><tr><th>年份</th><th class="num">总面积(ha)</th>
            <th class="num" v-for="n in names">{{ n }}</th></tr></thead>
          <tbody>
            <tr v-for="y in years" :key="y" @click="selYear = y; view = 'sheet'" style="cursor:pointer"
                :style="{background: selYear===y ? 'var(--green-t)' : ''}">
              <td><strong>{{ y }}</strong></td>
              <td class="num">{{ fmt(stats[y].total_ha) }}</td>
              <td class="num" v-for="n in names" :key="n">
                <span :style="{color: CLASS_COLORS[n]}">{{ fmt(stats[y].classes.find(c=>c.name===n).area_ha) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <h3>土地利用图
        <span class="seg seg-sm" style="margin-left:12px;">
          <button :class="{on: view==='sheet'}" @click="view='sheet'">专题图 · 时间轴</button>
          <button :class="{on: view==='compare'}" @click="view='compare'">两期对比</button>
          <button :class="{on: view==='map'}" @click="view='map'">交互地图</button>
        </span>
      </h3>

      <div v-if="view==='sheet'">
        <div class="tl-stage">
          <img v-for="y in years" :key="y" class="tl-img" :class="{ show: y === selYear }"
               :src="imgUrl(y)" :alt="y + ' 年土地利用图'">
          <div class="tl-year">{{ selYear }}</div>
          <div class="tl-loading" v-if="selYear && !ready[selYear]">正在渲染 {{ selYear }} 年…</div>
        </div>
        <div class="tl-bar">
          <button class="tl-play" @click="play" :title="playing ? '暂停' : '播放'">
            <ic :n="playing ? 'winmin' : 'play'"></ic>
          </button>
          <div class="tl-ticks">
            <button v-for="y in years" :key="y" class="tl-tick" :class="{ on: y === selYear }"
                    @click="stop(); selYear = y">{{ y }}</button>
          </div>
          <span class="seg seg-sm">
            <button v-for="s in [500, 900, 1600]" :key="s" :class="{on: speed === s}"
                    @click="setSpeed(s)">{{ s === 500 ? '快' : (s === 900 ? '中' : '慢') }}</button>
          </span>
        </div>
        <div class="tl-chips" v-if="curStats">
          <span v-for="c in curStats.classes" :key="c.id" class="tl-chip">
            <i :style="{background: rgbCss(c.color)}"></i>{{ c.name }}
            <b>{{ fmt(c.area_ha) }}</b><em>{{ c.percent }}%</em>
          </span>
          <span class="tl-chip total">合计 <b>{{ fmt(curStats.total_ha) }}</b> 公顷</span>
        </div>
      </div>

      <div v-else-if="view==='compare'">
        <div class="cmp-tools">
          <label>A 期</label>
          <select v-model="cmpA"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select>
          <label>B 期</label>
          <select v-model="cmpB"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select>
          <span class="seg seg-sm" style="margin-left:auto;">
            <button :class="{on: cmpMode==='swipe'}" @click="cmpMode='swipe'">滑动对比</button>
            <button :class="{on: cmpMode==='a'}" @click="cmpMode='a'">只看 A</button>
            <button :class="{on: cmpMode==='b'}" @click="cmpMode='b'">只看 B</button>
            <button :class="{on: cmpMode==='diff'}" @click="cmpMode='diff'">差异</button>
          </span>
        </div>

        <div class="cmp-wrap" ref="cmpEl" :class="{ dragging: cmpMode==='swipe' }" @pointerdown="startDrag">
          <img class="cmp-img" :src="imgUrl(cmpB)" alt="B 期">
          <div v-if="cmpMode==='swipe'" class="cmp-top" :style="{ clipPath: 'inset(0 ' + (100 - pos) + '% 0 0)' }">
            <img class="cmp-img" :src="imgUrl(cmpA)" alt="A 期">
          </div>
          <div v-if="cmpMode==='diff'" class="cmp-diff">
            <img class="cmp-img" :src="imgUrl(cmpA)" alt="A 期">
            <img class="cmp-img cmp-blend" :src="imgUrl(cmpB)" alt="B 期">
          </div>
          <template v-if="cmpMode==='swipe'">
            <div class="cmp-handle" :style="{ left: pos + '%' }" tabindex="0"
                 @keydown.left.prevent="nudge(-2)" @keydown.right.prevent="nudge(2)"
                 @dblclick="pos = 50" title="拖动对比 · ←→ 微调 · 双击回中">
              <span class="cmp-knob"><ic n="prev"></ic><ic n="next"></ic></span>
            </div>
            <span class="cmp-tag left">{{ cmpA }} 年</span>
            <span class="cmp-tag right">{{ cmpB }} 年</span>
          </template>
          <span class="cmp-hint" v-if="cmpMode==='diff'">暗色＝两期一致 · 亮色＝发生变化</span>
        </div>
        <div class="tip-line" style="margin-top:8px;">
          {{ cmpMode === 'diff' ? '差异视图由两期专题图叠差生成，用于快速定位变化位置；定量结论请看「变化分析」的转移矩阵。'
                                : '拖动中间分割线比较两期（←→ 微调，双击回中）。' }}
        </div>
      </div>

      <div v-else class="map-shell">
        <div class="map-tools">
          <label class="map-chk"><input type="checkbox" v-model="layers.shade"> 山体阴影</label>
          <label class="map-chk"><input type="checkbox" v-model="layers.land"> 土地利用</label>
          <select v-model="mapYear"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select>
          <label class="map-op">不透明度
            <input type="range" min="20" max="100" v-model.number="opacity"></label>
          <span class="map-zoom">
            <button @click="zoomBy(1)" title="放大">＋</button>
            <button @click="zoomBy(-1)" title="缩小">－</button>
            <button @click="resetView" title="回到全图">全图</button>
          </span>
        </div>
        <div class="map-legend">
          <span v-for="c in meta.dataset.classes" :key="c.id" class="lg-item">
            <i class="lg-dot" :style="{ background: c.color }"></i>{{ c.name }}</span>
        </div>
        <div class="map-canvas" ref="mapEl"></div>
        <div class="map-readout">
          <template v-if="pick">
            <template v-if="pick.inside">
              <span class="mr-swatch" :style="{ background: rgbCss(pick.color) }"></span>
              <b>{{ pick.class }}</b>
              <span>{{ pick.year }} 年 · 该地类 {{ fmt(pick.class_area_ha) }} 公顷（占 {{ pick.class_percent }}%）</span>
              <span class="mr-xy">{{ pick.x }}, {{ pick.y }} m</span>
            </template>
            <span v-else>点在图幅外 · {{ pick.x }}, {{ pick.y }} m</span>
          </template>
          <span v-else>在地图上单击任意位置，查询该点地类</span>
          <span class="mr-hint">{{ mapBoundsText }}</span>
        </div>
      </div>
    </div>
  </div>`,
};

/* ================= 数据来源选择器（各模块共用：数据库 / 上传 / 个人文件） ================= */
const SourcePicker = {
  props: {
    modelValue: { type: Object, default: () => ({ kind: "db" }) },
    label: { type: String, default: "数据来源" },
    hint: { type: String, default: "" },
    neutral: { type: String, default: "使用当前所选矿区数据库的数据" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const open = ref(false), busy = ref(false);
    const list = ref([]), folder = ref("/"), q = ref("");
    const isDb = computed(() => (props.modelValue || {}).kind !== "file");
    const filtered = computed(() => list.value.filter(f => {
      const e = (f.name.split(".").pop() || "").toLowerCase();
      return (f.is_dir || RASTER_EXT.indexOf(e) >= 0)
        && (!q.value || f.name.toLowerCase().includes(q.value.toLowerCase()));
    }));
    async function load() {
      busy.value = true;
      try { list.value = (await api("/files?folder=" + encodeURIComponent(folder.value))).items; }
      catch (e) { toast(e.message, "err"); }
      busy.value = false;
    }
    function toggle() { open.value = !open.value; if (open.value && !list.value.length) load(); }
    function setDb() { open.value = false; emit("update:modelValue", { kind: "db" }); }
    function enter(it) { folder.value = folder.value + it.name + "/"; load(); }
    function up() { folder.value = folder.value.replace(/[^/]+\/$/, "") || "/"; load(); }
    async function useFile(file) {
      busy.value = true;
      try {
        const d = await api("/image/inspect?file_id=" + file.id);
        emit("update:modelValue", { kind: "file", id: file.id, name: file.name, size: file.size,
                                    roles: d.roles || {}, view: d.kind, alignment: d.alignment });
        open.value = false;
      } catch (e) { toast(e.message, "err"); }
      busy.value = false;
    }
    async function onUpload(e) {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!f) return;
      busy.value = true;
      try {
        const fd = new FormData();
        fd.append("folder", "/");
        fd.append("file", f);
        const r = await apiUpload("/files/upload", fd);
        toast(`已上传：${r.name}（${fmtSize(r.size)}）`);
        await useFile({ id: r.id, name: r.name, size: r.size });
      } catch (err) { toast(err.message, "err"); }
      busy.value = false;
    }
    const info = computed(() => {
      const v = props.modelValue || {};
      if (v.kind !== "file") return "";
      const k = { multispectral: "多波段影像", indexstack: "指数栈", index: "单波段指数",
                  classmap: "地类图", rgb: "真彩色 RGB", unknown: "未识别" }[v.view] || v.view || "";
      const a = { aligned: "与数据库同网格", same_crs: "同投影", need_reproject: "异投影·将重投影",
                  disjoint: "与数据库不相交" }[(v.alignment || {}).level] || "";
      return [k, a].filter(Boolean).join(" · ");
    });
    return { open, busy, list, folder, q, isDb, filtered, toggle, setDb, enter, up, useFile, onUpload,
             info, crumbs: computed(() => folder.value.split("/").filter(Boolean)),
             fmtSize, RASTER_EXT };
  },
  template: `
  <div class="field">
    <label>{{ label }}</label>
    <div class="src-row">
      <button class="src-btn" :class="{ on: isDb }" @click="setDb"><ic n="database"></ic>数据库</button>
      <label class="src-btn" :class="{ on: !isDb }" style="cursor:pointer;">
        <ic n="upload"></ic>上传<input type="file" accept=".tif,.tiff,.img,.vrt,.png,.jpg,.jpeg,.bmp"
          style="display:none;" @change="onUpload"></label>
      <button class="src-btn" :class="{ on: !isDb && open }" @click="toggle"><ic n="folder"></ic>个人文件</button>
    </div>

    <div v-if="isDb" class="tip-line">{{ neutral }}</div>
    <div v-else class="src-file">
      <ic n="image"></ic>
      <span class="nm" :title="modelValue.name">{{ modelValue.name }}</span>
      <span class="meta">{{ info }}</span>
      <button class="src-x" title="改回数据库" @click="setDb"><ic n="winclose"></ic></button>
    </div>

    <div v-if="open" style="margin-top:8px;">
      <div style="display:flex; gap:6px; align-items:center; margin-bottom:6px;">
        <span class="chip" style="cursor:pointer;" @click="load">/{{ crumbs.join("/") }}</span>
        <button v-if="folder !== '/'" class="btn small" @click="up">返回上级</button>
        <span style="flex:1;"></span>
        <input v-model="q" placeholder="搜索…" style="width:96px; font-size:12px; padding:3px 6px;">
      </div>
      <div class="imp-list">
        <div v-for="f in filtered" :key="f.id" class="imp-item" @click="f.is_dir ? enter(f) : useFile(f)">
          <ic :n="f.is_dir ? 'folder' : 'image'"></ic>
          <span class="nm">{{ f.name }}</span>
          <span class="sz">{{ f.is_dir ? "" : fmtSize(f.size) }}</span>
        </div>
        <div v-if="!filtered.length" class="tip-line" style="padding:6px;">{{ busy ? "读取中…" : "该目录没有可用影像" }}</div>
      </div>
    </div>
    <div v-if="hint" class="tip-line" style="margin-top:5px;">{{ hint }}</div>
  </div>`,
};

/* ================= 数据预处理 ================= */
const PagePreprocess = {
  props: ["meta"],
  setup(props) {
    const year = ref(2020);
    const loading = ref(false);
    const result = ref(null);
    const src = ref({ kind: "db" });
    const fromFile = computed(() => src.value.kind === "file");
    async function run() {
      loading.value = true;
      try {
        const body = fromFile.value
          ? { file_id: src.value.id, bands: src.value.roles || {} }
          : { year: year.value };
        result.value = await api("/preprocess", body);
        const q = result.value.quality;
        toast(q.cloud_recall_pct === null
          ? `预处理完成（导入影像）：云区占比 ${q.cloud_detected_pct}%`
          : `预处理完成：云检出率 ${q.cloud_recall_pct}%`);
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    const imgNames = { raw_rgb: "① 原始影像(含云噪)", calibrated_rgb: "② 辐射定标", corrected_rgb: "③ 大气校正", cloud_mask: "云掩膜", clean_rgb: "④ 去云去噪成果", ndvi: "NDVI 指数" };
    return { year, loading, result, run, imgNames, src, fromFile,
             years: computed(() => props.meta ? props.meta.dataset.years : []) };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="funnel"></ic>数据预处理</div>
    <div class="page-desc">Landsat 影像自动化处理链路：辐射定标 → DOS 大气校正 → 云检测与邻域插值填充 → 质量检验</div>

    <div class="panel">
      <div class="grid" style="grid-template-columns: 1fr 1fr; gap:16px; align-items:start;">
        <source-picker v-model="src" label="数据来源" style="margin:0;"
          neutral="使用当前所选矿区数据库该年的模拟影像场景"
          hint="也可上传自己的影像（多波段 GeoTIFF 或 jpg/png）：处理链会作用在您的影像上"></source-picker>
        <div class="row" style="align-items:center;">
          <div class="field" style="margin:0;" v-if="!fromFile"><label>处理期次</label>
            <select v-model="year"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select>
          </div>
          <div class="field" style="margin:0;" v-else><label>输入</label>
            <div class="tip-line" style="padding-top:6px;">导入影像：波段角色已自动识别，可在「图像检测」里查看细节</div>
          </div>
          <button class="btn primary" style="margin-top:18px;" :disabled="loading" @click="run">
            {{ loading ? "处理中…" : "执行预处理" }}</button>
        </div>
      </div>
      <div class="step-flow" style="margin-top:16px;" v-if="result">
        <span class="step-node done">数据获取</span><span class="step-arrow">→</span>
        <template v-for="(s, i) in result.steps" :key="s.id">
          <span class="step-node done">{{ s.name }}</span>
          <span class="step-arrow" v-if="i < result.steps.length-1">→</span>
        </template>
      </div>
    </div>

    <div style="position:relative;">
      <div class="loading-mask" v-if="loading"><div class="spinner"></div><div>正在处理遥感影像…</div></div>

      <div v-if="result">
        <div class="grid cols-4" style="margin-bottom:16px;">
          <div class="stat-card"><div class="label">云区检出率</div>
            <div class="value" v-if="result.quality.cloud_recall_pct !== null">{{ result.quality.cloud_recall_pct }}<span class="unit">%</span></div>
            <div class="value" v-else style="font-size:15px; color:var(--ink-3);">—<span class="unit">无云真值</span></div></div>
          <div class="stat-card"><div class="label">{{ result.quality.cloud_overdetect_pct === null ? "云区占比" : "云过检率" }}</div>
            <div class="value">{{ result.quality.cloud_overdetect_pct === null ? result.quality.cloud_detected_pct : result.quality.cloud_overdetect_pct }}<span class="unit">%</span></div></div>
          <div class="stat-card"><div class="label">数据完备性</div><div class="value">{{ result.quality.completeness_pct }}<span class="unit">%</span></div></div>
          <div class="stat-card"><div class="label">插值轮次</div><div class="value">{{ result.quality.fill_rounds }}</div></div>
        </div>

        <div class="panel">
          <h3>处理成果影像</h3>
          <div class="img-compare">
            <figure v-for="(url, key) in result.images" :key="key">
              <figcaption>{{ imgNames[key] || key }}</figcaption>
              <img class="map-img" :src="url" style="image-rendering:auto;">
            </figure>
          </div>
        </div>

        <div class="panel">
          <h3>各环节质量指标</h3>
          <div class="grid cols-4">
            <div v-for="s in result.steps" :key="s.id">
              <div style="font-weight:600; color:#9fd3f5; margin-bottom:8px;">{{ s.name }}</div>
              <div class="kv" v-for="(v, k) in s.metrics" :key="k"><span class="k">{{ k }}</span><span class="v">{{ v }}</span></div>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="empty-tip panel"><div class="big-ic"><ic n="funnel"></ic></div>选择期次后点击「执行预处理」，演示完整 Landsat 预处理链路</div>
    </div>
  </div>`,
};

/* ================= 分类分析 ================= */
const PageClassify = {
  props: ["meta"],
  setup(props) {
    const year = ref(2020), algorithm = ref("rf"), ratio = ref(35), loading = ref(false), r = ref(null);
    const cmEl = ref(null);
    const cmChart = useChart(() => cmEl.value);
    const src = ref({ kind: "db" });
    const fromFile = computed(() => src.value.kind === "file");
    const years = computed(() => props.meta ? props.meta.dataset.years : []);
    const names = computed(() => props.meta ? props.meta.dataset.classes.map(c => c.name) : []);

    async function run() {
      loading.value = true;
      try {
        r.value = await api("/classify", fromFile.value
          ? { file_id: src.value.id, bands: src.value.roles || {}, year: year.value, use_drivers: true,
              train_ratio: ratio.value / 100 }
          : { year: year.value, algorithm: algorithm.value, train_ratio: ratio.value / 100 });
        toast(`分类完成：总体精度 ${r.value.overall_accuracy}%，Kappa ${r.value.kappa}`);
        cmChart.render({
          ...baseChart("混淆矩阵（行=真实，列=预测）"),
          tooltip: { position: "top", backgroundColor: "rgba(255,255,252,.97)", textStyle: { color: "#33453a" } },
          grid: { left: 80, right: 20, top: 46, bottom: 76 },
          xAxis: { type: "category", data: names.value, axisLabel: { ...CHART_TEXT, rotate: 28 }, splitArea: { show: true } },
          yAxis: { type: "category", data: names.value, axisLabel: CHART_TEXT, splitArea: { show: true } },
          visualMap: { min: 0, max: Math.max(...r.value.confusion_matrix.flat()), calculable: false, orient: "horizontal", left: "center", bottom: 2, textStyle: CHART_TEXT, inRange: { color: PAL.heatA }, itemHeight: 60 },
          series: [{ type: "heatmap", data: r.value.confusion_matrix.flatMap((row, i) => row.map((v, j) => [j, i, v])), label: { show: true, color: PAL.heatLabel, fontSize: 10, textBorderColor: PAL.heatLabelBorder, textBorderWidth: 1.2 }, itemStyle: { borderColor: "rgba(10,22,40,.6)", borderWidth: 1 } }],
        });
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    return { year, algorithm, ratio, loading, r, run, cmEl, years, src, fromFile,
             algorithms: computed(() => props.meta ? props.meta.algorithms : []), fmt, CLASS_COLORS };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="crosshair"></ic>分类分析</div>
    <div class="page-desc">集成机器学习监督分类：随机森林 / 支持向量机 / K近邻 · 光谱+纹理+地形 18 维特征；
      也可用自己导入的影像分类（标签取自数据库实测地类）</div>

    <div class="panel">
      <source-picker v-model="src" label="数据来源" style="margin-bottom:12px;"
        neutral="使用当前所选矿区数据库该年的模拟影像场景"
        hint="导入影像时：特征取自您的影像波段（+可选数据库驱动因子），训练标签取自数据库该年实测土地利用，统一用随机森林"></source-picker>
      <div class="row" style="align-items:flex-end;">
        <div class="field" style="margin:0;"><label>{{ fromFile ? "训练标签年份（数据库实测地类）" : "分类期次" }}</label>
          <select v-model="year"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select></div>
        <div class="field" style="margin:0;" v-if="!fromFile"><label>算法</label>
          <select v-model="algorithm"><option v-for="a in algorithms" :key="a.id" :value="a.id">{{ a.name }}</option></select></div>
        <div class="field" style="margin:0;" v-else><label>算法</label>
          <div class="tip-line" style="padding-top:8px;">随机森林（导入影像路径）</div></div>
        <div class="grow">
          <div class="slider-row" style="margin:0;">
            <label>训练样本比例</label>
            <input type="range" min="15" max="60" step="5" v-model.number="ratio">
            <span class="val">{{ ratio }}%</span>
          </div>
        </div>
        <button class="btn primary" :disabled="loading" @click="run">{{ loading ? "训练中…" : "开始分类" }}</button>
      </div>
    </div>

    <div style="position:relative;">
      <div class="loading-mask" v-if="loading"><div class="spinner"></div><div>机器学习训练中，请稍候…</div></div>
      <div v-if="r">
        <div class="grid cols-4" style="margin-bottom:16px;">
          <div class="stat-card"><div class="label">总体精度 OA</div><div class="value" style="color:#2d6a45;">{{ r.overall_accuracy }}<span class="unit">%</span></div></div>
          <div class="stat-card"><div class="label">Kappa 系数</div><div class="value" style="color:#2d6a45;">{{ r.kappa }}</div></div>
          <div class="stat-card"><div class="label">训练 / 验证样本</div><div class="value" style="font-size:17px;">{{ r.n_train }}<span class="unit">/ {{ r.n_test }}</span></div></div>
          <div class="stat-card"><div class="label">算法</div><div class="value" style="font-size:15px; font-family:inherit;">{{ r.algorithm_name }}</div></div>
        </div>
        <div class="grid cols-2">
          <div class="panel">
            <h3>分类成果图</h3>
            <img class="map-img" :src="r.map_url" style="image-rendering:auto;">
          </div>
          <div>
            <div class="panel">
              <h3>逐类精度</h3>
              <table class="data">
                <thead><tr><th>地类</th><th class="num">制图精度</th><th class="num">用户精度</th></tr></thead>
                <tbody><tr v-for="pc in r.per_class" :key="pc.id">
                  <td><span :style="{color: CLASS_COLORS[pc.name]}">●</span> {{ pc.name }}</td>
                  <td class="num">{{ pc.producer_acc }}%</td><td class="num">{{ pc.user_acc }}%</td></tr></tbody>
              </table>
            </div>
            <div class="panel"><h3>混淆矩阵</h3><div ref="cmEl" class="chart" style="height:270px;"></div></div>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="empty-tip panel"><div class="big-ic"><ic n="crosshair"></ic></div>选择期次与算法后点击「开始分类」</div>
    </div>
  </div>`,
};

/* ================= 变化分析 ================= */
const PageChange = {
  props: ["meta"],
  setup(props) {
    const a = ref(2000), b = ref(2020), loading = ref(false), r = ref(null);
    const matrixEl = ref(null), dynEl = ref(null);
    const matrixChart = useChart(() => matrixEl.value);
    const dynChart = useChart(() => dynEl.value);
    const srcA = ref({ kind: "db" }), srcB = ref({ kind: "db" });
    const anyFile = computed(() => srcA.value.kind === "file" || srcB.value.kind === "file");
    const years = computed(() => props.meta ? props.meta.dataset.years : []);
    const names = computed(() => props.meta ? props.meta.dataset.classes.map(c => c.name) : []);

    async function run() {
      loading.value = true;
      try {
        const body = anyFile.value
          ? { file_a: srcA.value.kind === "file" ? srcA.value.id : null,
              file_b: srcB.value.kind === "file" ? srcB.value.id : null,
              a_year: a.value, b_year: b.value }
          : { a_year: a.value, b_year: b.value };
        r.value = await api("/change", body);
        toast(`变化分析完成：${r.value.changed_percent}% 像元发生变化`);
        const m = r.value.prob_matrix;
        matrixChart.render({
          ...baseChart("土地利用转移概率矩阵"),
          tooltip: { position: "top", backgroundColor: "rgba(255,255,252,.97)", textStyle: { color: "#33453a" },
            formatter: p => names.value[p.value[1]] + " → " + names.value[p.value[0]] + ": " + (p.value[2] * 100).toFixed(2) + "%" },
          grid: { left: 80, right: 20, top: 46, bottom: 76 },
          xAxis: { type: "category", data: names.value, name: "→ 转入", nameTextStyle: CHART_TEXT, axisLabel: { ...CHART_TEXT, rotate: 28 }, splitArea: { show: true } },
          yAxis: { type: "category", data: names.value, name: "转出 ↓", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT, splitArea: { show: true } },
          visualMap: { min: 0, max: 1, calculable: false, orient: "horizontal", left: "center", bottom: 2, textStyle: CHART_TEXT, inRange: { color: PAL.heatB }, itemHeight: 60 },
          series: [{ type: "heatmap",
            // 基准期无像元的地类其概率无定义（后端返回 null），不入图，留空更诚实
            data: m.flatMap((row, i) => row.map((v, j) => [j, i, v]).filter(d => d[2] !== null && d[2] !== undefined)),
            label: { show: true, color: PAL.heatLabel, fontSize: 9.5, textBorderColor: PAL.heatLabelBorder, textBorderWidth: 1.2, formatter: p => (p.value[2] * 100).toFixed(1) + "%" },
            itemStyle: { borderColor: "rgba(10,22,40,.6)", borderWidth: 1 } }],
        });
        dynChart.render({
          ...baseChart("各地类面积变化 (公顷)"),
          grid: { left: 62, right: 26, top: 42, bottom: 52 },
          xAxis: { type: "category", data: names.value, axisLabel: { ...CHART_TEXT, rotate: 22 } },
          yAxis: { type: "value", axisLabel: CHART_TEXT, splitLine: { lineStyle: { color: "rgba(90,105,92,.16)" } } },
          legend: { show: false },
          series: [{ type: "bar", barWidth: 22,
            data: r.value.dynamics.map(d => ({ value: d.change_ha, itemStyle: { color: d.change_ha >= 0 ? "#3d7a52" : "#b3473f", borderRadius: 4 } } )) }],
        });
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    return { a, b, loading, r, run, matrixEl, dynEl, years, fmt, srcA, srcB, anyFile };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="trend"></ic>变化分析</div>
    <div class="page-desc">多期土地利用变化检测：转移矩阵 · 动态度 · 变化热点识别 ·
      也可用自己导入的地类图（像元值 1–6）与数据库某期对比</div>

    <div class="panel">
      <div class="grid" style="grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:12px;">
        <source-picker v-model="srcA" label="前期数据" style="margin:0;"
          neutral="使用数据库所选期次" hint="上传/选择地类图可替代数据库前期"></source-picker>
        <source-picker v-model="srcB" label="后期数据" style="margin:0;"
          neutral="使用数据库所选期次" hint="只导前期时，后期取下方所选数据库年份"></source-picker>
      </div>
      <div class="row" style="align-items:flex-end;">
        <div class="field" style="margin:0;"><label>起始期{{ srcA.kind === 'file' ? '（已用导入影像）' : '' }}</label>
          <select v-model="a" :disabled="srcA.kind === 'file'"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select></div>
        <div class="field" style="margin:0;"><label>{{ srcA.kind === 'file' && srcB.kind === 'file' ? '目标期（已用导入影像）' : '目标期' }}</label>
          <select v-model="b" :disabled="srcB.kind === 'file'"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select></div>
        <button class="btn primary" :disabled="loading || a===b" @click="run">{{ loading ? "分析中…" : "开始分析" }}</button>
      </div>
    </div>

    <div style="position:relative;">
      <div class="loading-mask" v-if="loading"><div class="spinner"></div><div>变化检测分析中…</div></div>
      <div v-if="r">
        <div class="grid cols-4" style="margin-bottom:16px;">
          <div class="stat-card"><div class="label">变化像元</div><div class="value">{{ fmt(r.changed_pixels, 0) }}</div></div>
          <div class="stat-card"><div class="label">变化面积</div><div class="value">{{ fmt(r.changed_pixels*0.09) }}<span class="unit">公顷</span></div></div>
          <div class="stat-card"><div class="label">变化比例</div><div class="value" style="color:#9a7d2e;">{{ r.changed_percent }}<span class="unit">%</span></div></div>
          <div class="stat-card"><div class="label">变化热点</div><div class="value">{{ r.hotspots.length }}<span class="unit">处</span></div></div>
        </div>

        <div class="grid cols-2">
          <div class="panel">
            <h3>变化检测图</h3>
            <img class="map-img" :src="r.map_url" style="image-rendering:auto;">
            <div style="font-size:11.5px; color:var(--muted); margin-top:9px;">红色像元 = 发生地类转换区域；底色为起始期地类淡化显示</div>
          </div>
          <div class="panel"><h3>转移概率矩阵</h3>
            <div ref="matrixEl" class="chart" style="height:340px;"></div>
            <div v-if="r.empty_classes && r.empty_classes.length"
              style="font-size:11.5px; color:var(--ink-3); margin-top:6px;">
              注：{{ r.empty_classes.join("、") }}在 {{ r.a_year }}{{ typeof r.a_year === 'number' ? ' 年' : '' }}无像元，其转出行不构成概率分布，故留空
            </div>
          </div>
        </div>

        <div class="grid cols-2" style="margin-top:16px;">
          <div class="panel">
            <h3>主要转移类型</h3>
            <table class="data">
              <thead><tr><th>转换方向</th><th class="num">面积(ha)</th><th class="num">概率</th></tr></thead>
              <tbody><tr v-for="t in r.transfers" :key="t.from+t.to">
                <td>{{ t.from }} <span style="color:var(--muted)">→</span> {{ t.to }}</td>
                <td class="num">{{ fmt(t.area_ha) }}</td><td class="num">{{ (t.prob*100).toFixed(1) }}%</td></tr></tbody>
            </table>
          </div>
          <div>
            <div class="panel"><h3>各地类面积增减</h3><div ref="dynEl" class="chart" style="height:250px;"></div></div>
            <div class="panel">
              <h3>逐类动态度</h3>
              <table class="data">
                <thead><tr><th>地类</th><th class="num">{{ r.a_year }} (ha)</th><th class="num">{{ r.b_year }} (ha)</th><th class="num">年均变化</th></tr></thead>
                <tbody><tr v-for="d in r.dynamics" :key="d.id">
                  <td>{{ d.name }}</td><td class="num">{{ fmt(d.area_a_ha) }}</td><td class="num">{{ fmt(d.area_b_ha) }}</td>
                  <td class="num" :class="d.annual_rate_pct === null ? '' : (d.annual_rate_pct>=0?'pos':'neg')">
                    <template v-if="d.annual_rate_pct === null">—<span v-if="d.new_in_period" style="color:var(--ink-3); font-size:11px;">（本期新增）</span></template>
                    <template v-else>{{ d.annual_rate_pct }}%</template></td></tr></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="empty-tip panel"><div class="big-ic"><ic n="trend"></ic></div>选择两期数据后点击「开始分析」</div>
    </div>
  </div>`,
};

/* ================= 预测建模 ================= */
const PagePredict = {
  props: ["meta"],
  setup(props) {
    const tab = ref("single");
    const years = computed(() => props.meta ? props.meta.dataset.years : []);
    const names = computed(() => props.meta ? props.meta.dataset.classes.map(c => c.name) : []);

    /* --- 单情景 --- */
    const model = ref("ca-markov");
    const scenario = ref("natural");
    const aYear = ref(2000), bYear = ref(2020), targetYear = ref(2030);
    const params = reactive({});
    const loading = ref(false), r = ref(null);
    const trendEl = ref(null), matrixEl = ref(null);
    const trendChart = useChart(() => trendEl.value);
    const matrixChart = useChart(() => matrixEl.value);
    const paramLabels = computed(() => props.meta ? props.meta.param_labels : []);
    const scenarios = computed(() => props.meta ? props.meta.scenarios : []);

    function applyScenario(id) {
      scenario.value = id;
      const sc = scenarios.value.find(s => s.id === id);
      if (sc) Object.assign(params, sc.params);
    }
    if (props.meta) applyScenario("natural");

    async function run() {
      loading.value = true;
      try {
        r.value = await api("/predict", { model: model.value, a_year: aYear.value, b_year: bYear.value,
          target_year: targetYear.value, scenario: scenario.value, params: { ...params } });
        toast(`${r.value.model_name} · ${r.value.scenario_name}情景预测完成`);
        drawTrend(r.value);
        nextTick(() => {
          const c = document.querySelector('.win-body[data-app="predict"]');
          if (c) c.scrollTo({ top: 0, behavior: "smooth" });
        });
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    function drawTrend(res) {
      const his = res.area_history;
      const baseYear = res.base.b;
      const baseStats = props.meta.stats[baseYear];
      const series = names.value.map(n => ({
        name: n, type: "line", smooth: true, symbolSize: 4,
        color: CLASS_COLORS[n], lineStyle: { width: 2 },
        data: [{ value: baseStats.classes.find(c => c.name === n).area_ha, year: baseYear },
               ...his.map(h => ({ value: h.areas[n], year: h.year }))].map(p => [String(p.year), p.value]),
      }));
      trendChart.render({ ...baseChart(`土地利用面积预测趋势（${res.scenario_name}）`),
        xAxis: { type: "category", axisLabel: CHART_TEXT, boundaryGap: false },
        yAxis: { type: "value", name: "公顷", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT, splitLine: { lineStyle: { color: "rgba(90,105,92,.16)" } } },
        series });
      const P = res.transition_matrix;
      matrixChart.render({
        ...baseChart("情景修正后转移概率矩阵"),
        tooltip: { position: "top", backgroundColor: "rgba(255,255,252,.97)", textStyle: { color: "#33453a" },
          formatter: p => names.value[p.value[1]] + " ← " + names.value[p.value[0]] + ": " + (p.value[2] * 100).toFixed(2) + "%" },
        grid: { left: 80, right: 20, top: 46, bottom: 76 },
        xAxis: { type: "category", data: names.value, name: "→ 转入", nameTextStyle: CHART_TEXT, axisLabel: { ...CHART_TEXT, rotate: 28 }, splitArea: { show: true } },
        yAxis: { type: "category", data: names.value, name: "转出 ↓", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT, splitArea: { show: true } },
        visualMap: { min: 0, max: 1, calculable: false, orient: "horizontal", left: "center", bottom: 2, textStyle: CHART_TEXT, inRange: { color: PAL.heatB }, itemHeight: 60 },
        series: [{ type: "heatmap", data: P.flatMap((row, i) => row.map((v, j) => [j, i, v])),
          label: { show: true, color: PAL.heatLabel, fontSize: 9.5, textBorderColor: PAL.heatLabelBorder, textBorderWidth: 1.2, formatter: p => (p.value[2] * 100).toFixed(1) + "%" },
          itemStyle: { borderColor: "rgba(10,22,40,.6)", borderWidth: 1 } }],
      });
    }

    /* --- 多情景对比 --- */
    const cmpLoading = ref(false), cmp = ref(null);
    const cmpBarEl = ref(null);
    const cmpBarChart = useChart(() => cmpBarEl.value);
    async function runCompare() {
      cmpLoading.value = true;
      try {
        cmp.value = await api("/compare", { a_year: aYear.value, b_year: bYear.value, target_year: targetYear.value });
        toast("四情景对比完成");
        const names2 = cmp.value.scenarios.map(s => s.scenario_name);
        const series = names.value.map(n => ({
          name: n, type: "bar", stack: "x", barWidth: 42, color: CLASS_COLORS[n],
          data: cmp.value.scenarios.map(s => s.final_areas[n] || 0),
        }));
        cmpBarChart.render({ ...baseChart(`${targetYear.value} 年各地类预测面积 · 四情景对比`),
          grid: { left: 62, right: 26, top: 42, bottom: 60 },
          xAxis: { type: "category", data: names2, axisLabel: CHART_TEXT },
          yAxis: { type: "value", name: "公顷", nameTextStyle: CHART_TEXT, axisLabel: CHART_TEXT, splitLine: { lineStyle: { color: "rgba(90,105,92,.16)" } } },
          series });
      } catch (e) { toast(e.message, "err"); }
      cmpLoading.value = false;
    }

    /* --- 精度验证 --- */
    const valA = ref(2000), valB = ref(2005), valTarget = ref(2010);
    const valLoading = ref(false), val = ref(null);
    const valErrEl = ref(null);
    const valErrChart = useChart(() => valErrEl.value);
    const valSrc = ref({ kind: "db" });
    const valFromFile = computed(() => valSrc.value.kind === "file");
    async function runValidate() {
      valLoading.value = true;
      try {
        val.value = await api("/validate", { train_a: valA.value, train_b: valB.value,
          target_year: valTarget.value, scenario: scenario.value,
          file_id: valFromFile.value ? valSrc.value.id : null });
        toast(`精度验证完成：OA ${val.value.overall_accuracy}%，Kappa ${val.value.kappa}`);
        valErrChart.render({ ...baseChart(`${val.value.target_year} 年面积预测误差 (%)`),
          grid: { left: 62, right: 26, top: 42, bottom: 52 },
          xAxis: { type: "category", data: val.value.area_error.map(e => e.name), axisLabel: { ...CHART_TEXT, rotate: 22 } },
          yAxis: { type: "value", axisLabel: CHART_TEXT, splitLine: { lineStyle: { color: "rgba(90,105,92,.16)" } } },
          legend: { show: false },
          series: [{ type: "bar", barWidth: 22, data: val.value.area_error.map(e => ({
            value: e.err_pct, itemStyle: { color: Math.abs(e.err_pct) < 10 ? PAL.pos : PAL.warn, borderRadius: 4 } })) }],
        });
      } catch (e) { toast(e.message, "err"); }
      valLoading.value = false;
    }
    const valTargets = computed(() => (props.meta ? props.meta.dataset.years.filter(y => y > 2005) : []));

    return {
      tab, years, names, model, scenario, aYear, bYear, targetYear, params, loading, r, trendEl, matrixEl,
      applyScenario, run, paramLabels, scenarios,
      cmpLoading, cmp, cmpBarEl, runCompare,
      valA, valB, valTarget, valLoading, val, valErrEl, runValidate, valTargets, valSrc, valFromFile,
      fmt, CLASS_COLORS,
    };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="compass"></ic>预测建模</div>
    <div class="page-desc">改良 CLUE-S + CA-Markov 融合模型 · 多情景土地利用空间格局推演 · 内置精度验证</div>

    <div class="tabs">
      <div class="tab" :class="{active: tab==='single'}" @click="tab='single'">单情景预测</div>
      <div class="tab" :class="{active: tab==='compare'}" @click="tab='compare'">多情景对比</div>
      <div class="tab" :class="{active: tab==='validate'}" @click="tab='validate'">精度验证</div>
    </div>

    <!-- ============ 单情景 ============ -->
    <div v-if="tab==='single'">
      <div class="grid" style="grid-template-columns: 320px 1fr; align-items:start;">
        <div>
          <div class="panel">
            <h3>模型与基准期</h3>
            <div class="field"><label>预测模型</label>
              <select v-model="model">
                <option value="ca-markov">CA-Markov 融合模型（含 CA 空间分配）</option>
                <option value="clues">CLUE-S 模型（适宜性分配）</option>
              </select></div>
            <div class="tip-line" style="margin:2px 0 9px;">
              本页需要数据库的多期土地利用序列与驱动因子（模型基建于时序转移与地形/距离因子），
              因此只接数据库数据；要用自己的影像请到「图像检测」，
              要用自己的实测地类做验证请在「精度验证」页签上传真值。</div>
            <div class="field"><label>训练期起止</label>
              <div class="row" style="gap:8px;">
                <select v-model="aYear" style="flex:1;"><option v-for="y in years.filter(y=>y<bYear)" :key="y" :value="y">{{ y }}</option></select>
                <span style="color:var(--muted)">→</span>
                <select v-model="bYear" style="flex:1;"><option v-for="y in years.filter(y=>y>aYear)" :key="y" :value="y">{{ y }}</option></select>
              </div></div>
            <div class="field"><label>预测目标年份</label>
              <input type="number" v-model.number="targetYear" min="2021" max="2060"></div>
          </div>

          <div class="panel">
            <h3>预测情景</h3>
            <div style="display:grid; gap:10px;">
              <div v-for="s in scenarios" :key="s.id" class="scenario-card" :class="{active: scenario===s.id}" @click="applyScenario(s.id)">
                <div class="s-name">{{ s.name }}</div><div class="s-desc">{{ s.desc }}</div>
              </div>
            </div>
          </div>

          <div class="panel">
            <h3>情景参数微调（12 项）</h3>
            <div style="max-height:330px; overflow-y:auto; padding-right:4px;">
              <div v-for="p in paramLabels" :key="p.key" :title="p.desc">
                <div class="slider-row">
                  <label>{{ p.label }}</label>
                  <input type="range" min="0" max="100" :value="Math.round((params[p.key]||0)*100)"
                    @input="params[p.key] = $event.target.value/100">
                  <span class="val">{{ Math.round((params[p.key]||0)*100) }}%</span>
                </div>
              </div>
            </div>
            <button class="btn primary" style="width:100%; margin-top:8px;" :disabled="loading" @click="run">
              {{ loading ? "预测运算中…" : "开始预测" }}</button>
          </div>
        </div>

        <div style="position:relative;">
          <div class="loading-mask" v-if="loading"><div class="spinner"></div><div>CA-Markov / CLUE-S 模型运算中…</div></div>
          <div v-if="r">
            <div class="grid cols-3" style="margin-bottom:16px;">
              <div class="stat-card"><div class="label">预测模型</div><div class="value" style="font-size:15px; font-family:inherit;">{{ r.model_name }}</div></div>
              <div class="stat-card"><div class="label">情景</div><div class="value" style="font-size:15px; font-family:inherit;">{{ r.scenario_name }}</div></div>
              <div class="stat-card"><div class="label">预测目标</div><div class="value">{{ r.final_year }}<span class="unit">年</span></div></div>
            </div>
            <div class="panel"><h3>预测成果图（{{ r.final_year }} 年）</h3>
              <img v-for="(url, key) in r.images" :key="key" class="map-img" :src="url"
                   style="image-rendering:auto; max-width:560px; margin:0 auto 12px;"></div>
            <div class="panel"><div ref="trendEl" class="chart" style="height:330px;"></div></div>
            <div class="panel"><div ref="matrixEl" class="chart" style="height:360px;"></div></div>
            <div class="panel" v-if="r.suitability_models && Object.keys(r.suitability_models).length">
              <h3>CLUE-S 驱动因子回归系数（真实标定）</h3>
              <table class="data">
                <thead><tr><th>地类</th><th class="num">高程</th><th class="num">坡度</th><th class="num">距道路</th><th class="num">距水域</th><th class="num">距矿距离</th><th class="num">样本数</th></tr></thead>
                <tbody><tr v-for="(m, name) in r.suitability_models" :key="name">
                  <td>{{ name }}</td>
                  <td class="num" v-for="(c, i) in m.coef" :key="i" :class="{pos: c>0, neg: c<0}">{{ c }}</td>
                  <td class="num">{{ m.n_pos }}/{{ m.n_neg }}</td></tr></tbody>
              </table>
            </div>
          </div>
          <div v-else-if="!loading" class="empty-tip panel"><div class="big-ic"><ic n="compass"></ic></div>选择情景与参数后点击「开始预测」<br>模型将以两期真实土地利用数据标定转移矩阵与驱动因子</div>
        </div>
      </div>
    </div>

    <!-- ============ 多情景对比 ============ -->
    <div v-if="tab==='compare'" style="position:relative;">
      <div class="loading-mask" v-if="cmpLoading"><div class="spinner"></div><div>四情景并行推演中…</div></div>
      <div class="panel">
        <div class="row" style="align-items:flex-end;">
          <div class="field" style="margin:0;"><label>训练期 {{ aYear }} → {{ bYear }} · 对比目标年</label>
            <input type="number" v-model.number="targetYear" min="2021" max="2060"></div>
          <button class="btn primary" :disabled="cmpLoading" @click="runCompare">{{ cmpLoading ? "推演中…" : "四情景对比" }}</button>
        </div>
      </div>
      <div v-if="cmp">
        <div class="grid cols-4" style="margin-bottom:16px;">
          <div v-for="s in cmp.scenarios" :key="s.scenario" class="stat-card">
            <div class="label">{{ s.scenario_name }}</div>
            <div class="value" style="font-size:16px; font-family:inherit;">采矿 {{ fmt(s.final_areas['采矿用地']) }}<span class="unit">ha</span></div>
            <div style="font-size:11.5px; color:var(--muted); margin-top:4px;">林地 {{ fmt(s.final_areas['林地']) }} ha · 耕地 {{ fmt(s.final_areas['耕地']) }} ha</div>
          </div>
        </div>
        <div class="panel"><div ref="cmpBarEl" class="chart" style="height:340px;"></div></div>
        <div class="panel">
          <h3>各情景预测格局图（{{ cmp.target_year }} 年）</h3>
          <div class="img-compare" style="grid-template-columns: repeat(4, 1fr);">
            <figure v-for="s in cmp.scenarios" :key="s.scenario">
              <figcaption>{{ s.scenario_name }}</figcaption>
              <img class="map-img" :src="s.image" style="image-rendering:auto;">
            </figure>
          </div>
        </div>
      </div>
      <div v-else-if="!cmpLoading" class="empty-tip panel"><div class="big-ic"><ic n="scale"></ic></div>点击「四情景对比」，一次推演 常规开采 / 强化开采 / 生态优先 / 综合平衡 四种发展路径</div>
    </div>

    <!-- ============ 精度验证 ============ -->
    <div v-if="tab==='validate'" style="position:relative;">
      <div class="loading-mask" v-if="valLoading"><div class="spinner"></div><div>独立验证运算中…</div></div>
      <div class="panel">
        <source-picker v-model="valSrc" label="实测真值来源" style="margin-bottom:12px;"
          neutral="使用数据库该年的实测土地利用作真值"
          hint="也可上传自己的实测地类图（像元值 1–6、与数据库同网格或可重投影）作真值，用模型预测该年再与您的实测对比"></source-picker>
        <div class="row" style="align-items:flex-end;">
          <div class="field" style="margin:0;"><label>训练期</label>
            <div class="row" style="gap:8px;">
              <select v-model="valA" style="flex:1;"><option v-for="y in years.filter(y=>y<valB)" :key="y" :value="y">{{ y }}</option></select>
              <span style="color:var(--muted)">→</span>
              <select v-model="valB" style="flex:1;"><option v-for="y in years.filter(y=>y>valA)" :key="y" :value="y">{{ y }}</option></select>
            </div></div>
          <div class="field" style="margin:0;"><label>验证目标年{{ valFromFile ? "（已用导入真值）" : "（有实测数据）" }}</label>
            <select v-model="valTarget"><option v-for="y in valTargets" :key="y" :value="y">{{ y }} 年</option></select></div>
          <button class="btn primary" :disabled="valLoading" @click="runValidate">{{ valLoading ? "验证中…" : "运行验证" }}</button>
        </div>
      </div>
      <div v-if="val">
        <div class="grid cols-4" style="margin-bottom:16px;">
          <div class="stat-card"><div class="label">总体精度 OA</div><div class="value" style="color:#2d6a45;">{{ val.overall_accuracy }}<span class="unit">%</span></div></div>
          <div class="stat-card"><div class="label">Kappa 系数</div><div class="value" style="color:#2d6a45;">{{ val.kappa }}</div></div>
          <div class="stat-card"><div class="label">训练期</div><div class="value" style="font-size:17px;">{{ val.train.a }}-{{ val.train.b }}</div></div>
          <div class="stat-card"><div class="label">验证目标</div><div class="value" style="font-size:17px;">{{ val.target_year }} 年实测</div></div>
        </div>
        <div class="grid cols-2">
          <div class="panel">
            <h3>预测 vs 实测</h3>
            <div class="img-compare">
              <figure><figcaption>{{ val.target_year }} 年预测格局</figcaption><img class="map-img" :src="val.images.predicted" style="image-rendering:auto;"></figure>
              <figure><figcaption>{{ val.target_year }} 年实测格局</figcaption><img class="map-img" :src="val.images.truth" style="image-rendering:auto;"></figure>
            </div>
          </div>
          <div>
            <div class="panel"><div ref="valErrEl" class="chart" style="height:250px;"></div></div>
            <div class="panel">
              <h3>逐类面积误差检验</h3>
              <table class="data">
                <thead><tr><th>地类</th><th class="num">实测(ha)</th><th class="num">预测(ha)</th><th class="num">误差</th></tr></thead>
                <tbody><tr v-for="e in val.area_error" :key="e.name">
                  <td>{{ e.name }}</td><td class="num">{{ fmt(e.true_ha) }}</td><td class="num">{{ fmt(e.pred_ha) }}</td>
                  <td class="num" :class="Math.abs(e.err_pct)<10?'pos':'neg'">{{ e.err_pct }}%</td></tr></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="!valLoading" class="empty-tip panel"><div class="big-ic"><ic n="check"></ic></div>模型用历史数据训练、独立预测有实测数据的年份并对比 —— 这就是 Kappa 精度的来源</div>
    </div>
  </div>`,
};

/* ================= 报告生成 ================= */
const PageReport = {
  props: ["meta"],
  setup(props) {
    const template = ref("comprehensive");
    const aYear = ref(2000), bYear = ref(2020), targetYear = ref(2030), scenario = ref("natural");
    const fmt = ref("docx");
    const loading = ref(false), result = ref(null);
    const history = ref([]);
    const years = computed(() => props.meta ? props.meta.dataset.years : []);

    async function loadHistory() {
      try { history.value = (await api("/report/list")).items; } catch (e) { /* 忽略 */ }
    }
    loadHistory();

    async function run() {
      loading.value = true;
      try {
        result.value = await api("/report", { template: template.value, format: fmt.value,
          options: { a_year: aYear.value, b_year: bYear.value, target_year: targetYear.value, scenario: scenario.value } });
        toast(fmt.value === "pdf" ? "PDF 报告已生成" : "Word 报告已生成");
        loadHistory();
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    async function del(fn) {
      if (!confirm(`确认删除报告「${fn}」？`)) return;
      try {
        await api("/report/delete", { filename: fn });
        loadHistory();
        toast("已删除");
      } catch (e) { toast(e.message, "err"); }
    }
    return { template, aYear, bYear, targetYear, scenario, fmt, loading, result, history, run, del, years,
      templates: computed(() => props.meta ? props.meta.templates : []),
      scenarios: computed(() => props.meta ? props.meta.scenarios : []) };
  },
  template: `
  <div v-if="meta">
    <div class="page-title"><ic n="report"></ic>报告生成</div>
    <div class="page-desc">自动整合分类成果、变化分析、多情景预测与精度验证，一键导出 Word / PDF 标准报告</div>

    <div class="panel">
      <h3>选择报告模板（八类行业标准）</h3>
      <div class="grid cols-4" style="gap:11px;">
        <div v-for="t in templates" :key="t.id" class="scenario-card" :class="{active: template===t.id}" @click="template=t.id">
          <div class="s-name" style="font-size:12.5px;">{{ t.name }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>报告参数</h3>
      <div class="row" style="align-items:flex-end; flex-wrap:wrap;">
        <div class="field" style="margin:0;"><label>变化分析区间</label>
          <div class="row" style="gap:8px;">
            <select v-model="aYear" style="flex:1;"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select>
            <span style="color:var(--ink-3)">→</span>
            <select v-model="bYear" style="flex:1;"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select>
          </div></div>
        <div class="field" style="margin:0;"><label>预测目标年</label>
          <input type="number" v-model.number="targetYear" min="2021" max="2060" style="width:110px;"></div>
        <div class="field" style="margin:0;"><label>预测情景</label>
          <select v-model="scenario"><option v-for="s in scenarios" :key="s.id" :value="s.id">{{ s.name }}</option></select></div>
        <div class="field" style="margin:0;"><label>导出格式</label>
          <div class="seg">
            <button :class="{ on: fmt === 'docx' }" @click="fmt = 'docx'">Word</button>
            <button :class="{ on: fmt === 'pdf' }" @click="fmt = 'pdf'">PDF</button>
          </div></div>
        <button class="btn primary" :disabled="loading" @click="run">
          {{ loading ? "生成中…" : "生成 " + (fmt === 'pdf' ? 'PDF' : 'Word') + " 报告" }}</button>
      </div>
    </div>

    <div style="position:relative;">
      <div class="loading-mask" v-if="loading"><div class="spinner"></div><div>正在整合成果、渲染图件、生成报告…</div></div>
      <div v-if="result" class="panel">
        <h3>报告已生成</h3>
        <div class="row" style="align-items:center;">
          <div class="ic" style="font-size:30px; color:var(--green);"><ic n="report"></ic></div>
          <div class="grow">
            <div style="font-weight:600;">{{ result.filename }}</div>
            <div style="font-size:12px; color:var(--ink-2); margin-top:4px;">
              含规范封面、目录、执行摘要、图表题编号、面积趋势图与四情景对比</div>
          </div>
          <a class="btn primary" :href="result.download_url" :download="result.filename">下载 {{ result.format.toUpperCase() }} 报告</a>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>历史报告（{{ history.length }}）</h3>
      <table class="data" v-if="history.length">
        <thead><tr><th>文件名</th><th>格式</th><th class="num">大小</th><th>生成时间</th><th style="width:150px;">操作</th></tr></thead>
        <tbody>
          <tr v-for="h in history" :key="h.filename">
            <td style="max-width:340px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ h.filename }}</td>
            <td><span class="chip" :class="h.format === 'pdf' ? 'orange' : ''">{{ h.format.toUpperCase() }}</span></td>
            <td class="num">{{ h.size_kb }} KB</td>
            <td style="color:var(--ink-2); font-size:12px;">{{ h.time }}</td>
            <td>
              <a class="btn small" :href="'/api/report/download/' + h.filename" :download="h.filename">下载</a>
              <button class="btn small" style="margin-left:5px; color:var(--bad); border-color:var(--bad);" @click="del(h.filename)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else style="color:var(--ink-3); font-size:12.5px; text-align:center; padding:16px 0;">暂无历史报告</div>
    </div>
  </div>`,
};

/* ================= 数据库选择器（可搜索） ================= */
const DsPicker = {
  props: ["datasets", "current"],
  emits: ["pick"],
  setup(props, { emit }) {
    const open = ref(false);
    const q = ref("");
    const list = computed(() => props.datasets || []);
    const cur = computed(() => list.value.find(d => d.id === props.current) || null);
    const filtered = computed(() => {
      const kw = q.value.trim().toLowerCase();
      if (!kw) return list.value;
      const primary = [], secondary = [];
      for (const d of list.value) {
        const nameHay = [d.region, d.id, d.short_name, d.crs,
                         d.years ? d.years.join(" ") : "", d.area_km2].join(" ").toLowerCase();
        if (nameHay.includes(kw)) { primary.push(d); continue; }
        if ((d.note || "").toLowerCase().includes(kw)) secondary.push({ ...d, _noteOnly: true });
      }
      return [...primary, ...secondary];
    });
    function pick(d) {
      if (d.id !== props.current) emit("pick", d.id);
      open.value = false; q.value = "";
    }
    function close() { open.value = false; q.value = ""; }
    function yearsOf(d) {
      if (!d.years || !d.years.length) return "";
      return d.years[0] + "–" + d.years[d.years.length - 1] + " · " + d.years.length + " 期";
    }
    return { open, q, list, cur, filtered, pick, close, yearsOf };
  },
  template: `
  <div class="ds-picker">
    <button class="ds-btn" :class="{ on: open }" @click="open = !open" title="切换矿区数据库">
      <ic n="database"></ic>
      <span class="ds-cur">{{ cur ? (cur.short_name || cur.region) : "选择数据库" }}</span>
      <span class="ds-count">{{ list.length }}</span>
      <span class="ds-chev" :class="{ up: open }"><ic n="chevron"></ic></span>
    </button>

    <div class="ds-backdrop" v-if="open" @pointerdown="close"></div>
    <div class="ds-pop" v-if="open" @pointerdown.stop>
      <div class="ds-search">
        <ic n="search"></ic>
        <input v-model="q" placeholder="搜索矿区 / 编号 / 年份…" autofocus>
        <button class="ds-x" v-if="q" @click="q = ''" title="清空"><ic n="winclose"></ic></button>
      </div>
      <div class="ds-list">
        <div v-for="d in filtered" :key="d.id" class="ds-item"
          :class="{ active: d.id === current }" @click="pick(d)">
          <div class="ds-main">
            <div class="ds-name">{{ d.short_name || d.region }}</div>
            <div class="ds-meta">
              <span v-if="yearsOf(d)">{{ yearsOf(d) }}</span>
              <span v-if="d.area_km2"> · {{ d.area_km2 }} km²</span>
              <span v-if="d.resolution_m"> · {{ d.resolution_m }} m</span>
            </div>
            <div class="ds-note" v-if="d._noteOnly">备注中包含关键词</div>
          </div>
          <span class="ds-check" v-if="d.id === current"><ic n="check"></ic></span>
          <span class="ds-tag" v-else>切换</span>
        </div>
        <div v-if="!filtered.length" class="ds-empty">
          未找到匹配的数据集<br><span>试试输入矿区名称或编号</span>
        </div>
      </div>
      <div class="ds-foot">
        共 {{ list.length }} 个矿区数据库<span v-if="q"> · 匹配 {{ filtered.length }} 个</span>
      </div>
    </div>
  </div>`,
};

/* ================= 系统设置 · 个性化中心 ================= */
const PageSettings = {
  props: ["meta", "user"],
  setup(props) {
    const theme = ref(localStorage.getItem("kdzy_theme") || "saas");
    const curIcon = ref(localStorage.getItem("kdzy_icons") || "tech");
    const curSize = ref(localStorage.getItem("kdzy_iconsize") || "md");
    const autohome = ref(localStorage.getItem("kdzy_autohome") !== "0");
    const glass = ref(localStorage.getItem("kdzy_glass") !== "0");
    const iconLabel = ref(localStorage.getItem("kdzy_iconlabel") || "auto");
    const labelOpts = [
      { id: "auto", label: "自动" },
      { id: "black", label: "黑" },
      { id: "white", label: "白" },
    ];
    const current = ref(lsJSON("kdzy_wall", null));
    const fileInput = ref(null);

    const themes = [
      { id: "atlas", label: "清新简约", desc: "shadcn 风格 · 中性色 + 翡翠强调", c1: "#059669", c2: "#fafafa" },
      { id: "console", label: "深空大屏", desc: "指挥调度 · 智慧矿山", c1: "#22d3ee", c2: "#0a1220" },
      { id: "saas", label: "极简工作台", desc: "现代 SaaS · 企业科研", c1: "#4f46e5", c2: "#f6f7f9" },
      { id: "ubuntu", label: "Ubuntu 风", desc: "Linux 发行版 · 暖灰 + 橙", c1: "#e95420", c2: "#f7f6f5" },
    ];
    const iconStyles = [
      { id: "tech", label: "实心科技", desc: "AI 生成位图 · macOS × 安卓 × 鸿蒙", isNew: true },
      { id: "soft", label: "柔和贴片", desc: "CasaOS 风格 · 柔和渐变" },
      { id: "harmony", label: "鸿蒙雅致", desc: "浅底细边 · 柔和" },
      { id: "line", label: "线性经典", desc: "透明底线性图标" },
      { id: "liquid", label: "液态玻璃", desc: "半透明玻璃质感" },
    ];
    const sizes = [
      { id: "sm", label: "小" }, { id: "md", label: "中" }, { id: "lg", label: "大" },
    ];
    const WALL_PRESETS = [
      { id: "sage", label: "远山黛", css: "linear-gradient(165deg,#eef1e6 0%,#c9dac6 48%,#8fae9d 100%)" },
      { id: "forest", label: "林海", css: "linear-gradient(160deg,#134e5e 0%,#3f7a58 55%,#71b280 100%)" },
      { id: "nebula", label: "深空", css: "linear-gradient(150deg,#0f2027 0%,#203a43 50%,#2c5364 100%)" },
      { id: "dusk", label: "暮色", css: "linear-gradient(135deg,#355c7d 0%,#6c5b7b 55%,#c06c84 100%)" },
      { id: "sky", label: "晴空", css: "linear-gradient(180deg,#a1c4fd 0%,#c2e9fb 100%)" },
      { id: "sunset", label: "斜阳", css: "linear-gradient(135deg,#ff9966 0%,#ff5e62 100%)" },
      { id: "graphite", label: "石墨", css: "linear-gradient(145deg,#2b2f36 0%,#414750 55%,#5a616b 100%)" },
      { id: "mist", label: "薄雾", css: "linear-gradient(160deg,#e8ecf1 0%,#d5dde6 50%,#b8c4d0 100%)" },
      // ── 照片壁纸（来源 pexels.com，Pexels License 免费可商用）──
      { id: "p-neon", label: "霓虹光带", kind: "photo", img: "assets/wallpapers/neon-magenta.jpg", credit: "摄影 thales13 / pexels.com" },
      { id: "p-boat", label: "落日归舟", kind: "photo", img: "assets/wallpapers/dusk-boat.jpg", credit: "摄影 Tu N Vu / pexels.com" },
      { id: "p-prism", label: "蓝紫棱镜", kind: "photo", img: "assets/wallpapers/prism-blue.jpg", credit: "摄影 thales13 / pexels.com" },
      { id: "p-rose", label: "玫瑰几何", kind: "photo", img: "assets/wallpapers/rose-geometry.jpg", credit: "摄影 Steve / pexels.com" },
    ];

    function setTheme(id) {
      rememberOpen();
      pushPref("theme", id);
      localStorage.setItem("kdzy_theme", id);
      window.location.reload();
    }
    function setIconStyle(id) {
      localStorage.setItem("kdzy_icons", id);
      document.body.dataset.icons = id;
      iconStyle.value = id;
      curIcon.value = id;
      pushPref("icons", id);
      toast("图标风格已切换");
    }
    function setSize(id) {
      localStorage.setItem("kdzy_iconsize", id);
      document.body.dataset.iconsize = id;
      curSize.value = id;
      pushPref("iconsize", id);
      toast("图标大小已调整");
    }
    function setIconLabel(id) {
      localStorage.setItem("kdzy_iconlabel", id);
      document.body.dataset.iconlabel = id;
      iconLabel.value = id;
      pushPref("iconlabel", id);
    }
    function toggleGlass(v) {
      localStorage.setItem("kdzy_glass", v ? "1" : "0");
      document.body.dataset.glass = v ? "1" : "0";
      glass.value = v;
      pushPref("glass", v ? "1" : "0");
    }
    function toggleAutohome(v) {
      localStorage.setItem("kdzy_autohome", v ? "1" : "0");
      pushPref("autohome", v ? "1" : "0");
    }
    function resetAll() {
      ["kdzy_theme", "kdzy_icons", "kdzy_iconsize", "kdzy_wall", "kdzy_autohome", "kdzy_glass", "kdzy_iconlabel"].forEach(k => localStorage.removeItem(k));
      window.location.reload();
    }
    function applyWall(v) {
      if (v === null) localStorage.removeItem("kdzy_wall");
      else localStorage.setItem("kdzy_wall", JSON.stringify(v));
      current.value = v;
      window.dispatchEvent(new Event("kdzy-wall"));
      pushPref("wall", v);
      toast("桌面壁纸已更新");
    }
    function pickPreset(p) { applyWall({ kind: "preset", id: p.id }); }
    function onFile(e) {
      const f = e.target.files[0];
      if (!f) return;
      if (!/^image\//.test(f.type)) { toast("请选择图片文件", "err"); return; }
      if (f.size > 4.5 * 1024 * 1024) { toast("图片过大，请选择 4MB 以内的图片", "err"); return; }
      const reader = new FileReader();
      reader.onload = () => applyWall({ kind: "custom", data: reader.result });
      reader.readAsDataURL(f);
      e.target.value = "";
    }
    function resetWall() { applyWall(null); }

    function onAvatar(e) {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      pickAvatarFile(f, () => toast("头像已更新，随账号同步"));
    }
    function resetAvatar() { setUserAvatar(""); toast("已恢复默认头像"); }
    /* ---------- 用户管理（仅超级管理员） ---------- */
    const users = ref([]);
    const newUser = reactive({ username: "", password: "", role: "standard" });
    const isSuper = computed(() => props.user && props.user.role === "super");
    async function loadUsers() {
      if (!isSuper.value) return;
      try { users.value = (await api("/auth/users")).users; } catch (e) { /* 忽略 */ }
    }
    loadUsers();
    async function addUser() {
      if (!newUser.username || !newUser.password) { toast("请填写用户名和密码", "err"); return; }
      try {
        const r = await api("/auth/users", { ...newUser });
        toast(`已创建用户：${r.user.username}（${r.user.role === 'super' ? '管理员' : '标准用户'}）`);
        newUser.username = ""; newUser.password = "";
        loadUsers();
      } catch (e) { toast(e.message, "err"); }
    }
    function quotaOf(role) { return role === "super" ? "50 GB" : "10 GB"; }

    return {
      theme, themes, setTheme, curIcon, iconStyles, setIconStyle,
      userAvatar, onAvatar, resetAvatar,
      curSize, sizes, setSize, autohome, toggleAutohome, glass, toggleGlass, iconLabel, labelOpts, setIconLabel, resetAll,
      current, fileInput, pickPreset, onFile, resetWall, presets: WALL_PRESETS,
      users, newUser, isSuper, addUser, quotaOf,
    };
  },
  template: `
  <div>
    <div class="page-title"><ic n="gear"></ic>系统设置</div>
    <div class="page-desc">外观个性化 · 全部设置实时生效并自动保存</div>

    <div class="panel">
      <h3>界面主题</h3>
      <div class="opt-grid cols3">
        <div v-for="t in themes" :key="t.id" class="opt-card" :class="{ active: theme === t.id }" @click="setTheme(t.id)">
          <span class="dot" :style="{ background: t.c1 }"></span>
          <span class="dot" :style="{ background: t.c2 }"></span>
          <div class="opt-name">{{ t.label }}</div>
          <div class="opt-desc">{{ t.desc }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>图标风格</h3>
      <div class="opt-grid cols3">
        <div v-for="s in iconStyles" :key="s.id" class="opt-card" :class="{ active: curIcon === s.id }" @click="setIconStyle(s.id)">
          <div class="opt-demo" data-demo>
            <span class="app-tile demo-tile" :class="'demo-' + s.id"><ic :n="'home'"></ic></span>
          </div>
          <div class="opt-name">{{ s.label }}</div>
          <div class="opt-desc">{{ s.desc }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <h3>图标大小</h3>
      <div class="seg">
        <button v-for="s in sizes" :key="s.id" :class="{ on: curSize === s.id }" @click="setSize(s.id)">{{ s.label }}</button>
      </div>
    </div>

    <div class="panel">
      <h3>桌面壁纸</h3>
      <div class="wall-grid">
        <div v-for="p in presets" :key="p.id" class="wall-thumb"
          :class="{ active: current && current.kind === 'preset' && current.id === p.id, photo: p.kind === 'photo' }"
          :style="p.img ? { backgroundImage: 'url(' + p.img + ')', backgroundSize: 'cover', backgroundPosition: 'center' } : { background: p.css }"
          @click="pickPreset(p)" :title="p.credit || p.label">
          <span>{{ p.label }}</span>
          <span class="wall-credit" v-if="p.credit">pexels.com</span>
          <span class="wall-check" v-if="current && current.kind === 'preset' && current.id === p.id"><ic n="check"></ic></span>
        </div>
      </div>
      <div class="row" style="align-items:center; margin-top:14px;">
        <button class="btn" @click="fileInput.click()"><ic n="image"></ic>上传本地图片</button>
        <input type="file" ref="fileInput" accept="image/*" style="display:none;" @change="onFile">
        <span style="font-size:12px; color:var(--ink-2);">PNG / JPG，建议 4MB 以内</span>
        <span style="font-size:11.5px; color:var(--ink-3);">照片壁纸来源
          <a href="https://www.pexels.com" target="_blank" style="color:var(--green-2);">pexels.com</a>
          · Pexels License 免费商用</span>
        <span style="flex:1;"></span>
        <button class="btn small" @click="resetWall">恢复默认壁纸</button>
      </div>
    </div>

    <div class="panel" v-if="isSuper">
      <h3>用户管理（超级管理员）</h3>
      <table class="data" style="margin-bottom:14px;">
        <thead><tr><th>用户名</th><th>角色</th><th>存储配额</th><th>创建时间</th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.username">
            <td>{{ u.username }}</td>
            <td>{{ u.role === 'super' ? '超级管理员' : '标准用户' }}</td>
            <td class="num">{{ quotaOf(u.role) }}</td>
            <td style="color:var(--ink-2); font-size:12px;">{{ u.created }}</td>
          </tr>
        </tbody>
      </table>
      <div class="row" style="align-items:flex-end;">
        <div class="field" style="margin:0; flex:1;"><label>新用户名</label>
          <input type="text" v-model="newUser.username" placeholder="2-20 位字母/数字/中文" style="width:100%;"></div>
        <div class="field" style="margin:0; flex:1;"><label>初始密码</label>
          <input type="text" v-model="newUser.password" placeholder="至少 4 位" style="width:100%;"></div>
        <div class="field" style="margin:0;"><label>角色</label>
          <select v-model="newUser.role"><option value="standard">标准用户</option><option value="super">超级管理员</option></select></div>
        <button class="btn primary" @click="addUser">创建用户</button>
      </div>
      <div style="font-size:11.5px; color:var(--ink-2); margin-top:10px;">
        标准用户享有 10 GB 个人存储空间，数据保存于服务端数据库，登录任意设备均可访问。
      </div>
    </div>

    <div class="panel">
      <h3>个人头像</h3>
      <div class="set-row">
        <div style="display:flex; align-items:center; gap:12px;">
          <span class="ava-preview">
            <img v-if="userAvatar" :src="userAvatar" alt="">
            <ic v-else n="user"></ic>
          </span>
          <div>
            <div class="set-name">账号头像</div>
            <div class="set-desc">支持 jpg / png，自动居中方裁切为 128×128 · 随账号同步到其它设备</div>
          </div>
        </div>
        <div style="display:flex; gap:8px;">
          <label class="btn small" style="cursor:pointer;"><ic n="upload"></ic>上传图片
            <input type="file" accept="image/*" style="display:none;" @change="onAvatar"></label>
          <button class="btn small" v-if="userAvatar" @click="resetAvatar"><ic n="winclose"></ic>恢复默认</button>
        </div>
      </div>

      <h3>通用</h3>
      <div class="set-row">
        <div><div class="set-name">登录后自动打开系统概览</div><div class="set-desc">进入桌面时自动弹出概览窗口</div></div>
        <label class="switch"><input type="checkbox" :checked="autohome" @change="toggleAutohome($event.target.checked)"><span class="sl"></span></label>
      </div>
      <div class="set-row">
        <div><div class="set-name">桌面图标文字颜色</div>
          <div class="set-desc">自动跟随主题；深色壁纸可选白色、浅色壁纸可选黑色</div></div>
        <div class="seg">
          <button v-for="o in labelOpts" :key="o.id" :class="{ on: iconLabel === o.id }" @click="setIconLabel(o.id)">{{ o.label }}</button>
        </div>
      </div>
      <div class="set-row">
        <div><div class="set-name">Dock 毛玻璃效果</div>
          <div class="set-desc">悬浮 Dock、开始菜单与窗口标题栏使用半透明模糊质感；关闭后为不透明底色，在复杂壁纸上更清晰</div></div>
        <label class="switch"><input type="checkbox" :checked="glass" @change="toggleGlass($event.target.checked)"><span class="sl"></span></label>
      </div>
      <div class="set-row">
        <div><div class="set-name">恢复全部默认设置</div><div class="set-desc">主题、图标、壁纸、启动项全部还原</div></div>
        <button class="btn small" @click="resetAll">重置</button>
      </div>
    </div>
  </div>`,
};
/* ================= 文件管理 ================= */
function fmtSize(n) {
  if (n === null || n === undefined) return "-";
  if (n < 1024) return n + " B";
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + " MB";
  return (n / 1024 ** 3).toFixed(2) + " GB";
}
function extOf(name) {
  const m = String(name).match(/\.([A-Za-z0-9]{1,6})$/);
  return m ? m[1].toUpperCase() : "FILE";
}
/* 编码代码 → 展示名（与 backend/core/viewer.py 的 CODEC_LABEL 对应） */
const ENC_NAMES = { "utf-8": "UTF-8", "utf-8-bom": "UTF-8 BOM", "utf-16": "UTF-16",
                    "gb18030": "GB18030", "big5": "Big5" };
function viewerEncName(code) { return ENC_NAMES[code] || (code ? String(code).toUpperCase() : ""); }

/* ================= 在线查看器（txt 文本 / jpg 图片） ================= */
const FV_ZOOM_MIN = 0.05, FV_ZOOM_MAX = 12, FV_ZOOM_STEP = 1.25;

const FileViewer = {
  props: {
    file: { type: Object, default: null },
    index: { type: Number, default: -1 },   // 当前文件在同目录可预览文件中的序号
    total: { type: Number, default: 0 },
  },
  emits: ["close", "step", "saved"],
  setup(props, { emit }) {
    const kind = ref("other"), err = ref(""), loading = ref(false);
    /* 文本 */
    const text = ref(""), encoding = ref(""), truncated = ref(false), binary = ref(false);
    const totalLines = ref(0), gutterOn = ref(true), wrap = ref(false), fs = ref(13);
    /* 编辑 */
    const editing = ref(false), draft = ref(""), saving = ref(false);
    const area = ref(null), editScroll = ref(0);
    const encodingCode = ref("utf-8"), sha = ref(""), editable = ref(false), readonlyWhy = ref("");
    /* 窗口（macOS 风格：绿键在浮窗/铺满之间切换，黄键最小化为胶囊） */
    const win = ref(null), maximized = ref(false), minimized = ref(false);
    /* 图片 */
    const stage = ref(null), src = ref("");
    const nat = reactive({ w: 0, h: 0 });
    const stageSize = reactive({ w: 0, h: 0 });
    const scale = ref(1), rot = ref(0), tx = ref(0), ty = ref(0);
    const fit = ref(true), panning = ref(false);
    let directUrl = "", blobUrl = "";

    const canStep = computed(() => props.index >= 0 && props.total > 1);
    const dirty = computed(() => editing.value && draft.value !== text.value);
    const encLabel = computed(() => viewerEncName(encodingCode.value));
    const zoomPct = computed(() => Math.round(scale.value * 100));
    /* 行号与自动换行互斥：折行后一个逻辑行占多行，行号会与视觉行错位 */
    const showGutter = computed(() => gutterOn.value && !wrap.value
      && totalLines.value > 0 && totalLines.value <= 30000);
    function toggleGutter() { gutterOn.value = !gutterOn.value; if (gutterOn.value) wrap.value = false; }
    function toggleWrap() { wrap.value = !wrap.value; if (wrap.value) gutterOn.value = false; }
    const gutter = computed(() => {
      const n = totalLines.value, arr = new Array(n);
      for (let i = 0; i < n; i++) arr[i] = i + 1;
      return arr.join("\n");
    });
    const textOk = computed(() => kind.value === "text" && !loading.value && !err.value && !binary.value);
    const textMsg = computed(() => {
      if (loading.value) return "正在读取文本…";
      if (err.value) return err.value;
      if (binary.value) return "该文件不是纯文本（可能为二进制内容），建议下载后用本地软件打开";
      return "";
    });
    /* 标题栏第二行：文件的关键信息（macOS 标题栏的副标题位） */
    const subtitle = computed(() => {
      const f = props.file;
      if (!f) return "";
      if (kind.value === "image") {
        return (nat.w ? nat.w + " × " + nat.h + " 像素 · " : "") + fmtSize(f.size);
      }
      if (kind.value === "text") {
        return (encoding.value ? encoding.value + " · " : "")
          + (totalLines.value ? totalLines.value + " 行 · " : "") + fmtSize(f.size);
      }
      return fmtSize(f.size);
    });

    /* ---------- 图片：适应窗口 / 缩放 / 平移 ---------- */
    function fitScale() {
      if (!nat.w || !stageSize.w) return 1;
      const swapped = rot.value % 180 !== 0;
      const w = swapped ? nat.h : nat.w, h = swapped ? nat.w : nat.h;
      return Math.min(1, (stageSize.w - 30) / w, (stageSize.h - 30) / h);
    }
    const pannable = computed(() => nat.w > 0 && scale.value > fitScale() * 1.002);
    /* 仅这些格式可能带透明通道，画布才铺棋盘底 */
    const alphaCapable = computed(() => {
      const e = (props.file ? extOf(props.file.name) : "").toLowerCase();
      return ["png", "gif", "webp", "svg", "avif", "ico"].indexOf(e) >= 0;
    });
    const imgStyle = computed(() => ({
      transform: `translate(-50%, -50%) translate(${tx.value}px, ${ty.value}px) `
               + `scale(${scale.value}) rotate(${rot.value}deg)`,
    }));

    function syncStage() {
      const el = stage.value;
      if (el) { stageSize.w = el.clientWidth; stageSize.h = el.clientHeight; }
    }
    function applyFit() {
      syncStage();
      scale.value = fitScale();
      tx.value = 0; ty.value = 0; fit.value = true;
    }
    function zoomReset() {
      scale.value = 1; tx.value = 0; ty.value = 0; fit.value = false;
    }
    /* 以容器内某点为锚缩放：保证光标下的像素在缩放前后不动 */
    function zoomAt(ux, uy, k) {
      const s0 = scale.value;
      const s1 = Math.max(FV_ZOOM_MIN, Math.min(FV_ZOOM_MAX, s0 * k));
      if (Math.abs(s1 - s0) < 1e-4) return;
      const r = s1 / s0;
      tx.value = ux - (ux - tx.value) * r;
      ty.value = uy - (uy - ty.value) * r;
      scale.value = s1;
      fit.value = false;
    }
    function zoomBy(k) { zoomAt(0, 0, k); }
    function onWheel(e) {
      const el = stage.value;
      if (!el) return;
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2,
        e.deltaY < 0 ? FV_ZOOM_STEP : 1 / FV_ZOOM_STEP);
    }
    function rotate() {
      rot.value = (rot.value + 90) % 360;
      if (fit.value) applyFit();
    }
    function toggleZoomFit() { fit.value ? zoomReset() : applyFit(); }
    function panStart(e) {
      if (e.button !== 0 || !pannable.value) return;
      const sx = e.clientX, sy = e.clientY, ox = tx.value, oy = ty.value;
      panning.value = true;
      const move = (ev) => { tx.value = ox + ev.clientX - sx; ty.value = oy + ev.clientY - sy; };
      const up = () => {
        panning.value = false;
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }

    /* ---------- 资源读取 ---------- */
    function revokeBlob() {
      if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = ""; }
    }
    function onImgLoad(e) {
      nat.w = e.target.naturalWidth;
      nat.h = e.target.naturalHeight;
      err.value = "";
      applyFit();
    }
    async function onImgError() {
      const f = props.file;
      if (!f) return;
      if (src.value === directUrl) {          // Cookie 不可用时改用带 Token 的请求重试一次
        try {
          const r = await apiFetch("/files/preview/" + f.id);
          blobUrl = URL.createObjectURL(await r.blob());
          src.value = blobUrl;
          return;
        } catch (e) { err.value = e.message; return; }
      }
      err.value = "图像内容无法解析，可下载后用本地软件打开";
    }
    async function loadText(f, forceCode) {
      loading.value = true;
      try {
        const r = await apiFetch("/files/text/" + f.id
          + (forceCode ? "?encoding=" + encodeURIComponent(forceCode) : ""));
        const d = await r.json();
        binary.value = d.kind === "binary";
        text.value = d.text || "";
        encoding.value = d.encoding || "";
        truncated.value = !!d.truncated;
        totalLines.value = d.lines || 0;
        editable.value = !!d.editable;
        encodingCode.value = d.encoding_code || "utf-8";
        sha.value = d.sha256 || "";
        readonlyWhy.value = d.truncated
          ? "文件超过 2 MB，仅支持查看（避免只保存下截断的内容而损坏原文件）"
          : "文件含无法识别的字节，已禁用编辑以避免覆盖后损坏原文件";
        loading.value = false;
        return true;
      } catch (e) {
        loading.value = false;
        if (!forceCode) err.value = e.message;     // 手动指定编码试错时静默
        return false;
      }
    }

    /* 切换文件编码：GB18030 与 Big5 字节区间重叠，自动探测可能误判，
       依次试下一候选，能解码即采用（显示与保存都用它） */
    const ENC_LIST = ["utf-8", "gb18030", "big5", "utf-16", "utf-8-bom"];
    async function cycleEncoding() {
      if (!props.file || loading.value) return;
      if (dirty.value && !confirm("切换编码会重新载入文件，未保存的修改将丢失。继续？")) return;
      if (dirty.value) { editing.value = false; draft.value = ""; }
      const start = ENC_LIST.indexOf(encodingCode.value);
      for (let i = 1; i <= ENC_LIST.length; i++) {
        const code = ENC_LIST[(start + i) % ENC_LIST.length];
        if (code === encodingCode.value) break;
        if (await loadText(props.file, code)) {
          toast("已按 " + viewerEncName(code) + " 解码");
          return;
        }
      }
      toast("没有其他可用于解码的编码", "err");
    }
    function load() {
      const f = props.file;
      err.value = ""; loading.value = false; binary.value = false; truncated.value = false;
      text.value = ""; encoding.value = ""; totalLines.value = 0;
      editing.value = false; draft.value = ""; saving.value = false; editable.value = false;
      nat.w = 0; nat.h = 0; scale.value = 1; rot.value = 0;
      tx.value = 0; ty.value = 0; fit.value = true;
      revokeBlob();
      if (!f) { src.value = ""; return; }
      kind.value = f.view || "other";
      src.value = "/api/files/preview/" + f.id;
      directUrl = src.value;
      if (kind.value === "text") { src.value = ""; loadText(f); }
    }
    watch(() => props.file && props.file.id, load, { immediate: true });

    async function copyAll() {
      try { await navigator.clipboard.writeText(text.value); toast("已复制全部内容"); }
      catch (e) { toast("复制失败，请手动选择文本", "err"); }
    }

    /* ---------- 编辑 ---------- */
    function startEdit() {
      if (!editable.value) return;
      draft.value = text.value;
      editScroll.value = 0;
      editing.value = true;
      nextTick(() => { if (area.value) area.value.focus(); });
    }
    function leaveEdit() {                       // 退出编辑：有改动先确认
      if (!editing.value) return;
      if (dirty.value && !confirm("有未保存的修改，确认放弃？")) return;
      editing.value = false;
      draft.value = "";
    }
    function toggleEdit() { editing.value ? leaveEdit() : startEdit(); }
    function onAreaScroll(e) { editScroll.value = e.target.scrollTop; }

    async function save(opts) {
      const o = opts || {};
      if (!editing.value || saving.value) return;
      saving.value = true;
      try {
        const r = await api("/files/save", {
          id: props.file.id, text: draft.value,
          encoding: o.encoding || encodingCode.value || "utf-8",
          base_sha256: sha.value, force: !!o.force,
        });
        const prevCode = encodingCode.value;
        text.value = draft.value;
        totalLines.value = draft.value ? draft.value.split("\n").length : 0;
        sha.value = r.sha256;
        encodingCode.value = r.encoding || prevCode;
        if (encodingCode.value !== prevCode) encoding.value = viewerEncName(encodingCode.value);
        emit("saved", r);                        // 父组件同步列表里的大小与时间
        toast("已保存 · " + fmtSize(r.size));
      } catch (e) {
        saving.value = false;
        if (e.status === 409 && confirm(e.message + "\n\n仍要覆盖保存吗？")) return save({ force: true });
        const code = o.encoding || encodingCode.value;
        if (e.data && e.data.code === "encoding" && code !== "utf-8"
            && confirm(e.message + "\n\n改用 UTF-8 编码保存？")) return save({ encoding: "utf-8" });
        toast(e.message, "err");
        return;
      }
      saving.value = false;
    }

    function step(d) {
      if (!canStep.value) return;
      if (dirty.value && !confirm("有未保存的修改，确认切换文件？")) return;
      editing.value = false;
      draft.value = "";
      emit("step", d);
    }
    function close() {
      if (dirty.value && !confirm("有未保存的修改，确认关闭？")) return;
      emit("close");
    }

    function onKey(e) {
      if (e.key === "Escape") { editing.value ? leaveEdit() : close(); return; }
      const el = document.activeElement;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    }
    /* 窗口尺寸变化（绿键铺满 / 浏览器缩放）后重新适配图片 */
    let ro = null;
    onMounted(() => {
      window.addEventListener("keydown", onKey);
      window.addEventListener("resize", syncStage);
      if (window.ResizeObserver) {
        ro = new ResizeObserver(() => { syncStage(); if (fit.value) applyFit(); });
        if (win.value) ro.observe(win.value);
      }
      nextTick(syncStage);
    });
    onUnmounted(() => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", syncStage);
      if (ro) ro.disconnect();
      revokeBlob();
    });

    return { kind, err, loading, text, encoding, truncated, binary, totalLines, gutterOn, wrap, fs,
             win, maximized, minimized,
             stage, src, nat, scale, rot, fit, panning, canStep, zoomPct, showGutter, gutter,
             textOk, textMsg, subtitle, pannable, alphaCapable, imgStyle, toggleGutter, toggleWrap,
             applyFit, zoomReset, zoomBy, onWheel, rotate, toggleZoomFit, panStart, onImgLoad, onImgError,
             editing, draft, saving, area, editScroll, editable, readonlyWhy, dirty, encLabel,
             startEdit, leaveEdit, toggleEdit, onAreaScroll, save, cycleEncoding,
             copyAll, step, close, fmtSize, extOf };
  },
  template: `
  <Teleport to="body">
  <div class="fv-backdrop" :class="{ plain: minimized }" @pointerdown.self="close">
    <div class="fv-win" :class="{ max: maximized }" v-show="!minimized" ref="win">
      <!-- macOS 标题栏：红黄绿灯 · 居中双行标题 · 右侧分段工具栏 -->
      <div class="fv-bar">
        <!-- 与桌面窗口标题栏共用同一套交通灯样式（.tl / .tl-group） -->
        <div class="tl-group">
          <button class="tl tl-close" title="关闭（Esc）" @click="close"><ic n="winclose"></ic></button>
          <button class="tl tl-min" title="最小化为悬浮胶囊" @click="minimized = true"><ic n="winmin"></ic></button>
          <button class="tl tl-max" :title="maximized ? '还原窗口' : '铺满屏幕'"
            @click="maximized = !maximized"><ic :n="maximized ? 'winrestore' : 'winmax'"></ic></button>
        </div>
        <div class="fv-title" :title="file ? file.name : ''">
          <div class="t1">{{ file ? file.name : "" }}</div>
          <div class="t2">{{ subtitle }}</div>
        </div>
        <div class="fv-tools">
          <template v-if="kind === 'image'">
            <div class="fv-seg">
              <button class="fv-btn" :class="{ on: fit }" title="适应窗口" @click="applyFit"><ic n="fitScreen"></ic></button>
              <button class="fv-btn" :class="{ on: !fit && scale === 1 }" title="原始大小 1:1" @click="zoomReset">1:1</button>
            </div>
            <div class="fv-seg">
              <button class="fv-btn" title="缩小" @click="zoomBy(1 / 1.25)"><ic n="zoomOut"></ic></button>
              <span class="lbl" title="点击恢复 100%" @click="zoomReset">{{ zoomPct }}%</span>
              <button class="fv-btn" title="放大" @click="zoomBy(1.25)"><ic n="zoomIn"></ic></button>
            </div>
            <button class="fv-btn" title="顺时针旋转 90°" @click="rotate"><ic n="rotate"></ic></button>
          </template>
          <template v-else-if="kind === 'text'">
            <div class="fv-seg">
              <button class="fv-btn" :class="{ on: showGutter }"
                :title="gutterOn ? '隐藏行号' : '显示行号（自动关闭换行）'" @click="toggleGutter"><ic n="listOrdered"></ic></button>
              <button class="fv-btn" :class="{ on: wrap }"
                :title="wrap ? '取消自动换行' : '自动换行（自动关闭行号）'" @click="toggleWrap"><ic n="wrapText"></ic></button>
            </div>
            <div class="fv-seg">
              <button class="fv-btn" title="缩小字号" @click="fs = Math.max(11, fs - 1)"><ic n="minus"></ic></button>
              <span class="lbl">{{ fs }}px</span>
              <button class="fv-btn" title="放大字号" @click="fs = Math.min(22, fs + 1)"><ic n="plus"></ic></button>
            </div>
            <button class="fv-btn" title="复制全部内容" @click="copyAll"><ic n="copy"></ic></button>
            <button class="fv-btn" @click="cycleEncoding"
              :title="'文件编码 ' + (encoding || encodingCode) + '（显示与保存均按它），点击换一种'">{{ encLabel }}</button>
            <button v-if="!editing" class="fv-btn" :disabled="!editable" :title="editable ? '编辑文本' : readonlyWhy"
              @click="startEdit"><ic n="pencil"></ic>编辑</button>
            <template v-else>
              <button class="fv-btn primary" :disabled="!dirty || saving"
                :title="dirty ? '保存（Ctrl/⌘+S）' : '没有需要保存的修改'"
                @click="save()"><ic n="save"></ic>{{ saving ? "保存中…" : "保存" }}</button>
              <button class="fv-btn" title="完成编辑（Esc）" @click="leaveEdit">完成</button>
            </template>
          </template>
          <div class="fv-seg" v-if="total > 0">
            <button class="fv-btn" :disabled="!canStep" title="上一个可预览文件（←）" @click="step(-1)"><ic n="prev"></ic></button>
            <span class="lbl" v-if="canStep" style="min-width:34px;">{{ index + 1 }}/{{ total }}</span>
            <button class="fv-btn" :disabled="!canStep" title="下一个可预览文件（→）" @click="step(1)"><ic n="next"></ic></button>
          </div>
          <a v-if="file && kind === 'image'" class="fv-btn" :href="'/api/files/preview/' + file.id"
            target="_blank" rel="noopener" title="在新标签页打开原图"><ic n="external"></ic></a>
          <a v-if="file" class="fv-btn" :href="'/api/files/download/' + file.id" :download="file.name"
            title="下载文件"><ic n="download"></ic></a>
        </div>
      </div>

      <div class="fv-body">
        <!-- 图片查看 -->
        <div v-if="kind === 'image'" ref="stage" class="fv-stage"
          :class="{ grab: pannable, grabbing: panning, opaque: !alphaCapable }"
          @pointerdown="panStart" @wheel.prevent="onWheel" @dblclick="toggleZoomFit">
          <img v-if="src" class="fv-img" :src="src" :style="imgStyle" alt=""
            @load="onImgLoad" @error="onImgError">
          <div v-if="err" class="fv-note">
            <ic n="image"></ic>
            <div>{{ err }}</div>
            <a v-if="file" class="fv-btn primary" :href="'/api/files/download/' + file.id" :download="file.name">
              <ic n="download"></ic>下载查看</a>
          </div>
          <div v-else-if="!nat.w" class="fv-note"><ic n="image"></ic><div>正在加载图像…</div></div>
        </div>

        <!-- 文本查看 -->
        <div v-else-if="kind === 'text' && textOk && !editing" class="fv-text" :style="{ '--fv-fs': fs + 'px' }">
          <div class="fv-inner" :class="{ wrap }">
            <div v-if="showGutter" class="fv-gutter">{{ gutter }}</div>
            <pre class="fv-code">{{ text }}</pre>
          </div>
        </div>

        <!-- 文本编辑：与只读视图同一套字号行高，行号栏随编辑区纵向同步 -->
        <div v-else-if="kind === 'text' && textOk" class="fv-edit" :style="{ '--fv-fs': fs + 'px' }">
          <div v-if="showGutter" class="fv-egutter">
            <div :style="{ transform: 'translateY(' + (-editScroll) + 'px)' }">{{ gutter }}</div>
          </div>
          <textarea ref="area" v-model="draft" class="fv-area" :class="{ wrap }"
            :wrap="wrap ? 'soft' : 'off'" spellcheck="false" autocapitalize="off" autocomplete="off"
            @scroll="onAreaScroll" @keydown.ctrl.s.prevent="save()" @keydown.meta.s.prevent="save()"></textarea>
        </div>
        <div v-else-if="kind === 'text'" class="fv-center">
          <div class="fv-note plain">
            <ic :n="loading ? 'fileText' : 'report'"></ic>
            <div>{{ textMsg }}</div>
            <a v-if="!loading && file" class="fv-btn primary" :href="'/api/files/download/' + file.id" :download="file.name">
              <ic n="download"></ic>下载查看</a>
          </div>
        </div>

        <!-- 其他格式 -->
        <div v-else class="fv-center">
          <div class="fv-note plain">
            <ic n="report"></ic>
            <div>「{{ file ? extOf(file.name) : "" }}」格式暂不支持在线查看</div>
            <div class="fv-tip">支持在线查看：图片 jpg / jpeg / png / gif / webp / bmp / svg；文本 txt / log / csv / md / json / xml / ini 等</div>
            <a v-if="file" class="fv-btn primary" :href="'/api/files/download/' + file.id" :download="file.name">
              <ic n="download"></ic>下载文件</a>
          </div>
        </div>
      </div>

      <div class="fv-status">
        <span v-if="kind === 'image' && file">显示比例 {{ zoomPct }}%</span>
        <span v-else-if="kind === 'text' && textOk">共 {{ totalLines }} 行</span>
        <span v-if="truncated" class="warn">文件较大，仅显示前 2 MB，完整内容请下载查看</span>
        <span v-else-if="editing && dirty" class="warn">已修改 · 未保存</span>
        <span v-else-if="editing" class="ok">编辑中 · 已同步</span>
        <span class="grow"></span>
        <span v-if="kind === 'image'">滚轮缩放 · 拖动平移 · 双击切换 1:1 / 适应窗口</span>
        <span v-else-if="editing">Ctrl/⌘+S 保存 · Esc 完成编辑</span>
        <span v-else-if="kind === 'text'">← → 切换文件 · Esc 关闭</span>
        <span v-if="file && file.created">{{ file.created }}</span>
      </div>
    </div>

    <!-- 最小化后的悬浮胶囊 -->
    <button class="fv-mini" v-if="minimized" title="还原查看器" @click="minimized = false">
      <span class="dots"><i class="r"></i><i class="y"></i><i class="g"></i></span>
      <span>{{ file ? file.name : "" }}</span>
      <span class="hint">点击还原</span>
    </button>
  </div>
  </Teleport>`,
};

/* 栅格影像：文件管理里转交「图像检测」处理 */
const RASTER_EXT_LIST = ["tif", "tiff", "img", "vrt"];
function isRaster(name) { return RASTER_EXT_LIST.indexOf(extOf(name).toLowerCase()) >= 0; }

const PageFiles = {
  props: ["meta", "user"],
  emits: ["goto"],
  setup(props, { emit }) {
    const folder = ref("/");
    const items = ref([]);
    const used = ref(0), quota = ref(0);
    const loading = ref(false), dragOver = ref(false);
    const history = ref([]);
    const crumbs = computed(() => {
      const parts = folder.value.split("/").filter(Boolean);
      const arr = [{ name: "全部文件", path: "/" }];
      let acc = "";
      for (const p of parts) { acc += "/" + p + "/"; arr.push({ name: p, path: acc }); }
      return arr;
    });

    async function load() {
      loading.value = true;
      try {
        const r = await api("/files?folder=" + encodeURIComponent(folder.value));
        items.value = r.items; used.value = r.used; quota.value = r.quota;
        const h = await api("/user/history");
        history.value = h.items;
      } catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    load();

    async function uploadFiles(fileList) {
      const files = [...fileList];
      if (!files.length) return;
      for (const f of files) {
        try {
          const fd = new FormData();
          fd.append("folder", folder.value);
          fd.append("file", f);
          const r = await apiUpload("/files/upload", fd);
          toast(`已上传：${r.name}（${fmtSize(r.size)}）`);
        } catch (e) { toast(e.message, "err"); }
      }
      load();
    }
    function onPick(e) { uploadFiles(e.target.files); e.target.value = ""; }
    function onDrop(e) { dragOver.value = false; uploadFiles(e.dataTransfer.files); }

    async function mkdir() {
      const name = prompt("新文件夹名称：");
      if (!name) return;
      try {
        await api("/files/mkdir", { folder: folder.value, name });
        load();
      } catch (e) { toast(e.message, "err"); }
    }
    async function del(it) {
      if (!confirm(it.is_dir ? `确认删除文件夹「${it.name}」及其全部内容？` : `确认删除「${it.name}」？`)) return;
      try {
        await api("/files/delete", { id: it.id });
        toast("已删除");
        load();
      } catch (e) { toast(e.message, "err"); }
    }
    function openItem(it) {
      if (it.is_dir) { folder.value = folder.value + it.name + "/"; load(); }
    }
    function go(path) { folder.value = path; load(); }

    /* ---------- 在线查看 ----------
       列表接口按扩展名给出 view 字段（image / text / other）：
       图片、文本可在线预览，其余格式提示下载 */
    const viewing = ref(null);
    const viewable = computed(() => items.value.filter(x => !x.is_dir && x.view !== "other"));
    const viewPos = computed(() => viewable.value.findIndex(x => x.id === (viewing.value ? viewing.value.id : -1)));
    function open(it) { if (!it.is_dir) viewing.value = it; }
    /* 栅格影像交给「图像检测」应用打开（带上文件，跳到检测） */
    function toDetect(it) {
      detectTarget.value = { id: it.id, name: it.name, size: it.size };
      emit("goto", "detect");
    }
    function stepView(d) {
      const list = viewable.value, i = viewPos.value;
      if (i < 0 || list.length < 2) return;
      viewing.value = list[(i + d + list.length) % list.length];
    }
    /* 在线编辑保存后，同步列表中的大小、修改时间与配额占用 */
    function onSaved(r) {
      const it = items.value.find(x => x.id === r.id);
      if (it) { it.size = r.size; it.modified = r.modified; }
      used.value = r.used;
    }

    return { folder, items, used, quota, loading, dragOver, history, crumbs,
             viewing, viewable, viewPos, open, stepView, onSaved, toDetect, isRaster,
             load, uploadFiles, onPick, mkdir, del, openItem, go, onDrop, fmtSize, extOf };
  },
  template: `
  <div>
    <div class="page-title"><ic n="folder"></ic>文件管理</div>
    <div class="page-desc">个人云存储 · 文件与偏好均保存在服务端数据库，登录任意设备均可访问 ·
      点击文件名可在线查看图片与文本（txt / csv / log / json 等）</div>

    <div class="grid" style="grid-template-columns: 1fr 280px; align-items:start;">
      <div class="panel" style="margin-bottom:0;">
        <h3>{{ folder }}</h3>
        <div class="fm-toolbar">
          <label class="btn small"><ic n="upload"></ic>上传文件
            <input type="file" multiple style="display:none;" @change="onPick"></label>
          <button class="btn small" @click="mkdir"><ic n="folder"></ic>新建文件夹</button>
          <button class="btn small" @click="load"><ic n="check"></ic>刷新</button>
          <span style="flex:1;"></span>
          <div class="fm-quota">
            <div class="progress-bar" style="width:130px;">
              <div :style="{ width: Math.min(100, used / quota * 100) + '%' }"></div>
            </div>
            <span>{{ fmtSize(used) }} / {{ (quota / 1024 ** 3).toFixed(0) }} GB</span>
          </div>
        </div>
        <div class="fm-crumbs">
          <template v-for="(c, i) in crumbs" :key="c.path">
            <span class="fm-crumb" :class="{ cur: i === crumbs.length - 1 }" @click="go(c.path)">{{ c.name }}</span>
            <span v-if="i < crumbs.length - 1" class="fm-sep">/</span>
          </template>
        </div>
        <div class="fm-list" :class="{ over: dragOver }"
          @dragover.prevent="dragOver = true" @dragleave="dragOver = false"
          @drop.prevent="onDrop">
          <table class="data">
            <thead><tr><th style="width:46px;"></th><th>名称</th><th class="num">大小</th><th>时间</th><th style="width:214px;">操作</th></tr></thead>
            <tbody>
              <tr v-for="c in crumbs.slice(0, -1)" :key="'up' + c.path">
                <td><ic n="folder" style="color:var(--gold);"></ic></td>
                <td><span class="fm-link" @click="go(c.path)">返回上一级</span></td>
                <td></td><td></td><td></td>
              </tr>
              <tr v-for="it in items" :key="it.id">
                <td>
                  <span v-if="it.is_dir" class="fm-ic folder"><ic n="folder"></ic></span>
                  <span v-else class="fm-ext">{{ extOf(it.name) }}</span>
                </td>
                <td>
                  <span v-if="it.is_dir" class="fm-link" @click="openItem(it)">{{ it.name }}</span>
                  <span v-else class="fm-link" :title="it.view === 'other' ? '查看文件信息' : '点击在线查看'" @click="open(it)">{{ it.name }}</span>
                  <span v-if="!it.is_dir && it.view !== 'other'" class="fm-view-tag">
                    <ic :n="it.view === 'image' ? 'image' : 'fileText'"></ic>{{ it.view === "image" ? "图片" : "文本" }}</span>
                </td>
                <td class="num">{{ it.is_dir ? "—" : fmtSize(it.size) }}</td>
                <td style="color:var(--ink-2); font-size:12px;">{{ it.modified || it.created }}</td>
                <td>
                  <button v-if="!it.is_dir && isRaster(it.name)" class="btn small" @click="toDetect(it)"
                    title="用「图像检测」打开：结合所选数据库做扰动检测/分类/对比">去检测</button>
                  <button v-else-if="!it.is_dir" class="btn small" @click="open(it)">查看</button>
                  <a v-if="!it.is_dir" class="btn small" style="margin-left:5px;" :href="'/api/files/download/' + it.id" :download="it.name">下载</a>
                  <button class="btn small" style="margin-left:5px; color:var(--bad); border-color:var(--bad);" @click="del(it)">删除</button>
                </td>
              </tr>
              <tr v-if="!items.length && crumbs.length <= 1">
                <td colspan="5" style="text-align:center; color:var(--ink-3); padding:26px 0;">
                  {{ dragOver ? "松开鼠标即可上传" : "空文件夹 · 拖拽文件到此即可上传" }}
                </td>
              </tr>
            </tbody>
          </table>
          <div class="fm-dropmask" v-if="dragOver">松开上传到当前文件夹</div>
        </div>
      </div>

      <div>
        <div class="panel" style="margin-bottom:14px;">
          <h3>存储配额</h3>
          <div style="font-family:var(--font-num); font-size:26px; font-weight:700; color:var(--green-2);">
            {{ fmtSize(used) }}
          </div>
          <div style="font-size:12px; color:var(--ink-2); margin:4px 0 10px;">可用总额 {{ (quota / 1024 ** 3).toFixed(0) }} GB · 随账号永久保存</div>
          <div class="progress-bar"><div :style="{ width: Math.min(100, used / quota * 100) + '%' }"></div></div>
        </div>
        <div class="panel" style="margin-bottom:0;">
          <h3>最近分析记录</h3>
          <div v-if="history.length">
            <div v-for="(h, i) in history" :key="i" class="kv" style="display:block;">
              <div style="font-size:12px; color:var(--ink);">{{ h.type }}</div>
              <div style="font-size:11.5px; color:var(--ink-2); margin:2px 0;">{{ h.detail }}</div>
              <div style="font-size:11px; color:var(--ink-3);">{{ h.created }}</div>
            </div>
          </div>
          <div v-else style="color:var(--ink-3); font-size:12.5px; padding:14px 0; text-align:center;">暂无分析记录</div>
        </div>
      </div>
    </div>

    <!-- 在线查看器：txt / csv / log 等文本与 jpg / png 等图片 -->
    <file-viewer v-if="viewing" :file="viewing" :index="viewPos" :total="viewable.length"
      @close="viewing = null" @step="stepView" @saved="onSaved"></file-viewer>
  </div>`,
};

/* ================= 图像检测（导入影像 + 所选数据库） ================= */
const RASTER_ACCEPT = ".tif,.tiff,.img,.vrt,.png,.jpg,.jpeg,.bmp";
const RASTER_EXT = ["tif", "tiff", "img", "vrt", "png", "jpg", "jpeg", "bmp"];

const PageDetect = {
  props: ["meta", "user"],
  setup(props) {
    /* ---- 影像来源 ---- */
    const src = ref(null);                 // { id, name, size }
    const info = ref(null);                // 探查结果
    const inspecting = ref(false), running = ref(false), err = ref("");
    /* 个人文件选择器 */
    const picker = ref(false), pf = ref([]), pfolder = ref("/"), pq = ref(""), ploading = ref(false);
    /* ---- 波段/指数映射（探查后自动填，可改） ---- */
    const roles = reactive({ red: 0, nir: 0, swir: 0, blue: 0, green: 0 });
    const indexKeys = ref([]);             // 指数栈：每层对应的指数名（""=忽略）
    const singleIndex = ref("ndvi");
    /* ---- 检测参数 ---- */
    const mode = ref("disturb");
    const sens = ref("标准");              // 形态学强度 / 连片阈值
    const labelYear = ref(null), cmpYear = ref(null), useDrivers = ref(true);
    const result = ref(null);

    const years = computed(() => props.meta ? props.meta.dataset.years : []);
    const dsName = computed(() => props.meta ? props.meta.dataset.region : "");

    /* 从「文件管理 → 去检测」带过来的影像：直接读取 */
    watch(detectTarget, (t) => { if (t) { inspect(t); detectTarget.value = null; } }, { immediate: true });
    const INDEX_OPTS = [["ndvi", "NDVI"], ["bsi", "BSI"], ["ndbi", "NDBI"], ["lst", "LST"], ["", "忽略"]];
    const SENS = { "严格（少而准）": { close_it: 1, open_it: 1, min_patch: 30 },
                   "标准": { close_it: 2, open_it: 1, min_patch: 20 },
                   "宽松（多而全）": { close_it: 3, open_it: 1, min_patch: 10 } };

    const showPicker = ref(false);
    const files = computed(() => pf.value.filter(f => {
      const e = (f.name.split(".").pop() || "").toLowerCase();
      return (f.is_dir || RASTER_EXT.indexOf(e) >= 0)
        && (!pq.value || f.name.toLowerCase().includes(pq.value.toLowerCase()));
    }));

    async function loadFiles() {
      ploading.value = true;
      try {
        const r = await api("/files?folder=" + encodeURIComponent(pfolder.value));
        pf.value = r.items;
      } catch (e) { toast(e.message, "err"); }
      ploading.value = false;
    }
    function togglePicker() {
      picker.value = !picker.value;
      if (picker.value && !pf.value.length) loadFiles();
    }
    function enter(it) { pfolder.value = pfolder.value + it.name + "/"; loadFiles(); }
    function up() { pfolder.value = pfolder.value.replace(/[^/]+\/$/, "") || "/"; loadFiles(); }
    function crumbs() { return pfolder.value.split("/").filter(Boolean); }

    async function uploadFiles(fileList) {
      const f = fileList && fileList[0];
      if (!f) return;
      const ext = (f.name.split(".").pop() || "").toLowerCase();
      if (RASTER_EXT.indexOf(ext) < 0) { toast("请选择 GeoTIFF/TIFF 或常见图像格式（jpg/png/bmp）", "err"); return; }
      running.value = true;
      try {
        const fd = new FormData();
        fd.append("folder", "/");
        fd.append("file", f);
        const r = await apiUpload("/files/upload", fd);
        toast(`已上传：${r.name}（${fmtSize(r.size)}）`);
        pf.value = [];
        await inspect({ id: r.id, name: r.name, size: r.size });
      } catch (e) { toast(e.message, "err"); }
      running.value = false;
    }
    function onPick(e) { uploadFiles(e.target.files); e.target.value = ""; }

    async function inspect(file) {
      src.value = file;
      info.value = null; result.value = null; err.value = "";
      inspecting.value = true;
      try {
        const d = await api("/image/inspect?file_id=" + file.id);
        info.value = d;
        // 自动填映射（d.roles 是按波段名/波段数推断的角色，d.bands 是波段数）
        const b = d.roles || {};
        if (b.index_keys) indexKeys.value = b.index_keys.slice();
        else if (b.index) { singleIndex.value = b.index; indexKeys.value = []; }
        else {
          ["red", "nir", "swir", "blue", "green"].forEach(k => { roles[k] = b[k] || 0; });
          indexKeys.value = [];
        }
        labelYear.value = years.value.length ? years.value[years.value.length - 1] : 2020;
        cmpYear.value = labelYear.value;
        const n = (d.band_names || []).length;
        toast(n ? `影像已读取，按波段名识别：${d.band_names.join(" / ")}` : "影像已读取");
      } catch (e) { err.value = e.message; toast(e.message, "err"); }
      inspecting.value = false;
    }

    /* 不同影像类型给出不同的默认检测模式 */
    function defaultMode(kind) {
      if (kind === "classmap") return "compare";
      if (kind === "rgb") return "classify";
      return "disturb";
    }
    watch(info, (d) => { if (d) mode.value = defaultMode(d.kind); });

    function detectArgs() {
      const a = { file_id: src.value.id, mode: mode.value };
      const kind = info.value ? info.value.kind : "";
      if (kind === "indexstack") a.index_keys = indexKeys.value.map(k => k || "ndvi");
      else if (kind === "index") a.index_keys = [singleIndex.value];
      else a.bands = { red: roles.red, nir: roles.nir, swir: roles.swir, blue: roles.blue, green: roles.green };
      if (mode.value === "disturb") Object.assign(a, SENS[sens.value] || SENS["标准"]);
      if (mode.value === "classify") { a.year = labelYear.value; a.use_drivers = useDrivers.value; }
      if (mode.value === "compare") a.year = cmpYear.value;
      return a;
    }

    async function run() {
      if (!src.value) return;
      running.value = true; result.value = null; err.value = "";
      try {
        result.value = await api("/image/detect", detectArgs());
        toast("检测完成");
      } catch (e) { err.value = e.message; toast(e.message, "err"); }
      running.value = false;
    }
    function reset() { src.value = null; info.value = null; result.value = null; err.value = ""; }

    const ALIGN_TAG = { aligned: ["与数据库同网格", "ok"], same_crs: ["同投影·需对齐", "info"],
                        need_reproject: ["异投影·将重投影", "info"], disjoint: ["与数据库不相交", "warn"],
                        resized: ["无投影·按尺寸对齐", "warn"], unknown: ["未知", "warn"] };
    const KIND_LABEL = { multispectral: "多波段影像", indexstack: "指数栈", index: "单波段指数",
                         classmap: "地类图", rgb: "真彩色 RGB", unknown: "未识别" };
    function fmt(v, d) { return v === null || v === undefined ? "—" : (typeof v === "number" ? v.toFixed(d || 1) : v); }

    return { src, info, inspecting, running, err, picker, togglePicker, files, pfolder, pq, ploading,
             enter, up, crumbs, onPick, inspect, reset, mode, sens, SENS, labelYear, cmpYear, useDrivers,
             result, run, roles, indexKeys, singleIndex, INDEX_OPTS, years, dsName,
             ALIGN_TAG, KIND_LABEL, RASTER_ACCEPT, fmt, fmtSize, loadFiles };
  },
  template: `
  <div>
    <div class="page-title"><ic n="image"></ic>图像检测</div>
    <div class="page-desc">上传或从个人文件选择 GeoTIFF / 影像，结合当前所选矿区数据库做检测 ·
      数据库提供地类体系、训练真值与驱动因子</div>

    <div class="grid" style="grid-template-columns: 330px 1fr; align-items:start;">
      <!-- 左栏：影像来源 + 检测设置 -->
      <div>
        <div class="panel" style="margin-bottom:14px;">
          <h3>1. 选择影像</h3>
          <label class="btn primary" style="width:100%; justify-content:center; margin-bottom:8px; cursor:pointer;">
            <ic n="upload"></ic>上传影像
            <input type="file" :accept="RASTER_ACCEPT" style="display:none;" @change="onPick"></label>
          <button class="btn" style="width:100%; justify-content:center;" @click="togglePicker">
            <ic n="folder"></ic>{{ picker ? "收起个人文件" : "从个人文件选择" }}</button>
          <div class="tip-line">支持 GeoTIFF/TIFF/IMG（含多波段与投影）与 jpg/png/bmp</div>

          <div v-if="picker" style="margin-top:10px; border-top:1px dashed var(--line); padding-top:10px;">
            <div style="display:flex; gap:6px; align-items:center; margin-bottom:6px;">
              <span class="chip" style="cursor:pointer;" @click="loadFiles">/{{ crumbs().join("/") || "" }}</span>
              <button v-if="pfolder !== '/'" class="btn small" @click="up">返回上级</button>
              <span style="flex:1;"></span>
              <input v-model="pq" placeholder="搜索影像…" style="width:110px; font-size:12px; padding:3px 6px;">
            </div>
            <div class="imp-list">
              <div v-for="f in files" :key="f.id" class="imp-item" @click="f.is_dir ? enter(f) : inspect(f)">
                <ic :n="f.is_dir ? 'folder' : 'image'"></ic>
                <span class="nm">{{ f.name }}</span>
                <span class="sz">{{ f.is_dir ? "" : fmtSize(f.size) }}</span>
              </div>
              <div v-if="!files.length" class="tip-line">{{ ploading ? "读取中…" : "该目录没有可用影像" }}</div>
            </div>
          </div>

          <div v-if="src" style="margin-top:10px; border-top:1px dashed var(--line); padding-top:9px;">
            <div class="kv"><span class="k">已选影像</span><span class="v" :title="src.name">{{ src.name }}</span></div>
            <div class="kv"><span class="k">大小</span><span class="v">{{ fmtSize(src.size) }}</span></div>
            <button class="btn small" style="margin-top:6px;" @click="reset"><ic n="winclose"></ic>清除</button>
          </div>
        </div>

        <div v-if="info" class="panel" style="margin-bottom:14px;">
          <h3>2. 检测设置</h3>
          <div class="field"><label>检测模式</label>
            <select v-model="mode">
              <option value="disturb">光谱扰动检测（裸土/扰动候选）</option>
              <option value="classify">用数据库真值分类</option>
              <option value="compare">与数据库对比变化</option>
            </select></div>
          <template v-if="mode === 'disturb'">
            <div class="field"><label>灵敏度</label>
              <select v-model="sens"><option v-for="(v,k) in SENS" :key="k" :value="k">{{ k }}</option></select></div>
            <div class="tip-line">按影像自身的 NDVI/BSI/NDBI 分位数自动定阈值，无需手工调参</div>
          </template>
          <template v-else-if="mode === 'classify'">
            <div class="field"><label>训练标签年份（数据库实测地类）</label>
              <select v-model="labelYear"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select></div>
            <label class="switch-row"><input type="checkbox" v-model="useDrivers">
              同时使用数据库驱动因子（高程/坡度/距道路/距水域）作为特征</label>
          </template>
          <template v-else>
            <div class="field"><label>对比的数据库年份</label>
              <select v-model="cmpYear"><option v-for="y in years" :key="y" :value="y">{{ y }} 年</option></select></div>
            <div class="tip-line">要求影像与数据库同网格，且像元值为地类编号（1–6）</div>
          </template>

          <button class="btn primary" style="width:100%; justify-content:center; margin-top:10px;"
            :disabled="running" @click="run">
            <ic n="crosshair"></ic>{{ running ? "检测中…" : "开始检测" }}</button>
        </div>
      </div>

      <!-- 右栏：探查信息 + 结果 -->
      <div>
        <div v-if="!info && !inspecting" class="panel">
          <div class="empty-tip" style="padding:40px 0;">
            <div class="big-ic"><ic n="image"></ic></div>
            选择影像后自动读取波段、投影与空间关系
            <div class="tip-line" style="margin-top:8px;">当前数据库：{{ dsName }}（{{ years.join(" / ") }}）</div>
          </div>
        </div>
        <div v-if="inspecting" class="panel"><div class="empty-tip" style="padding:40px 0;">正在读取影像…</div></div>

        <div v-if="info" class="panel" style="margin-bottom:14px;">
          <h3>影像信息</h3>
          <div class="stat-row">
            <span class="chip">{{ KIND_LABEL[info.kind] || info.kind }}</span>
            <span class="chip">{{ info.bands }} 波段</span>
            <span class="chip">{{ info.width }} × {{ info.height }} 像元</span>
            <span class="chip">{{ info.crs || "无投影信息" }}</span>
            <span class="chip" v-if="info.resolution_m">{{ info.resolution_m }} m</span>
            <span class="chip" :class="'tag-' + (ALIGN_TAG[info.alignment.level] || ['','info'])[1]">
              {{ (ALIGN_TAG[info.alignment.level] || ["未知","info"])[0] }}</span>
          </div>
          <div class="tip-line" style="margin-top:6px;">{{ info.note }}</div>
          <div class="tip-line">{{ info.alignment.note }}</div>

          <!-- 波段角色（可改） -->
          <div style="margin-top:10px; border-top:1px dashed var(--line); padding-top:9px;">
            <div class="sec-label">波段对应关系（自动识别，可修正）</div>
            <div v-if="info.kind === 'indexstack'" class="stat-row">
              <div v-for="(k, i) in indexKeys" :key="i" class="band-pick">
                <span>第 {{ i + 1 }} 层</span>
                <select v-model="indexKeys[i]"><option v-for="o in INDEX_OPTS" :key="o[0]" :value="o[0]">{{ o[1] }}</option></select>
              </div>
            </div>
            <div v-else-if="info.kind === 'index'" class="stat-row">
              <div class="band-pick"><span>该波段是</span>
                <select v-model="singleIndex"><option v-for="o in INDEX_OPTS.filter(x => x[0])" :key="o[0]" :value="o[0]">{{ o[1] }}</option></select>
              </div>
            </div>
            <div v-else-if="info.kind === 'multispectral' || info.kind === 'rgb'" class="stat-row">
              <div v-for="r in [['red','红'],['nir','近红外'],['swir','短波红外'],['blue','蓝'],['green','绿']]" :key="r[0]" class="band-pick">
                <span>{{ r[1] }}</span>
                <select v-model.number="roles[r[0]]">
                  <option :value="0">—</option>
                  <option v-for="n in info.bands" :key="n" :value="n">B{{ n }}</option>
                </select>
              </div>
            </div>
            <div v-else class="tip-line">地类图按像元值直接解读，无需波段映射</div>
          </div>
        </div>

        <div v-if="err" class="panel" style="margin-bottom:14px;">
          <div class="empty-tip" style="color:var(--bad);">{{ err }}</div>
        </div>

        <div v-if="result" class="panel">
          <h3>检测结果</h3>
          <div class="tip-line" style="margin-bottom:10px;">
            {{ result.file.name }} · 数据库：{{ result.dataset.region }} ·
            网格：{{ result.grid.grid === 'aligned' ? '与数据库同网格' : (result.grid.resampled ? '已重采样对齐' : result.grid.grid) }}
            <span v-if="result.grid.warn">（{{ result.grid.warn }}）</span>
          </div>

          <!-- 扰动检测 -->
          <template v-if="mode === 'disturb'">
            <div class="stat-row" style="margin-bottom:12px;">
              <div class="stat-card"><div class="label">检出扰动面积</div><div class="value">{{ fmt(result.disturb_ha) }}<span class="unit">公顷</span></div></div>
              <div class="stat-card"><div class="label">占比</div><div class="value">{{ fmt(result.disturb_percent) }}<span class="unit">%</span></div></div>
              <div class="stat-card"><div class="label">连片数</div><div class="value">{{ result.patch_count }}<span class="unit">片</span></div></div>
              <div class="stat-card"><div class="label">阈值交集（未清理）</div><div class="value">{{ fmt(result.raw_ha) }}<span class="unit">公顷</span></div></div>
            </div>
            <div class="sec-label">判据（自适应分位数阈值）</div>
            <div class="stat-row" style="margin-bottom:8px;">
              <span v-for="c in result.criteria" :key="c.index" class="chip md">{{ c.index }} {{ c.rule }}</span>
            </div>
            <div class="tip-line" style="margin-bottom:12px;">
              三条判据取交集得到零碎像元，再按「{{ sens }}」做形态学清理：先闭运算并合邻近碎斑、再开运算剔除孤立噪点，
              因此清理后的面积可能与交集不同（并合处会略微增大）。</div>
            <img class="map-img" :src="result.map_url" style="image-rendering:auto; margin-bottom:12px;">
            <div class="sec-label">主要连片（前 8）</div>
            <table class="data"><thead><tr><th>片区</th><th class="num">像元</th><th class="num">面积(ha)</th><th>中心(列,行)</th></tr></thead>
              <tbody><tr v-for="(p, i) in result.patches.slice(0, 8)" :key="p.id">
                <td>#{{ i + 1 }}</td><td class="num">{{ p.pixels }}</td>
                <td class="num">{{ fmt(p.area_ha, 2) }}</td><td>{{ p.center_px.join(", ") }}</td></tr></tbody></table>
          </template>

          <!-- 用数据库真值分类 -->
          <template v-else-if="mode === 'classify'">
            <div class="stat-row" style="margin-bottom:12px;">
              <div class="stat-card"><div class="label">总体精度 OA</div><div class="value">{{ fmt(result.overall_accuracy, 2) }}<span class="unit">%</span></div></div>
              <div class="stat-card"><div class="label">Kappa</div><div class="value">{{ fmt(result.kappa, 4) }}</div></div>
              <div class="stat-card"><div class="label">训练/检验样本</div><div class="value">{{ result.n_train }}/{{ result.n_test }}</div></div>
              <div class="stat-card"><div class="label">标签年份</div><div class="value">{{ result.label_year }}<span class="unit">年</span></div></div>
            </div>
            <div class="sec-label">特征（来自导入影像 + 数据库）</div>
            <div class="stat-row" style="margin-bottom:12px;">
              <span v-for="f in result.feature_names" :key="f" class="chip md">{{ f }}</span>
            </div>
            <img class="map-img" :src="result.map_url" style="image-rendering:auto; margin-bottom:12px;">
            <div class="sec-label">逐类精度</div>
            <table class="data"><thead><tr><th>地类</th><th class="num">制图精度</th><th class="num">用户精度</th><th class="num">检验像元</th></tr></thead>
              <tbody><tr v-for="c in result.per_class" :key="c.id">
                <td>{{ c.name }}</td>
                <td class="num">{{ c.producer_acc === null ? "—" : c.producer_acc + "%" }}</td>
                <td class="num">{{ c.user_acc === null ? "—" : c.user_acc + "%" }}</td>
                <td class="num">{{ c.test_pixels }}</td></tr></tbody></table>
          </template>

          <!-- 与数据库对比 -->
          <template v-else>
            <div class="stat-row" style="margin-bottom:12px;">
              <div class="stat-card"><div class="label">变化面积</div><div class="value">{{ fmt(result.changed_percent) }}<span class="unit">%</span></div></div>
              <div class="stat-card"><div class="label">变化像元</div><div class="value">{{ result.changed_pixels }}</div></div>
              <div class="stat-card"><div class="label">变化热点</div><div class="value">{{ result.hotspots.length }}<span class="unit">处</span></div></div>
            </div>
            <img class="map-img" :src="result.map_url" style="image-rendering:auto; margin-bottom:12px;">
            <div class="sec-label">主要转移（前 8）</div>
            <table class="data"><thead><tr><th>转换方向</th><th class="num">面积(ha)</th><th class="num">概率</th></tr></thead>
              <tbody><tr v-for="(t, i) in result.transfers.slice(0, 8)" :key="i">
                <td>{{ t.from }} → {{ t.to }}</td><td class="num">{{ fmt(t.area_ha) }}</td>
                <td class="num">{{ (t.prob * 100).toFixed(1) }}%</td></tr></tbody></table>
            <div class="tip-line" style="margin-top:8px;">对比：{{ result.a_year }} → {{ result.b_year }}</div>
          </template>
        </div>
      </div>
    </div>
  </div>`,
};

/* ================= AI 助手（桌面悬浮对话面板 + 设置窗口） ================= */
const AI_MODELS_HINT = "本地优先：把 GGUF 放到软件旁的 models/ 目录即可，离线可用";

const AssistantChat = {
  props: { meta: Boolean },
  emits: ["goto", "settings"],
  setup(props, { emit }) {
    const q = ref(""), busy = ref(false), msgs = ref([]);
    const st = ref(null), listEl = ref(null), area = ref(null);
    const PRESETS = [
      "矿区现在的耕地和林地各有多少？",
      "过去二十年变化最大的地类是什么？",
      "2030 年生态优先情景有什么建议？",
      "Kappa 系数怎么理解？",
    ];
    async function loadStatus() { try { st.value = await api("/llm/status"); } catch (e) {} }
    loadStatus();
    async function send(text) {
      const s = (text !== undefined ? text : q.value).trim();
      if (!s || busy.value) return;
      q.value = "";
      msgs.value.push({ role: "user", content: s });
      busy.value = true;
      await nextTick();
      if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
      try {
        const r = await api("/assistant/chat", { question: s, history: msgs.value.slice(0, -1) });
        msgs.value.push({ role: "assistant", content: r.answer, actions: r.actions || [],
                          refs: r.references || [], unverified: r.unverified || [],
                          meta: (r.provider === "local" ? "本地" : "云端") + " · " + r.seconds + "s" });
      } catch (e) {
        msgs.value.push({ role: "error", content: e.message });
      }
      busy.value = false;
      await nextTick();
      if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
      resetHeight();
      focusInput();
    }
    function clearAll() { msgs.value = []; }

    /* 输入框：自动增高到 5 行以内，超出后内部滚动 */
    function onInput() {
      const el = area.value;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 96) + "px";
    }
    function resetHeight() {
      const el = area.value;
      if (el) el.style.height = "auto";
    }
    function focusInput() {
      nextTick(() => { if (area.value) area.value.focus(); });
    }
    /* 回车发送、Shift+Enter 换行。关键：中文输入法组字期间的回车是"确认候选词"，
       不能当发送——否则用户打一半就被发出去（isComposing / keyCode 229 都要判） */
    function onKeydown(e) {
      if (e.key !== "Enter" || e.shiftKey) return;
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      send();
    }
    function onEsc(e) { if (e.key === "Escape") emit("close"); }
    onMounted(() => {
      window.addEventListener("keydown", onEsc);
      focusInput();
    });
    onUnmounted(() => window.removeEventListener("keydown", onEsc));
    return { q, busy, msgs, st, listEl, area, PRESETS, send, clearAll, loadStatus,
             onInput, onKeydown };
  },
  template: `
  <div class="ai-float">
    <div class="ai-head">
      <span class="ai-ava"><img src="assets/logo-64.png" alt="AI"></span>
      <div class="ai-htext">
        <div class="ai-name">图图</div>
        <div class="ai-sub">
          <span class="dot" :class="st && (st.provider === 'local' ? st.local.ready : st.api.configured) ? 'on' : 'off'"></span>
          {{ st ? (st.provider === 'local' ? (st.local.ready ? '本地模型 · ' + (st.local.model || '') : '本地模型未就绪') : '云端接口') : '检测中…' }}
        </div>
      </div>
      <button class="ai-ib" title="清空对话" v-if="msgs.length" @click="clearAll"><ic n="winclose"></ic></button>
      <button class="ai-ib" title="图图设置（模型方案 / 知识库）" @click="$emit('settings')"><ic n="sliders"></ic></button>
      <button class="ai-ib" title="收起（Esc）" @click="$emit('close')"><ic n="winmin"></ic></button>
    </div>

    <div class="ai-body" ref="listEl">
      <div v-if="!msgs.length" class="ai-empty">
        <div class="ai-ava big"><img src="assets/logo.png" alt="AI"></div>
        <div class="ai-hi">你好，我是图图</div>
        <div class="ai-tip">我可以解读当前矿区的数据、解释遥感与地信概念，并带你跳到对应功能页</div>
        <div class="ai-chips">
          <button v-for="p in PRESETS" :key="p" class="ai-chip" @click="send(p)">{{ p }}</button>
        </div>
      </div>

      <div v-for="(m, i) in msgs" :key="i" class="ai-row" :class="m.role">
        <span v-if="m.role === 'assistant'" class="ai-ava sm"><img src="assets/logo-64.png" alt="AI"></span>
        <div class="ai-col">
          <div class="ai-bub" :class="m.role">{{ m.content }}</div>
          <div v-if="m.role === 'assistant'" class="ai-meta">
            <span>{{ m.meta }}</span>
            <span v-if="m.refs && m.refs.length" class="ai-ref" :title="m.refs.join('、')">知识库 {{ m.refs.length }} 条</span>
            <span v-if="m.unverified && m.unverified.length" class="ai-ref warn" :title="'未在当前数据中核对：' + m.unverified.join('、')">待核 {{ m.unverified.length }}</span>
            <button v-for="a in m.actions" :key="a.id" class="ai-jump" @click="$emit('goto', a.id)">
              {{ a.label }}<ic n="next"></ic></button>
          </div>
        </div>
      </div>

      <div v-if="busy" class="ai-row assistant">
        <span class="ai-ava sm"><img src="assets/logo-64.png" alt="AI"></span>
        <div class="ai-bub assistant typing"><i></i><i></i><i></i></div>
      </div>
    </div>

    <div class="ai-compose">
      <textarea ref="area" v-model="q" rows="1"
        placeholder="问点关于矿区的事…（Enter 发送 / Shift+Enter 换行）"
        @input="onInput" @keydown="onKeydown"></textarea>
      <button class="ai-send" :disabled="busy || !q.trim()" @click="send()"><ic n="play"></ic></button>
    </div>
  </div>`,
};

const PageAiSettings = {
  props: ["meta", "user"],
  setup() {
    const st = ref(null), kb = ref(null), saving = ref(false), msg = ref("");
    const cfg = reactive({ provider: "local", api_base: "", api_key: "", api_model: "" });
    async function load() {
      try {
        st.value = await api("/llm/status");
        cfg.provider = st.value.provider;
        cfg.api_base = st.value.api.base || "";
        cfg.api_model = st.value.api.model || "";
      } catch (e) { /* 忽略 */ }
      try { kb.value = await api("/kb/stats"); } catch (e) {}
    }
    load();
    async function save() {
      saving.value = true; msg.value = "";
      try {
        await api("/llm/config", { provider: cfg.provider, api_base: cfg.api_base,
                                   api_key: cfg.api_key, api_model: cfg.api_model });
        msg.value = "已保存并生效";
        await load();
      } catch (e) { msg.value = e.message; }
      saving.value = false;
    }
    function backLocal() { cfg.provider = "local"; save(); }
    return { st, kb, cfg, saving, msg, load, save, backLocal };
  },
  template: `
  <div>
    <div class="page-title"><ic n="sliders"></ic>图图设置</div>
    <div class="page-desc">图图（AI 助手）的模型方案、知识库与运行状态 · 本地优先，离线可用</div>

    <div class="grid" style="grid-template-columns: 1fr 300px; align-items:start;">
      <div class="panel">
        <h3>模型方案</h3>
        <div class="ai-cards">
          <div class="ai-card" :class="{ on: cfg.provider === 'local' }" @click="cfg.provider = 'local'">
            <div class="ai-card-t"><ic n="database"></ic>本地模型<span class="tag">推荐</span></div>
            <div class="ai-card-d">完全离线、数据不出本机。模型放在软件旁 <code>models/</code> 目录，自动识别。</div>
            <div class="ai-card-s">
              <span class="dot" :class="st && st.local.ready ? 'on' : 'off'"></span>
              {{ st && st.local.model ? st.local.model + ' · ' + st.local.model_mb + ' MB' : '未找到模型文件' }}
            </div>
            <div class="tip-line" v-if="st && !st.local.lib">{{ st.local.lib_msg || '本地推理库不可用' }}</div>
            <div class="tip-line" v-else-if="st && st.local.last_error" style="color:var(--bad);">
              上次调用失败：{{ st.local.last_error }}</div>
          </div>
          <div class="ai-card" :class="{ on: cfg.provider === 'api' }" @click="cfg.provider = 'api'">
            <div class="ai-card-t"><ic n="globe"></ic>云端接口</div>
            <div class="ai-card-d">OpenAI 兼容接口（火山方舟 / DeepSeek / 通义等）。回答质量更高，但需要联网。</div>
            <div class="ai-card-s">
              <span class="dot" :class="st && st.api.configured ? 'on' : 'off'"></span>
              {{ st && st.api.configured ? st.api.model : '未配置' }}
            </div>
          </div>
        </div>

        <div v-if="cfg.provider === 'api'" style="margin-top:12px; border-top:1px dashed var(--line); padding-top:12px;">
          <div class="field"><label>接口地址</label>
            <input v-model="cfg.api_base" placeholder="https://ark.cn-beijing.volces.com/api/v3"></div>
          <div class="row" style="gap:10px;">
            <div class="field" style="flex:1;"><label>模型名 / 接入点</label>
              <input v-model="cfg.api_model" placeholder="如 deepseek-chat 或 ep-2024xxxx"></div>
            <div class="field" style="flex:1;"><label>API Key</label>
              <input v-model="cfg.api_key" type="password" placeholder="仅保存在本机 data/llm.json"></div>
          </div>
          <div class="tip-line" style="color:var(--gold);">切换到云端后，问题与数据摘要会发送到该接口；涉密数据请勿使用云端方案。</div>
        </div>

        <div style="display:flex; gap:8px; align-items:center; margin-top:14px;">
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? "保存中…" : "保存并生效" }}</button>
          <button class="btn" @click="backLocal">回到本地方案</button>
          <span class="tip-line" v-if="msg" :style="msg === '已保存并生效' ? 'color:var(--green-2)' : 'color:var(--bad)'">{{ msg }}</span>
        </div>
      </div>

      <div>
        <div class="panel" style="margin-bottom:14px;">
          <h3>知识库</h3>
          <div style="font-family:var(--font-num); font-size:24px; font-weight:700; color:var(--green-2);">
            {{ kb ? kb.sections : "—" }}<span style="font-size:12px; color:var(--ink-3); margin-left:4px;">节</span></div>
          <div class="tip-line" style="margin-top:4px;">
            {{ kb ? kb.files.join("、") + " · 约 " + kb.chars + " 字" : "读取中…" }}</div>
          <div class="tip-line" style="margin-top:8px;">
            检索方式：中文字符二元组 + IDF 加权（无需嵌入模型，离线可用）。<br>
            续写知识：直接编辑 <code>backend/data/kb/*.md</code>，按 <code>## 标题</code> 分节，助手会自动检索。</div>
        </div>
        <div class="panel" style="margin-bottom:0;">
          <h3>运行状态</h3>
          <div class="kv"><span class="k">当前方案</span><span class="v">{{ st ? st.provider : "—" }}</span></div>
          <div class="kv"><span class="k">本地库</span><span class="v">{{ st && st.local.lib ? "已安装" : "未安装" }}</span></div>
          <div class="kv"><span class="k">模型已载入</span><span class="v">{{ st && st.local.loaded ? "是" : "否（首次提问时加载）" }}</span></div>
          <div class="kv" v-if="st && st.hint"><span class="k">提示</span><span class="v" style="color:var(--gold);">{{ st.hint }}</span></div>
          <button class="btn small" style="margin-top:8px;" @click="load"><ic n="check"></ic>刷新状态</button>
        </div>
      </div>
    </div>
  </div>`,
};

/* ================= 站内消息（私聊 + 系统通知） ================= */
const MessagesPanel = {
  props: ["user"],
  emits: ["close", "read"],
  setup(props, { emit }) {
    const view = ref("list");          // list | thread
    const peer = ref(null), peerName = ref(""), notice = ref(false);
    const threads = ref([]), msgs = ref([]), draft = ref(""), busy = ref(false), err = ref("");
    const listEl = ref(null), area = ref(null);
    const isSuper = computed(() => props.user && props.user.role === "super");
    /* 联系人搜索：q 是关键词，hits 是服务端返回的 {contacts, messages} */
    const q = ref(""), hits = ref({ contacts: [], messages: [] });
    const dir = ref([]), showDir = ref(false), dirLoaded = ref(false), qi = ref(0);
    const searchEl = ref(null);
    let sTimer = null, seq = 0;

    async function loadThreads() {
      try {
        threads.value = (await api("/msg/threads")).threads || [];
        emit("read");
      } catch (e) { err.value = e.message; }
    }
    async function openThread(t) {
      peer.value = t.peer; peerName.value = t.name; notice.value = !!t.notice;
      view.value = "thread"; msgs.value = [];
      await loadMessages();
    }
    async function loadMessages() {
      if (!peer.value) return;
      try {
        const r = await api("/msg/thread/" + encodeURIComponent(peer.value));
        msgs.value = r.messages || [];
        emit("read");
        await nextTick();
        if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
      } catch (e) { err.value = e.message; }
    }
    async function send() {
      if (!peer.value || !draft.value.trim() || busy.value) return;
      busy.value = true; err.value = "";
      try {
        await api("/msg/send", { to: peer.value, body: draft.value.trim() });
        draft.value = "";
        onInput();
        await loadMessages();
        await loadThreads();
      } catch (e) { err.value = e.message; }
      busy.value = false;
    }
    function back() { view.value = "list"; peer.value = null; draft.value = ""; loadThreads(); }

    /* ---------- 联系人搜索 ---------- */
    const flat = computed(() => [
      ...hits.value.contacts.map(u => ({ kind: "c", u })),
      ...hits.value.messages.map(m => ({ kind: "m", m })),
    ]);
    /* 命中片段切成 前/命中/后 三段交给模板插值（不用 v-html，避免正文里的标签被当 HTML 执行） */
    function markSnip(text, needle) {
      const i = (text || "").toLowerCase().indexOf((needle || "").toLowerCase());
      if (i < 0) return [{ t: text || "" }];
      return [
        { t: text.slice(0, i) },
        { t: text.slice(i, i + needle.length), hit: true },
        { t: text.slice(i + needle.length) },
      ];
    }
    async function doSearch() {
      const needle = q.value.trim();
      if (!needle) { hits.value = { contacts: [], messages: [] }; return; }
      const my = ++seq;                     // 打字很快，只认最后一次请求的结果
      try {
        const r = await api("/msg/search?q=" + encodeURIComponent(needle));
        if (my !== seq) return;
        hits.value = {
          contacts: r.contacts || [],
          messages: (r.messages || []).map(m => ({ ...m, parts: markSnip(m.snippet, needle) })),
        };
        qi.value = 0;
      } catch (e) { err.value = e.message; }
    }
    function onSearch() { clearTimeout(sTimer); sTimer = setTimeout(doSearch, 240); }
    function clearSearch() {
      q.value = ""; hits.value = { contacts: [], messages: [] }; qi.value = 0;
      if (searchEl.value) searchEl.value.focus();
    }
    async function loadDir() {
      if (dirLoaded.value) return;
      try {
        dir.value = ((await api("/msg/directory")).users || []).sort((a, b) =>
          a.online === b.online ? a.username.localeCompare(b.username) : (a.online ? -1 : 1));
        dirLoaded.value = true;
      } catch (e) { err.value = e.message; }
    }
    function toggleDir() {
      showDir.value = !showDir.value;
      q.value = ""; hits.value = { contacts: [], messages: [] };
      if (showDir.value) loadDir();
    }
    /* 从搜索结果/联系人目录直接开聊（还没有会话也能开，发送即建立） */
    function openContact(username, name, notice) {
      peer.value = username; peerName.value = notice ? "系统通知" : (name || username);
      notice.value = !!notice; view.value = "thread"; msgs.value = [];
      loadMessages();
    }
    function hitAt(i) {
      const f = flat.value[i];
      if (!f) return;
      if (f.kind === "c") openContact(f.u.username, f.u.username, false);
      else openContact(f.m.peer, f.m.name, f.m.notice);
    }
    function onSearchKey(e) {
      const n = flat.value.length;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!n) return;
        e.preventDefault();
        qi.value = e.key === "ArrowDown" ? (qi.value + 1) % n : (qi.value - 1 + n) % n;
      } else if (e.key === "Enter") {
        if (e.isComposing || e.keyCode === 229) return;
        e.preventDefault();
        if (!q.value.trim()) return;
        if (n) hitAt(qi.value); else doSearch();
      } else if (e.key === "Escape") {
        e.stopPropagation();               // 面板级 Esc 是关窗口，这里先清关键词
        q.value ? clearSearch() : emit("close");
      }
    }

    /* 输入框：与 AI 助手一致的自动增高 + 输入法安全的回车发送 */
    function onInput() {
      const el = area.value;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 84) + "px";
    }
    function onKeydown(e) {
      if (e.key !== "Enter" || e.shiftKey) return;
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      send();
    }
    function onEsc(e) {
      if (e.key !== "Escape") return;
      if (view.value === "list" && q.value) { clearSearch(); return; }
      emit("close");
    }
    onMounted(() => { window.addEventListener("keydown", onEsc); loadThreads(); });
    onUnmounted(() => window.removeEventListener("keydown", onEsc));
    let timer = setInterval(() => {
      if (view.value === "thread") loadMessages();
      else if (q.value.trim()) doSearch();      // 搜索结果也保持在线状态/未读数新鲜
      else loadThreads();
    }, 6000);
    onUnmounted(() => { clearInterval(timer); clearTimeout(sTimer); });

    return { view, peer, peerName, notice, threads, msgs, draft, busy, err, isSuper,
             listEl, area, openThread, send, back, loadThreads, loadMessages, onInput, onKeydown,
             q, hits, dir, showDir, qi, searchEl, flat, openContact, clearSearch, onSearch,
             onSearchKey, toggleDir, loadDir };
  },
  template: `
  <div class="msg-float">
    <div class="ai-head">
      <span class="ai-ava m"><ic n="mail"></ic></span>
      <div class="ai-htext">
        <div class="ai-name">{{ view === "list" ? "站内消息" : peerName }}</div>
        <div class="ai-sub">
          <template v-if="view === 'list'">与在线用户私聊 · 接收超级管理员的系统通知</template>
          <template v-else-if="notice">{{ isSuper ? "系统通知：对全部账号广播" : "系统通知（只读）" }}</template>
          <template v-else>与 {{ peerName }} 的私聊</template>
        </div>
      </div>
      <button class="ai-ib" v-if="view === 'thread'" title="返回会话列表" @click="back"><ic n="prev"></ic></button>
      <button class="ai-ib" title="收起（Esc）" @click="$emit('close')"><ic n="winmin"></ic></button>
    </div>

    <div v-if="view === 'list'" class="ai-body">
      <div class="msg-search">
        <div class="msg-field">
          <ic n="search"></ic>
          <input ref="searchEl" v-model="q" placeholder="搜索联系人 / 消息内容…"
                 @input="onSearch" @keydown="onSearchKey">
          <button class="ds-x" v-if="q" @click="clearSearch" title="清空（Esc）"><ic n="winclose"></ic></button>
        </div>
        <button class="msg-add" :class="{ on: showDir }" @click="toggleDir"
                :title="showDir ? '返回会话列表' : '全部联系人 / 发起新对话'"><ic n="plus"></ic></button>
      </div>

      <!-- 一、搜索中：联系人 + 消息记录 -->
      <template v-if="q.trim()">
        <div v-if="hits.contacts.length" class="msg-sec">联系人 <span class="msg-sec-n">{{ hits.contacts.length }}</span></div>
        <div v-for="(u, i) in hits.contacts" :key="'c' + u.username" class="msg-item" :class="{ hl: qi === i }"
             @click="openContact(u.username, u.username, false)">
          <span class="ai-ava sm m"><ic n="user"></ic></span>
          <div class="msg-item-main">
            <div class="msg-item-top">
              <span class="msg-item-name">{{ u.username }}</span>
              <span class="msg-role">{{ u.role_label }}</span>
              <span class="dot" :class="u.online ? 'on' : 'off'" :title="u.online ? '在线' : '离线'"></span>
              <span class="msg-item-time">{{ u.time || "" }}</span>
            </div>
            <div class="msg-item-last">{{ u.last || "开始新对话" }}</div>
          </div>
          <span v-if="u.unread" class="msg-item-badge">{{ u.unread > 99 ? "99+" : u.unread }}</span>
          <span v-else class="msg-start">对话</span>
        </div>

        <div v-if="hits.messages.length" class="msg-sec">消息记录 <span class="msg-sec-n">{{ hits.messages.length }}</span></div>
        <div v-for="(m, i) in hits.messages" :key="'m' + m.id" class="msg-item"
             :class="{ hl: qi === hits.contacts.length + i }"
             @click="openContact(m.peer, m.name, m.notice)">
          <span class="ai-ava sm m"><ic :n="m.notice ? 'report' : 'user'"></ic></span>
          <div class="msg-item-main">
            <div class="msg-item-top">
              <span class="msg-item-name">{{ m.name }}</span>
              <span v-if="m.notice" class="ai-ref">系统</span>
              <span v-else-if="m.mine" class="ai-ref">我</span>
              <span class="msg-item-time">{{ m.created }}</span>
            </div>
            <div class="msg-item-last msg-snip">
              <span v-for="(p, k) in m.parts" :key="k" :class="{ hit: p.hit }">{{ p.t }}</span>
            </div>
          </div>
        </div>

        <div v-if="!hits.contacts.length && !hits.messages.length" class="ai-empty">
          <div class="ai-ava big"><ic n="search"></ic></div>
          <div class="ai-hi">没有找到「{{ q.trim() }}」</div>
          <div class="ai-tip">可搜账号名、角色（超级管理员 / 标准用户），或消息里的关键词。↑↓ 选择，Enter 打开。</div>
        </div>
      </template>

      <!-- 二、未搜索：全部联系人（右上 ＋ 打开） -->
      <template v-else-if="showDir">
        <div class="msg-sec">全部联系人 <span class="msg-sec-n">{{ dir.length }}</span></div>
        <div v-if="!dir.length" class="tip-line" style="text-align:center; padding:14px 0;">暂无其它账号</div>
        <div v-for="u in dir" :key="'d' + u.username" class="msg-item"
             @click="openContact(u.username, u.username, false)">
          <span class="ai-ava sm m"><ic n="user"></ic></span>
          <div class="msg-item-main">
            <div class="msg-item-top">
              <span class="msg-item-name">{{ u.username }}</span>
              <span class="msg-role">{{ u.role_label }}</span>
              <span class="dot" :class="u.online ? 'on' : 'off'" :title="u.online ? '在线' : '离线'"></span>
            </div>
            <div class="msg-item-last">{{ u.online ? "在线 · 可以立即发送" : "离线 · 消息下次登录可见" }}</div>
          </div>
          <span class="msg-start">对话</span>
        </div>
      </template>

      <!-- 三、默认：会话列表 -->
      <template v-else>
        <div v-if="!threads.length" class="ai-empty">
          <div class="ai-ava big"><ic n="mail"></ic></div>
          <div class="ai-hi">还没有消息</div>
          <div class="ai-tip">系统通知会出现在这里；点右上 ＋ 或直接搜索账号，发一条消息即可开始对话</div>
        </div>
        <div v-for="t in threads" :key="t.peer" class="msg-item" @click="openThread(t)">
          <span class="ai-ava sm m"><ic :n="t.notice ? 'report' : 'user'"></ic></span>
          <div class="msg-item-main">
            <div class="msg-item-top">
              <span class="msg-item-name">{{ t.name }}</span>
              <span v-if="t.notice" class="ai-ref">系统</span>
              <span v-else class="dot" :class="t.online ? 'on' : 'off'" :title="t.online ? '在线' : '离线'"></span>
              <span class="msg-item-time">{{ t.time }}</span>
            </div>
            <div class="msg-item-last">{{ t.last || "（暂无消息）" }}</div>
          </div>
          <span v-if="t.unread" class="msg-item-badge">{{ t.unread > 99 ? "99+" : t.unread }}</span>
        </div>
        <div class="tip-line" style="margin-top:10px;">在线状态取自当前登录会话；离线用户也能收到消息，下次登录即可看到。</div>
      </template>
    </div>

    <template v-else>
      <div class="ai-body" ref="listEl">
        <div v-if="!msgs.length" class="tip-line" style="text-align:center; padding:18px 0;">
          {{ notice && !isSuper ? "暂无系统通知" : "还没有消息，发送第一条吧" }}</div>
        <div v-for="m in msgs" :key="m.id" class="ai-row" :class="m.mine ? 'user' : 'assistant'">
          <span v-if="!m.mine" class="ai-ava sm m"><ic :n="notice ? 'report' : 'user'"></ic></span>
          <div class="ai-col">
            <div class="ai-bub" :class="m.mine ? 'user' : 'assistant'">{{ m.body }}</div>
            <div class="ai-meta">
              <span>{{ m.mine ? "我" : m.sender }}</span>
              <span v-if="notice && isSuper">· 系统通知</span>
              <span>{{ m.created }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="ai-compose" v-if="!notice || isSuper">
        <textarea ref="area" v-model="draft" rows="1"
          :placeholder="notice ? '输入系统通知内容，将广播给全部账号…' : '输入消息…（Enter 发送 / Shift+Enter 换行）'"
          @input="onInput" @keydown="onKeydown"></textarea>
        <button class="ai-send" :disabled="busy || !draft.trim()" @click="send()"><ic n="play"></ic></button>
      </div>
      <div class="tip-line" v-else style="padding:10px 14px;">系统通知为只读，仅超级管理员可发布。</div>
      <div class="tip-line" v-if="err" style="color:var(--bad); padding:0 14px 10px;">{{ err }}</div>
    </template>
  </div>`,
};

/* ================= 注册 ================= */
/* ================= 注册 ================= */
const app = createApp(RootApp);
app.component("ic", IcComp);
app.component("page-home", PageHome);
app.component("page-data", PageData);
app.component("page-preprocess", PagePreprocess);
app.component("page-classify", PageClassify);
app.component("page-change", PageChange);
app.component("page-predict", PagePredict);
app.component("page-report", PageReport);
app.component("page-settings", PageSettings);
app.component("ds-picker", DsPicker);
app.component("page-files", PageFiles);
app.component("page-detect", PageDetect);
app.component("source-picker", SourcePicker);
app.component("page-ai-settings", PageAiSettings);
app.component("assistant-chat", AssistantChat);
app.component("messages-panel", MessagesPanel);
app.component("file-viewer", FileViewer);
app.mount("#app");
