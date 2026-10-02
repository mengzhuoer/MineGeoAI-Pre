/* 矿地智预 MineGeoAI-Pre · 移动端 · by zhuoer mengzhuoda · 9.20
   ------------------------------------------------------------
   与桌面版共用同一后端（/api/*）与同一批随包库（Vue3 / ECharts / Leaflet），
   但界面不做窗口与桌面隐喻：直接按模块分页，底部标签栏切换。
   ============================================================ */
const { createApp, ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

const AUTHOR = "by zhuoer mengzhuoda · 9.20";
const TOKEN_KEY = "kdzy_m_token";
const DS_KEY = "kdzy_m_dataset";
const DARK_KEY = "kdzy_m_dark";

/* ---------------- 图标（只保留移动端用到的几个） ---------------- */
const _svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
  stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICONS = {
  home: _svg('<path d="M15 21v-8H9v8"/><path d="M3 10a2 2 0 0 1 .7-1.5l7-6a2 2 0 0 1 2.6 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  map: _svg('<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15"/><path d="M15 6v15"/>'),
  chat: _svg('<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
  doc: _svg('<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8l6 6v12a2 2 0 0 1-2 2z"/><path d="M14 2v6h6"/>'),
  user: _svg('<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
  play: _svg('<path d="M5 5a2 2 0 0 1 3-1.7l12 7a2 2 0 0 1 0 3.4l-12 7A2 2 0 0 1 5 19z"/>'),
  pause: _svg('<path d="M7 4h4v16H7z"/><path d="M13 4h4v16h-4z"/>'),
  sun: _svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: _svg('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8"/>'),
  logout: _svg('<path d="m16 17 5-5-5-5"/><path d="M21 12H9"/><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'),
  send: _svg('<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>'),
  refresh: _svg('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
  layers: _svg('<path d="m12 2 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>'),
  location: _svg('<path d="M12 21s7-5.7 7-11a7 7 0 1 0-14 0c0 5.3 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>'),
};

/* ---------------- 通用工具 ---------------- */
function toast(msg, kind) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  if (kind === "err") el.style.background = "rgba(150, 30, 30, .94)";
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}
const fmt = (n, d = 1) => (n === null || n === undefined || isNaN(n)) ? "—"
  : Number(n).toLocaleString("zh-CN", { maximumFractionDigits: d });
const rgbCss = (c) => Array.isArray(c) ? `rgb(${c[0]},${c[1]},${c[2]})` : (c || "#888");

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
    location.reload();
    throw new Error("登录已过期");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
  return data;
}

// 供 modules.js 里的模块组件复用（脚本顺序无关，取的是运行时函数）
window.__kdzyApi = api;
window.__kdzyToast = toast;

/* ================= 登录 ================= */
const LoginView = {
  emits: ["ok"],
  setup(_, { emit }) {
    const username = ref("admin"), password = ref(""), loading = ref(false), err = ref("");
    // 演示导航页预填：入口链接带 ?u=账号&p=密码 时自动填充（仅显式传参才生效）
    try {
      const q = new URLSearchParams(location.search);
      if (q.get("u")) username.value = q.get("u");
      if (q.get("p")) password.value = q.get("p");
    } catch (e) { /* 预填失败不影响登录 */ }
    async function submit() {
      if (loading.value) return;
      loading.value = true; err.value = "";
      try {
        const r = await api("/auth/login", { username: username.value.trim(), password: password.value });
        localStorage.setItem(TOKEN_KEY, r.token);
        emit("ok", r.user);
      } catch (e) { err.value = e.message; }
      loading.value = false;
    }
    return { username, password, loading, err, submit, ICONS };
  },
  template: `
  <div class="login">
    <div class="brand">
      <img src="../assets/logo.png" alt="矿地智预">
      <h1>矿地智预</h1>
      <p>矿区土地利用智能预测系统 · 移动版</p>
    </div>
    <div class="field">
      <label>账号</label>
      <input v-model="username" autocomplete="username" placeholder="admin">
    </div>
    <div class="field">
      <label>密码</label>
      <input v-model="password" type="password" autocomplete="current-password"
             placeholder="默认 123" @keydown.enter="submit">
    </div>
    <button class="btn" :disabled="loading || !password" @click="submit">
      {{ loading ? "登录中…" : "登 录" }}
    </button>
    <div class="err" v-if="err">{{ err }}</div>
    <div class="dim" style="text-align:center; margin-top:18px;">
      离线部署 · 本地推理 · 数据不出本机<br>{{ "by zhuoer mengzhuoda · 9.20" }}
    </div>
  </div>`,
};

/* ================= ① 概览 ================= */
const TabOverview = {
  props: ["meta", "stats"],
  setup(props) {
    const changeEl = ref(null), donutEl = ref(null);
    let c1 = null, c2 = null;
    const years = computed(() => (props.meta ? props.meta.dataset.years : []));
    const lastYear = computed(() => (years.value.length ? years.value[years.value.length - 1] : null));
    const areas = computed(() => (lastYear.value && props.stats[lastYear.value]) || null);
    const miningPct = computed(() => {
      const ys = years.value;
      if (ys.length < 2) return null;
      const pick = (y) => { const s = props.stats[y]; const c = s && s.classes.find(x => x.name === "采矿用地"); return c ? c.area_ha : null; };
      const a = pick(ys[0]), b = pick(ys[ys.length - 1]);
      if (a === null || b === null || a <= 0) return null;
      return Math.round((b - a) / a * 100);
    });
    function render() {
      if (!props.meta) return;
      const st = props.stats, ys = years.value;
      const names = props.meta.dataset.classes.map(c => c.name);
      const base = ((st[String(ys[0])] || {}).classes) || [];
      nextTick(() => {
        if (changeEl.value) {
          if (!c1) c1 = echarts.init(changeEl.value);
          c1.setOption({
            backgroundColor: "transparent",
            grid: { left: 6, right: 10, top: 16, bottom: 2, containLabel: true },
            tooltip: { trigger: "axis", valueFormatter: v => (v > 0 ? "+" : "") + v + " ha" },
            xAxis: { type: "category", data: ys, boundaryGap: false, axisLabel: { fontSize: 10, color: "#7d9179" }, axisTick: { show: false } },
            yAxis: { type: "value", axisLabel: { fontSize: 10, color: "#7d9179" }, splitLine: { lineStyle: { color: "rgba(125,145,121,.22)" } } },
            series: names.map((n, idx) => {
              const b0 = (base.find(x => x.name === n) || {}).area_ha || 0;
              const key = n === "采矿用地";
              return {
                name: n, type: "line", smooth: true, showSymbol: false,
                lineStyle: { width: key ? 3 : 1.6 },
                itemStyle: { color: window.__CLASS_COLORS[n] },
                areaStyle: key ? { opacity: 0.18 } : undefined,
                data: ys.map(y => { const c = ((st[String(y)] || {}).classes || []).find(x => x.name === n); return c ? +(c.area_ha - b0).toFixed(1) : 0; }),
              };
            }),
            animationDuration: 800,
          });
        }
        if (donutEl.value && areas.value) {
          if (!c2) c2 = echarts.init(donutEl.value);
          c2.setOption({
            backgroundColor: "transparent",
            tooltip: { trigger: "item", formatter: p => `${p.name}<br/>${p.value} ha · ${p.percent}%` },
            series: [{
              type: "pie", radius: ["56%", "84%"], center: ["50%", "50%"],
              itemStyle: { borderWidth: 2, borderColor: "rgba(255,255,255,.6)" },
              label: { show: false }, labelLine: { show: false },
              data: areas.value.classes.map(c => ({ name: c.name, value: c.area_ha, itemStyle: { color: rgbCss(c.color) } })),
              animationDuration: 800,
            }],
          });
        }
      });
    }
    watch(() => props.meta, render);
    onMounted(render);
    /* 竖屏转横屏 / 窗口尺寸变化（含录制视口 480→1920）时让图表跟着容器重排，
       否则 canvas 保持初始宽度，窄视口下溢出、宽视口下留白 */
    const onResize = () => { if (c1) c1.resize(); if (c2) c2.resize(); };
    window.addEventListener("resize", onResize);
    onUnmounted(() => {
      window.removeEventListener("resize", onResize);
      if (c1) c1.dispose();
      if (c2) c2.dispose();
    });
    return { changeEl, donutEl, years, lastYear, areas, miningPct, fmt, rgbCss };
  },
  template: `
  <div v-if="meta">
    <div class="section">
      <div class="kpi-grid">
        <div class="kpi" style="--c:#059669">
          <div class="l">研究区面积</div>
          <div class="v">{{ fmt(meta.dataset.area_km2, 2) }}<span class="u">km²</span></div>
          <div class="f">{{ meta.dataset.crs }}</div>
        </div>
        <div class="kpi" style="--c:#0891b2">
          <div class="l">时序数据</div>
          <div class="v">{{ years.length }}<span class="u">期</span></div>
          <div class="f">{{ years[0] }}–{{ years[years.length-1] }} 年</div>
        </div>
        <div class="kpi" style="--c:#d97706">
          <div class="l">空间分辨率</div>
          <div class="v">{{ fmt(meta.dataset.resolution_m, 0) }}<span class="u">m</span></div>
          <div class="f">{{ meta.dataset.classes.length }} 个地类</div>
        </div>
        <div class="kpi" style="--c:#4f46e5">
          <div class="l">矿区</div>
          <div class="v" style="font-size:15px;">{{ meta.dataset.short_name || meta.dataset.region }}</div>
          <div class="f">{{ fmt(areas && areas.total_ha, 0) }} 公顷</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 6px; font-size:13px;">地类面积变化 <span class="dim">相对 {{ years[0] }} 年 · 公顷</span></h2>
      <div class="chart" ref="changeEl"></div>
      <div class="legend">
        <span v-for="c in meta.dataset.classes" :key="c.id"><i :style="{background:c.color}"></i>{{ c.name }}</span>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 6px; font-size:13px;">{{ lastYear }} 年地类结构</h2>
      <div class="donut-wrap">
        <div class="chart donut" ref="donutEl"></div>
        <div class="donut-center" v-if="areas">
          <b>{{ fmt(areas.total_ha, 0) }}</b><i>公顷</i>
        </div>
      </div>
      <div class="callout" v-if="miningPct !== null" style="margin-top:10px;">
        <span>采矿用地 {{ years[0] }} → {{ lastYear }} 增长 <b>+{{ miningPct }}%</b>，是本区土地利用变化的主导驱动</span>
      </div>
    </div>
  </div>
  <div v-else class="loading"><span class="spin"></span>正在读取矿区数据…</div>`,
};

/* ================= ② 地图 ================= */
const TabMap = {
  props: ["meta"],
  setup(props) {
    const el = ref(null), year = ref(null), playing = ref(false), opacity = ref(90);
    const layers = reactive({ shade: true, land: true });
    const pick = ref(null);
    let map = null, shadeL = null, landL = null, timer = null;
    const years = computed(() => (props.meta ? props.meta.dataset.years : []));
    const imgUrl = (y) => `/api/map/landuse/${y}?scale=3&plain=1`;
    const ext = computed(() => (props.meta ? props.meta.dataset.extent : null));

    function bounds() {
      const e = ext.value;
      return [[e.ymin, e.xmin], [e.ymax, e.xmax]];
    }
    function init() {
      if (map || !el.value || !props.meta) return;
      map = L.map(el.value, { crs: L.CRS.Simple, minZoom: -6, maxZoom: -3.25, zoomSnap: 0.25,
                              attributionControl: false, zoomControl: false });
      map.fitBounds(bounds());
      shadeL = L.imageOverlay("/api/map/hillshade?scale=3", bounds(), { opacity: 1 });
      landL = L.imageOverlay(imgUrl(year.value), bounds(), { opacity: opacity.value / 100 });
      if (layers.shade) shadeL.addTo(map);
      if (layers.land) landL.addTo(map);
      L.rectangle(bounds(), { color: "#5a6b7a", weight: 1, dashArray: "4 3", fill: false }).addTo(map);
      L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
      map.on("click", onPick);
      setTimeout(() => { map.invalidateSize(); map.fitBounds(bounds()); }, 150);
    }
    async function onPick(e) {
      try {
        pick.value = await api(`/map/pick?x=${e.latlng.lng.toFixed(1)}&y=${e.latlng.lat.toFixed(1)}&year=${year.value}`);
      } catch (err) { toast(err.message, "err"); }
    }
    function setYear(y) { year.value = y; if (landL) landL.setUrl(imgUrl(y)); pick.value = null; }
    function togglePlay() {
      if (playing.value) { playing.value = false; clearInterval(timer); return; }
      playing.value = true;
      timer = setInterval(() => {
        const ys = years.value, i = ys.indexOf(year.value);
        setYear(ys[(i + 1) % ys.length]);
      }, 1100);
    }
    watch([opacity], () => { if (landL) landL.setOpacity(opacity.value / 100); });
    watch(layers, () => {
      if (!map) return;
      if (layers.shade) { if (!map.hasLayer(shadeL)) shadeL.addTo(map); } else if (map.hasLayer(shadeL)) map.removeLayer(shadeL);
      if (layers.land) { if (!map.hasLayer(landL)) landL.addTo(map); } else if (map.hasLayer(landL)) map.removeLayer(landL);
    }, { deep: true });
    watch(() => props.meta, () => {
      const ys = years.value;
      year.value = ys.length ? ys[ys.length - 1] : null;
      if (map) { map.remove(); map = null; shadeL = landL = null; }
      nextTick(init);
    });
    onMounted(() => {
      const ys = years.value;
      year.value = ys.length ? ys[ys.length - 1] : null;
      nextTick(init);
    });
    onUnmounted(() => { clearInterval(timer); if (map) { map.remove(); map = null; } });
    return { el, year, years, playing, opacity, layers, pick, setYear, togglePlay, rgbCss, fmt, ICONS };
  },
  template: `
  <div v-if="meta">
    <div id="map" ref="el"></div>
    <div class="map-bar">
      <button class="pill" @click="togglePlay">{{ playing ? "⏸ 暂停" : "▶ 播放" }}</button>
      <button v-for="y in years" :key="y" class="pill" :class="{ on: y === year }" @click="setYear(y)">{{ y }}</button>
    </div>
    <div class="card" style="margin-top:10px;">
      <div class="readout">
        <template v-if="pick && pick.inside">
          <span class="swatch" :style="{ background: rgbCss(pick.color) }"></span>
          <b>{{ pick.class }}</b>
          <span class="muted">{{ pick.year }} 年 · {{ fmt(pick.class_area_ha) }} 公顷（占 {{ pick.class_percent }}%）</span>
          <span class="dim">{{ pick.x }}, {{ pick.y }} m</span>
        </template>
        <span v-else-if="pick" class="muted">点在图幅外</span>
        <span v-else class="muted">点一下地图，查询该点地类</span>
      </div>
      <div class="switch-row" style="margin-top:12px;">
        <label><input type="checkbox" v-model="layers.shade"> 山体阴影</label>
        <label><input type="checkbox" v-model="layers.land"> 土地利用</label>
        <label>透明度 <input type="range" min="20" max="100" v-model.number="opacity"></label>
      </div>
      <div class="legend" style="margin-top:10px;">
        <span v-for="c in meta.dataset.classes" :key="c.id"><i :style="{background:c.color}"></i>{{ c.name }}</span>
      </div>
    </div>
  </div>
  <div v-else class="loading"><span class="spin"></span>正在准备地图…</div>`,
};

/* ================= ③ 图图 ================= */
const TabChat = {
  props: ["meta"],
  emits: ["goto"],
  setup(props, { emit }) {
    const msgs = ref([]), draft = ref(""), busy = ref(false), listEl = ref(null);
    const PRESETS = ["矿区现在的耕地和林地各有多少？", "过去二十年变化最大的地类是什么？", "2030 年生态优先情景有什么建议？", "Kappa 系数怎么理解？"];
    async function send(text) {
      const q = (text !== undefined ? text : draft.value).trim();
      if (!q || busy.value) return;
      draft.value = "";
      msgs.value.push({ role: "user", text: q });
      busy.value = true;
      scroll();
      try {
        const r = await api("/assistant/chat", { question: q, history: msgs.value.slice(0, -1).map(m => ({ role: m.role === "user" ? "user" : "assistant", content: m.text })) });
        msgs.value.push({ role: "ai", text: r.answer || "（无回答）", refs: (r.references || []).length,
                          meta: (r.provider === "local" ? "本地" : "云端") + " · " + r.seconds + "s",
                          actions: r.actions || [] });
      } catch (e) {
        msgs.value.push({ role: "ai", text: "调用失败：" + e.message, err: true });
      }
      busy.value = false;
      scroll();
    }
    function scroll() { nextTick(() => { if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight; }); }
    return { msgs, draft, busy, listEl, PRESETS, send, ICONS };
  },
  template: `
  <div class="section" style="margin-bottom:0;">
    <div class="chat-list" ref="listEl">
      <div v-if="!msgs.length" class="card">
        <div style="font-weight:600; margin-bottom:4px;">你好，我是图图</div>
        <div class="muted">我可以解读当前矿区的数据、解释遥感与地信概念。</div>
        <div class="chips">
          <button v-for="p in PRESETS" :key="p" class="chip" @click="send(p)">{{ p }}</button>
        </div>
      </div>
      <template v-for="(m, i) in msgs" :key="i">
        <div class="bub" :class="m.role === 'user' ? 'me' : 'ai'" v-if="m.role !== 'sys'">{{ m.text }}</div>
        <div class="bub sys" v-else>{{ m.text }}</div>
        <div class="meta-line" v-if="m.role === 'ai' && m.meta">{{ m.meta }} · 知识库 {{ m.refs }} 条</div>
      </template>
      <div v-if="busy" class="bub ai"><span class="dim">图图思考中…</span></div>
    </div>
  </div>
  <div class="composer">
    <textarea v-model="draft" rows="1" placeholder="问点什么…" @keydown.enter.prevent="send()"></textarea>
    <button class="send" :disabled="busy || !draft.trim()" @click="send()">
      <span style="display:flex;" v-html="ICONS.send"></span></button>
  </div>`,
};

/* ================= ④ 报告 ================= */
const TabReports = {
  props: ["meta"],
  setup(props) {
    const items = ref([]), busy = ref(false), tpl = ref("comprehensive"), fmtv = ref("docx"), loading = ref(true);
    async function load() {
      loading.value = true;
      try { items.value = (await api("/report/list")).items || []; }
      catch (e) { toast(e.message, "err"); }
      loading.value = false;
    }
    async function make() {
      busy.value = true;
      try {
        const r = await api("/report", { template: tpl.value, format: fmtv.value });
        toast("已生成：" + r.filename);
        await load();
      } catch (e) { toast(e.message, "err"); }
      busy.value = false;
    }
    function download(name) {
      // 下载走浏览器原生：登录时后端已种下 Cookie，img/a 这类请求也能通过鉴权
      window.open("/api/report/download/" + encodeURIComponent(name), "_blank");
    }
    onMounted(load);
    return { items, busy, tpl, fmtv, loading, load, make, download };
  },
  template: `
  <div class="section">
    <div class="card">
      <h2 style="margin:0 0 8px; font-size:13px;">生成新报告</h2>
      <select v-model="tpl">
        <option v-for="t in (meta ? meta.templates : [])" :key="t.id" :value="t.id">{{ t.name }}</option>
      </select>
      <div class="actions" style="margin-top:10px;">
        <select v-model="fmtv" style="flex:1;">
          <option value="docx">Word (.docx)</option>
          <option value="pdf">PDF</option>
        </select>
        <button class="btn" style="flex:1.4;" :disabled="busy" @click="make">{{ busy ? "生成中…" : "生成" }}</button>
      </div>
      <div class="dim" style="margin-top:8px;">报告在本机生成，含图件与统计表，可直接下载或带走。</div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 4px; font-size:13px;">历史报告 <span class="dim">共 {{ items.length }} 份</span></h2>
      <div v-if="loading" class="loading"><span class="spin"></span>读取中…</div>
      <div v-else-if="!items.length" class="muted" style="padding:10px 0;">还没有报告，先在上面生成一份。</div>
      <div v-for="it in items" :key="it.filename" class="row" @click="download(it.filename)">
        <span class="tag" :class="it.format">{{ it.format.toUpperCase() }}</span>
        <div class="main">
          <div class="name">{{ it.filename }}</div>
          <div class="sub">{{ it.time }} · {{ it.size_kb }} KB</div>
        </div>
        <span class="dim">下载</span>
      </div>
    </div>
  </div>`,
};

/* ================= ⑤ 我的 ================= */
const TabMe = {
  props: ["user", "meta", "dark", "dsId"],
  emits: ["logout", "toggle-dark", "pick-dataset"],
  setup(props, { emit }) {
    const llm = ref(null);
    onMounted(async () => {
      try { llm.value = await api("/llm/status"); } catch (e) { /* 离线容错 */ }
    });
    return { llm, emit, AUTHOR };
  },
  template: `
  <div class="section">
    <div class="card">
      <div class="row" style="border:0; padding-top:0;">
        <span class="tag">{{ user && user.role === "super" ? "超级管理员" : "标准用户" }}</span>
        <div class="main">
          <div class="name">{{ user ? user.username : "—" }}</div>
          <div class="sub">已登录 · 数据保存在本机</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 8px; font-size:13px;">矿区数据库</h2>
      <select :value="dsId" @change="$emit('pick-dataset', $event.target.value)">
        <option v-for="d in (meta ? meta.datasets : [])" :key="d.id" :value="d.id" :selected="d.id === dsId">
          {{ d.short_name || d.region }} · {{ d.area_km2 }} km²
        </option>
      </select>
      <div class="dim" style="margin-top:8px;">切换后会重新载入该矿区的统计、地图与知识库上下文。</div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 8px; font-size:13px;">图图（AI 助手）</h2>
      <div class="row" style="border:0; padding:0;">
        <span class="tag">{{ llm && llm.local && llm.local.ready ? "本地模型" : (llm && llm.api && llm.api.configured ? "云端接口" : "未就绪") }}</span>
        <div class="main">
          <div class="name">{{ llm && llm.local ? (llm.local.model || "未找到模型文件") : "检测中…" }}</div>
          <div class="sub">{{ llm && llm.local && llm.local.model_mb ? llm.local.model_mb + " MB · 离线推理" : "在桌面版的「图图设置」里配置" }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="switch-row" style="justify-content:space-between;">
        <span>深色模式</span>
        <button class="icon-btn" @click="$emit('toggle-dark')">
          <span v-html="dark ? '☀' : '☾'" style="font-size:17px;"></span>
        </button>
      </div>
    </div>

    <button class="btn ghost" @click="$emit('logout')">退出登录</button>
    <div class="dim" style="text-align:center; margin-top:16px; line-height:1.9;">
      矿地智预 MineGeoAI-Pre · 移动版<br>{{ AUTHOR }}
    </div>
  </div>`,
};

/* ================= 数据页（地图 + 明细 + 两期对比） ================= */
const TabData = {
  components: { TabMap },
  props: ["meta", "stats"],
  setup(props) {
    const view = ref("map");                      // map | table | compare
    const years = computed(() => (props.meta ? props.meta.dataset.years : []));
    const cmpA = ref(null), cmpB = ref(null), pos = ref(50), el = ref(null);
    let dragging = false;
    const imgUrl = (y) => `/api/map/landuse/${y}?scale=3`;
    function moveTo(clientX) {
      const r = el.value.getBoundingClientRect();
      pos.value = Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100));
    }
    function start(e) { dragging = true; moveTo(e.clientX);
      window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", end); }
    function onMove(e) { if (dragging) moveTo(e.clientX); }
    function end() { dragging = false;
      window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", end); }
    onMounted(() => { const ys = years.value; cmpA.value = ys[0]; cmpB.value = ys[ys.length - 1]; });
    return { view, years, cmpA, cmpB, pos, el, imgUrl, start, fmt, CLASS_COLORS: window.__CLASS_COLORS };
  },
  template: `
  <div v-if="meta">
    <div class="seg-row">
      <button class="pill" :class="{ on: view === 'map' }" @click="view = 'map'">交互地图</button>
      <button class="pill" :class="{ on: view === 'table' }" @click="view = 'table'">数据明细</button>
      <button class="pill" :class="{ on: view === 'compare' }" @click="view = 'compare'">两期对比</button>
    </div>

    <TabMap v-if="view === 'map'" :meta="meta" />

    <div v-else-if="view === 'table'" class="card">
      <h2>五期地类面积 <span class="dim">公顷</span></h2>
      <div class="tbl-wrap">
        <table class="mini wide">
          <thead><tr><th>年份</th><th>总面积</th><th v-for="c in meta.dataset.classes" :key="c.id">{{ c.name }}</th></tr></thead>
          <tbody>
            <tr v-for="y in years" :key="y">
              <td><strong>{{ y }}</strong></td>
              <td>{{ fmt(stats[y].total_ha, 0) }}</td>
              <td v-for="c in meta.dataset.classes" :key="c.id">
                {{ fmt((stats[y].classes.find(x => x.name === c.name) || {}).area_ha, 0) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="dim" style="margin-top:8px;">左右滑动可看完整表格</div>
    </div>

    <div v-else>
      <div class="two-col" style="margin-bottom:10px;">
        <select v-model.number="cmpA"><option v-for="y in years" :key="y" :value="y">{{ y }} 年（左）</option></select>
        <select v-model.number="cmpB"><option v-for="y in years" :key="y" :value="y">{{ y }} 年（右）</option></select>
      </div>
      <div class="cmp-wrap" ref="el" @pointerdown="start">
        <img class="cmp-img" :src="imgUrl(cmpB)" alt="B">
        <div class="cmp-top" :style="{ clipPath: 'inset(0 ' + (100 - pos) + '% 0 0)' }">
          <img class="cmp-img" :src="imgUrl(cmpA)" alt="A">
        </div>
        <div class="cmp-handle" :style="{ left: pos + '%' }"></div>
        <span class="cmp-tag left">{{ cmpA }} 年</span>
        <span class="cmp-tag right">{{ cmpB }} 年</span>
      </div>
      <div class="dim" style="margin-top:8px;">拖动分割线比较两期；定量结论见「变化分析」的转移矩阵。</div>
    </div>
  </div>`,
};

/* ================= 功能页（所有模块入口） ================= */
/* 图标与桌面版统一：桌面默认风格是「实心科技」位图，手机端直接复用同一套 PNG */
const TECH_ICO = { detect: "detect", preprocess: "preprocess", classify: "classify",
                   change: "change", predict: "predict", report: "report",
                   files: "files", aisettings: "ai-settings" };
const TabFunctions = {
  props: ["modules"],
  emits: ["open"],
  setup() {
    const hasIco = (m) => !!TECH_ICO[m.id];
    const icoStyle = (m) => hasIco(m)
      ? { backgroundImage: 'url("../assets/icons/tech/' + TECH_ICO[m.id] + '-128.png")' } : {};
    return { ICONS, hasIco, icoStyle };
  },
  template: `
  <div class="section">
    <div class="card">
      <h2>全部功能 <span class="dim">{{ modules.length }} 个模块</span></h2>
      <div class="mod-grid">
        <button v-for="m in modules" :key="m.id" class="mod" @click="$emit('open', m.id)">
          <span class="mod-ic" :class="{ 'ico-img': hasIco(m) }" :style="icoStyle(m)"
                v-html="ICONS[m.icon]"></span>
          <span class="mod-txt">
            <b>{{ m.label }}</b>
            <i>{{ m.desc }}</i>
          </span>
        </button>
      </div>
    </div>
    <div class="card">
      <h2>模块与桌面版对应</h2>
      <div class="dim" style="line-height:1.9;">
        桌面版的 12 个应用在手机上都能打开：概览、数据（地图/明细/对比）、图图、报告、检测、
        预处理、分类、变化、预测、文件、图图设置、我的。手机端针对触屏重做了布局，
        接口与算法和桌面版完全一致。
      </div>
    </div>
  </div>`,
};

/* ================= 外壳 ================= */
const App = {
  components: { LoginView, TabOverview, TabData, TabChat, TabFunctions, TabReports, TabMe },
  setup() {
    const authed = ref(false), user = ref(null), meta = ref(null), tab = ref("overview");
    const page = ref(null);                       // 打开的模块子页（null=标签页）
    const dark = ref(localStorage.getItem(DARK_KEY) === "1");
    const dsId = ref(localStorage.getItem(DS_KEY) || "");
    const modules = window.KDZY_MODULES || [];
    const TABS = [
      { id: "overview", label: "概览", icon: "home" },
      { id: "data", label: "数据", icon: "map" },
      { id: "chat", label: "图图", icon: "chat" },
      { id: "tools", label: "功能", icon: "layers" },
      { id: "me", label: "我的", icon: "user" },
    ];
    const stats = computed(() => {
      if (!meta.value) return {};
      const out = {};
      for (const [y, v] of Object.entries(meta.value.stats || {})) out[Number(y)] = v;
      return out;
    });
    const current = computed(() => TABS.find(t => t.id === tab.value) || TABS[0]);
    const openMod = computed(() => page.value ? modules.find(m => m.id === page.value) : null);
    const title = computed(() => (openMod.value ? openMod.value.label : current.value.label));

    watch(dark, (v) => {
      document.body.dataset.dark = v ? "1" : "0";
      localStorage.setItem(DARK_KEY, v ? "1" : "0");
      setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
    }, { immediate: true });

    async function loadMeta() {
      meta.value = await api("/meta");
      // 当前数据集 id 在顶层 dataset_id（dataset 对象里没有 id）
      if (!dsId.value) {
        dsId.value = meta.value.dataset_id || (meta.value.datasets && meta.value.datasets[0] || {}).id || "";
        if (dsId.value) localStorage.setItem(DS_KEY, dsId.value);
      }
      window.__CLASS_COLORS = {};
      (meta.value.dataset.classes || []).forEach(c => { window.__CLASS_COLORS[c.name] = c.color; });
      document.title = "矿地智预 · " + (meta.value.dataset.short_name || "矿区土地利用");
    }
    async function boot() {
      if (!localStorage.getItem(TOKEN_KEY)) return;
      try {
        const me = await api("/auth/me");
        user.value = me.user;
        authed.value = true;
        await loadMeta();
      } catch (e) { /* 未登录或过期 */ }
    }
    async function onLogin(u) {
      user.value = u;
      authed.value = true;
      try { await loadMeta(); } catch (e) { toast(e.message, "err"); }
    }
    function pickDataset(id) {
      dsId.value = id;
      localStorage.setItem(DS_KEY, id);
      loadMeta().then(() => toast("已切换到 " + (meta.value.dataset.short_name || id))).catch(e => toast(e.message, "err"));
    }
    async function logout() {
      try { await api("/auth/logout", {}); } catch (e) { /* 忽略 */ }
      localStorage.removeItem(TOKEN_KEY);
      location.reload();
    }
    onMounted(boot);
    return { authed, user, meta, tab, page, dark, dsId, stats, TABS, modules, current, title,
             onLogin, pickDataset, logout, ICONS, openMod };
  },
  template: `
  <LoginView v-if="!authed" @ok="onLogin" />
  <div class="app" v-else>
    <div class="topbar">
      <button v-if="page" class="icon-btn" @click="page = null" title="返回">‹</button>
      <img v-else class="logo" src="../assets/logo.png" alt="">
      <div class="tt">
        <b>{{ page ? title : '矿地智预' }}</b>
        <i>{{ meta ? (meta.dataset.short_name || '矿区') : '加载中' }}{{ page ? '' : ' · ' +  title }}</i>
      </div>
      <div class="spacer"></div>
      <button class="icon-btn" @click="tab = 'chat'; page = null" title="问图图">
        <span style="display:flex;" v-html="ICONS.chat"></span></button>
    </div>

    <div class="content" :style="tab === 'chat' && !page ? 'padding-bottom: calc(var(--tab-h) + env(safe-area-inset-bottom, 0px) + 86px)' : ''">
      <component v-if="page && openMod && openMod.comp" :is="openMod.comp" :meta="meta" />
      <div v-else-if="page" class="loading"><span class="spin"></span>该模块正在开发…</div>

      <template v-else>
        <TabOverview v-if="tab === 'overview'" :meta="meta" :stats="stats" />
        <TabData v-else-if="tab === 'data'" :meta="meta" :stats="stats" />
        <TabChat v-else-if="tab === 'chat'" :meta="meta" />
        <TabFunctions v-else-if="tab === 'tools'" :modules="modules" @open="page = $event" />
        <TabMe v-else :user="user" :meta="meta" :dark="dark" :ds-id="dsId"
               @logout="logout" @toggle-dark="dark = !dark" @pick-dataset="pickDataset" @open="page = $event" />
      </template>
    </div>

    <div class="tabbar" v-if="!page">
      <button v-for="t in TABS" :key="t.id" class="tab" :class="{ on: tab === t.id }" @click="tab = t.id">
        <span v-html="ICONS[t.icon]" style="display:flex;"></span>
        <span>{{ t.label }}</span>
      </button>
    </div>
  </div>`,
};

// 把桌面版已有的「报告」组件挂到模块登记表上（登记表由 modules.js 提供）
(function () {
  const m = (window.KDZY_MODULES || []).find(x => x.id === "report");
  if (m) m.comp = TabReports;
})();
const app = createApp(App);
app.mount("#app");
console.log("%c矿地智预 MineGeoAI-Pre · 移动版 · " + AUTHOR, "color:#4f46e5;font-weight:700");
