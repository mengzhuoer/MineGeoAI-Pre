/* 矿地智预 MineGeoAI-Pre · 移动版功能模块 · by zhuoer mengzhuoda · 9.20
   ------------------------------------------------------------
   把桌面版的 12 个应用在手机上补齐：这里登记模块清单与各自的参数表单，
   结果统一交给 ResultView 渲染——它按"数字→指标卡 / 图片→缩略图 /
   对象数组→表格 / 二维数组→矩阵 / 嵌套对象→小节"自动排布，
   所以后端加字段也不用改界面，且显示的一定是后端真实返回的内容。
   ============================================================ */
(function () {
  const { ref, reactive, computed, nextTick, watch } = Vue;
  // 运行时再取（app.js 与本文件的加载顺序就不重要了）
  const api = (...a) => window.__kdzyApi(...a);

  /* ---------------- 通用结果渲染 ---------------- */
  const IMG_RE = /^\/api\/img\/|\.png$|\.jpg$|_url$|^images?\./i;
  const isImg = (k, v) => typeof v === "string" && (v.startsWith("/api/img/") || /\.(png|jpe?g)$/i.test(v)) && !k.includes("title");
  const isNumTable = (v) => Array.isArray(v) && v.length && v.every(r => typeof r === "number");
  const isObjTable = (v) => Array.isArray(v) && v.length && v.every(r => r && typeof r === "object");

  const ResultView = {
    props: ["data", "title"],
    setup(props) {
      const NAMES = { overall_accuracy: "总体精度 OA", kappa: "Kappa", n_train: "训练样本", n_test: "测试样本",
        changed_percent: "变化像元占比", changed_pixels: "变化像元数", cloud_detected_pct: "云检出率",
        radiometric_error_pct: "辐射误差", completeness: "数据完整性", model_name: "模型", scenario_name: "情景",
        algorithm_name: "算法", year: "年份", a_year: "前期", b_year: "后期", final_year: "目标年", source: "数据来源" };
      const PCT = new Set(["overall_accuracy", "changed_percent", "cloud_detected_pct", "cloud_recall_pct", "completeness", "cloud_overdetect_pct", "radiometric_error_pct"]);
      const entries = computed(() => Object.entries(props.data || {}));
      const images = computed(() => entries.value.filter(([k, v]) => isImg(k, v)));
      // 图片地址不要再当成指标卡显示（否则会看到一长串 URL），超长文本同理
      const scalars = computed(() => entries.value.filter(([k, v]) =>
        (typeof v !== "object" || v === null) && !isImg(k, v) && String(v).length <= 40));
      const nested = computed(() => entries.value.filter(([k, v]) => v && typeof v === "object" && !isImg(k, v)));
      const show = (k) => (NAMES[k] || k);
      const num = (v) => typeof v === "number" ? (Number.isInteger(v) ? v : +v.toFixed(3)) : v;
      const val = (k, v) => PCT.has(k) ? num(v) + "%" : num(v);
      const fmtCell = (v) => (typeof v === "number" ? (Number.isInteger(v) ? v : +v.toFixed(3)) : (v === null ? "—" : String(v)));
      const cols = (arr) => Object.keys(arr[0]).slice(0, 6);
      return { scalars, images, nested, show, val, cols, fmtCell, isNumTable, isObjTable };
    },
    template: `
    <div>
      <div class="card" v-if="scalars.length">
        <h2>结果概览</h2>
        <div class="kpi-grid">
          <div class="kpi" v-for="[k, v] in scalars" :key="k">
            <div class="l">{{ show(k) }}</div>
            <div class="v" :style="String(val(k, v)).length > 10 ? 'font-size:14px' : ''">{{ val(k, v) }}</div>
          </div>
        </div>
      </div>

      <div class="card" v-if="images.length">
        <h2>图件</h2>
        <div class="thumb-row">
          <a v-for="[k, v] in images" :key="k" class="thumb" :href="v" target="_blank">
            <img :src="v" :alt="k"><span>{{ k }}</span>
          </a>
        </div>
      </div>

      <template v-for="[k, v] in nested" :key="k">
        <div class="card" v-if="!Array.isArray(v)">
          <h2>{{ show(k) }}</h2>
          <div class="kv">
            <div class="kv-row" v-for="[kk, vv] in Object.entries(v)" :key="kk">
              <span class="kv-k">{{ kk }}</span>
              <span class="kv-v">{{ typeof vv === 'object' ? JSON.stringify(vv) : fmtCell(vv) }}</span>
            </div>
          </div>
        </div>
        <div class="card" v-else-if="isObjTable(v)">
          <h2>{{ show(k) }} <span class="dim">{{ v.length }} 条</span></h2>
          <div class="tbl-wrap">
            <table class="mini">
              <thead><tr><th v-for="c in cols(v)" :key="c">{{ c }}</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in v" :key="i">
                  <td v-for="c in cols(v)" :key="c">{{ fmtCell(r[c]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="card" v-else-if="isNumTable(v)">
          <h2>{{ show(k) }} <span class="dim">矩阵</span></h2>
          <div class="tbl-wrap">
            <table class="mini">
              <tbody><tr v-for="(row, i) in v" :key="i"><td v-for="(c, j) in row" :key="j">{{ fmtCell(c) }}</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="card" v-else>
          <h2>{{ show(k) }}</h2>
          <div class="kv"><div class="kv-row"><span class="kv-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
      </template>
    </div>`,
  };

  /* ---------------- 预处理 ---------------- */
  const PreprocessModule = {
    components: { ResultView },
    props: ["meta"],
    setup(props) {
      const year = ref(null), busy = ref(false), out = ref(null);
      onMounted(() => { const ys = props.meta.dataset.years; year.value = ys[ys.length - 1]; });
      async function run() {
        busy.value = true; out.value = null;
        try { out.value = await api("/preprocess", { year: year.value }); }
        catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      return { year, busy, out, run };
    },
    template: `
    <div>
      <div class="card">
        <h2>参数</h2>
        <div class="field"><label>年份</label>
          <select v-model.number="year"><option v-for="y in meta.dataset.years" :key="y" :value="y">{{ y }} 年</option></select>
        </div>
        <button class="btn" :disabled="busy" @click="run">{{ busy ? "处理中…" : "运行预处理链路" }}</button>
        <div class="dim" style="margin-top:8px;">辐射定标 → 大气校正 → 去云去噪 → 质量检验，全部在本机计算。</div>
      </div>
      <div v-if="busy" class="loading"><span class="spin"></span>正在处理…</div>
      <ResultView v-if="out" :data="out" />
    </div>`,
  };

  /* ---------------- 分类 ---------------- */
  const ClassifyModule = {
    components: { ResultView },
    props: ["meta"],
    setup(props) {
      const year = ref(null), algorithm = ref("rf"), trainRatio = ref(0.35), busy = ref(false), out = ref(null);
      const ALGOS = [{ id: "rf", name: "随机森林" }, { id: "svm", name: "支持向量机" }, { id: "knn", name: "KNN" }];
      onMounted(() => { const ys = props.meta.dataset.years; year.value = ys[ys.length - 1]; });
      async function run() {
        busy.value = true; out.value = null;
        try { out.value = await api("/classify", { year: year.value, algorithm: algorithm.value, train_ratio: trainRatio.value }); }
        catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      return { year, algorithm, trainRatio, ALGOS, busy, out, run };
    },
    template: `
    <div>
      <div class="card">
        <h2>参数</h2>
        <div class="field"><label>年份</label>
          <select v-model.number="year"><option v-for="y in meta.dataset.years" :key="y" :value="y">{{ y }} 年</option></select>
        </div>
        <div class="field"><label>算法</label>
          <div class="pill-row">
            <button v-for="a in ALGOS" :key="a.id" class="pill" :class="{ on: algorithm === a.id }" @click="algorithm = a.id">{{ a.name }}</button>
          </div>
        </div>
        <div class="field"><label>训练样本比例：{{ Math.round(trainRatio * 100) }}%</label>
          <input type="range" min="5" max="80" step="5" v-model.number="trainRatio">
        </div>
        <button class="btn" :disabled="busy" @click="run">{{ busy ? "分类中…" : "开始分类" }}</button>
      </div>
      <div v-if="busy" class="loading"><span class="spin"></span>正在训练与预测…</div>
      <ResultView v-if="out" :data="out" />
    </div>`,
  };

  /* ---------------- 变化分析 ---------------- */
  const ChangeModule = {
    components: { ResultView },
    props: ["meta"],
    setup(props) {
      const ys = props.meta.dataset.years;
      const aYear = ref(ys[0]), bYear = ref(ys[ys.length - 1]), busy = ref(false), out = ref(null);
      async function run() {
        busy.value = true; out.value = null;
        try { out.value = await api("/change", { a_year: aYear.value, b_year: bYear.value }); }
        catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      return { ys, aYear, bYear, busy, out, run };
    },
    template: `
    <div>
      <div class="card">
        <h2>参数</h2>
        <div class="two-col">
          <div class="field"><label>前期</label>
            <select v-model.number="aYear"><option v-for="y in ys" :key="y" :value="y">{{ y }} 年</option></select>
          </div>
          <div class="field"><label>后期</label>
            <select v-model.number="bYear"><option v-for="y in ys" :key="y" :value="y">{{ y }} 年</option></select>
          </div>
        </div>
        <button class="btn" :disabled="busy || aYear === bYear" @click="run">{{ busy ? "计算中…" : "分析两期变化" }}</button>
        <div class="dim" v-if="aYear === bYear" style="margin-top:8px;">请选择两个不同年份。</div>
      </div>
      <div v-if="busy" class="loading"><span class="spin"></span>正在统计转移矩阵…</div>
      <ResultView v-if="out" :data="out" />
    </div>`,
  };

  /* ---------------- 预测建模 ---------------- */
  const PredictModule = {
    components: { ResultView },
    props: ["meta"],
    setup(props) {
      const ys = props.meta.dataset.years;
      const model = ref("ca-markov"), scenario = ref("natural"), target = ref(2030);
      const busy = ref(false), out = ref(null);
      const SCEN = [{ id: "natural", name: "常规开采" }, { id: "intensive", name: "强化开采" },
                    { id: "eco", name: "生态优先" }, { id: "balanced", name: "综合平衡" }];
      async function run() {
        busy.value = true; out.value = null;
        try { out.value = await api("/predict", { model: model.value, a_year: ys[0], b_year: ys[ys.length - 1], target_year: target.value, scenario: scenario.value }); }
        catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      return { model, scenario, target, SCEN, busy, out, run };
    },
    template: `
    <div>
      <div class="card">
        <h2>参数</h2>
        <div class="field"><label>模型</label>
          <div class="pill-row">
            <button class="pill" :class="{ on: model === 'ca-markov' }" @click="model = 'ca-markov'">CA-Markov</button>
            <button class="pill" :class="{ on: model === 'clue-s' }" @click="model = 'clue-s'">CLUE-S</button>
          </div>
        </div>
        <div class="field"><label>情景</label>
          <div class="pill-row">
            <button v-for="s in SCEN" :key="s.id" class="pill" :class="{ on: scenario === s.id }" @click="scenario = s.id">{{ s.name }}</button>
          </div>
        </div>
        <div class="field"><label>目标年：{{ target }}</label>
          <input type="range" min="2025" max="2050" step="5" v-model.number="target">
        </div>
        <button class="btn" :disabled="busy" @click="run">{{ busy ? "推演中…" : "开始预测" }}</button>
      </div>
      <div v-if="busy" class="loading"><span class="spin"></span>正在推演土地利用格局…</div>
      <ResultView v-if="out" :data="out" />
    </div>`,
  };

  /* ---------------- 图像检测（手机最大优势：拍照即检测） ---------------- */
  const DetectModule = {
    components: { ResultView },
    props: ["meta"],
    setup(props) {
      const file = ref(null), fileId = ref(null), info = ref(null), mode = ref("disturb");
      const busy = ref(false), uploading = ref(false), out = ref(null), fileInput = ref(null);
      const MODES = [{ id: "disturb", name: "扰动检测" }, { id: "classify", name: "地类分类" },
                     { id: "compare", name: "与数据库比对" }];
      async function upload(ev) {
        const f = ev.target.files && ev.target.files[0];
        if (!f) return;
        uploading.value = true; out.value = null; info.value = null;
        const fd = new FormData();
        fd.append("file", f);
        try {
          const r = await fetch("/api/files/upload?folder=%2F", {
            method: "POST",
            headers: Object.assign({}, localStorage.getItem("kdzy_m_token") ? { Authorization: "Bearer " + localStorage.getItem("kdzy_m_token") } : {},
                                  localStorage.getItem("kdzy_m_dataset") ? { "X-Dataset": localStorage.getItem("kdzy_m_dataset") } : {}),
            body: fd,
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail || "上传失败");
          fileId.value = d.id || (d.file && d.file.id);
          file.value = d.name || f.name;
          info.value = await api("/image/inspect?file_id=" + fileId.value);
        } catch (e) { window.__kdzyToast(e.message, "err"); }
        uploading.value = false;
      }
      async function run() {
        if (!fileId.value) { window.__kdzyToast("请先拍照或选择影像", "err"); return; }
        busy.value = true; out.value = null;
        try {
          out.value = await api("/image/detect", { file_id: fileId.value, mode: mode.value, year: props.meta.dataset.years.slice(-1)[0] });
        } catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      return { file, fileId, info, mode, MODES, busy, uploading, out, fileInput, upload, run };
    },
    template: `
    <div>
      <div class="card">
        <h2>导入影像</h2>
        <input ref="fileInput" type="file" accept="image/*,.tif,.tiff" style="display:none" @change="upload">
        <button class="btn" :disabled="uploading" @click="$refs.fileInput.click()">
          {{ uploading ? "上传中…" : (fileId ? "重新选择影像" : "拍照 / 选择影像") }}
        </button>
        <div class="dim" style="margin-top:8px;">
          支持 GeoTIFF / TIFF / jpg / png；手机可直接调用相机拍矿区照片。
        </div>
        <div class="kv" v-if="info" style="margin-top:10px;">
          <div class="kv-row"><span class="kv-k">文件</span><span class="kv-v">{{ file }}</span></div>
          <div class="kv-row" v-for="[k, v] in Object.entries(info).slice(0, 6)" :key="k">
            <span class="kv-k">{{ k }}</span>
            <span class="kv-v">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>检测模式</h2>
        <div class="pill-row">
          <button v-for="m in MODES" :key="m.id" class="pill" :class="{ on: mode === m.id }" @click="mode = m.id">{{ m.name }}</button>
        </div>
        <button class="btn" style="margin-top:12px;" :disabled="busy || !fileId" @click="run">
          {{ busy ? "检测中…" : "开始检测" }}
        </button>
      </div>
      <div v-if="busy" class="loading"><span class="spin"></span>正在检测…</div>
      <ResultView v-if="out" :data="out" />
    </div>`,
  };

  /* ---------------- 文件管理 ---------------- */
  const FilesModule = {
    setup() {
      const items = ref([]), loading = ref(true), folder = ref("/"), upBusy = ref(false), el = ref(null);
      const used = ref({ used: 0, quota: 0 });
      async function load() {
        loading.value = true;
        try {
          const r = await api("/files?folder=" + encodeURIComponent(folder.value));
          items.value = r.items || [];
          used.value = { used: r.used, quota: r.quota };
        } catch (e) { window.__kdzyToast(e.message, "err"); }
        loading.value = false;
      }
      async function upload(ev) {
        const f = ev.target.files && ev.target.files[0];
        if (!f) return;
        upBusy.value = true;
        const fd = new FormData(); fd.append("file", f);
        try {
          const r = await fetch("/api/files/upload?folder=" + encodeURIComponent(folder.value), {
            method: "POST",
            headers: Object.assign({}, { Authorization: "Bearer " + localStorage.getItem("kdzy_m_token") },
                                  localStorage.getItem("kdzy_m_dataset") ? { "X-Dataset": localStorage.getItem("kdzy_m_dataset") } : {}),
            body: fd,
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail || "上传失败");
          window.__kdzyToast("已上传：" + (d.name || f.name));
          await load();
        } catch (e) { window.__kdzyToast(e.message, "err"); }
        upBusy.value = false;
      }
      async function del(it) {
        if (!confirm("删除「" + it.name + "」？")) return;
        try { await api("/files/delete", { id: it.id }); await load(); window.__kdzyToast("已删除"); }
        catch (e) { window.__kdzyToast(e.message, "err"); }
      }
      function enter(it) { folder.value = folder.value + it.name + "/"; load(); }
      function up() { folder.value = folder.value.replace(/[^/]+\/$/, "") || "/"; load(); }
      const pct = computed(() => used.value.quota ? Math.round(used.value.used / used.value.quota * 100) : 0);
      const mb = (b) => (b / 1024 / 1024).toFixed(b > 1024 * 1024 ? 1 : 2);
      onMounted(load);
      return { items, loading, folder, upBusy, el, used, pct, mb, load, upload, del, enter, up };
    },
    template: `
    <div>
      <div class="card">
        <h2>个人存储 <span class="dim">{{ mb(used.used) }} MB / {{ (used.quota / 1024 ** 3).toFixed(0) }} GB（{{ pct }}%）</span></h2>
        <div class="bar"><i :style="{ width: Math.min(100, pct) + '%' }"></i></div>
        <input ref="el" type="file" style="display:none" @change="upload">
        <div class="actions" style="margin-top:12px;">
          <button class="btn" :disabled="upBusy" @click="$refs.el.click()">{{ upBusy ? "上传中…" : "上传文件" }}</button>
          <button class="btn ghost" v-if="folder !== '/'" @click="up">返回上级</button>
        </div>
        <div class="dim" style="margin-top:8px;">当前目录：{{ folder }}</div>
      </div>
      <div class="card">
        <div v-if="loading" class="loading"><span class="spin"></span>读取中…</div>
        <div v-else-if="!items.length" class="muted" style="padding:8px 0;">此目录为空</div>
        <div v-for="it in items" :key="it.id" class="row" @click="it.is_dir ? enter(it) : null">
          <span class="tag">{{ it.is_dir ? "目录" : (it.view || "文件") }}</span>
          <div class="main">
            <div class="name">{{ it.name }}</div>
            <div class="sub">{{ it.is_dir ? "文件夹" : mb(it.size) + " MB" }} · {{ it.modified || it.created }}</div>
          </div>
          <button class="icon-btn" @click.stop="del(it)" title="删除">✕</button>
        </div>
      </div>
    </div>`,
  };

  /* ---------------- 图图设置 ---------------- */
  const AiSettingsModule = {
    setup() {
      const st = ref(null), cfg = reactive({ provider: "local" }), kb = ref(null), busy = ref(false);
      async function load() {
        try {
          st.value = await api("/llm/status");
          cfg.provider = st.value.provider;
          kb.value = await api("/kb/stats");
        } catch (e) { window.__kdzyToast(e.message, "err"); }
      }
      async function save() {
        busy.value = true;
        try {
          await api("/llm/config", { provider: cfg.provider });
          window.__kdzyToast("已切换为「" + (cfg.provider === "local" ? "本地模型" : "云端接口") + "」");
          await load();
        } catch (e) { window.__kdzyToast(e.message, "err"); }
        busy.value = false;
      }
      onMounted(load);
      return { st, cfg, kb, busy, load, save };
    },
    template: `
    <div>
      <div class="card">
        <h2>推理方案</h2>
        <div class="pill-row">
          <button class="pill" :class="{ on: cfg.provider === 'local' }" @click="cfg.provider = 'local'">本地模型</button>
          <button class="pill" :class="{ on: cfg.provider === 'api' }" @click="cfg.provider = 'api'">云端接口</button>
        </div>
        <button class="btn" style="margin-top:12px;" :disabled="busy || !st || cfg.provider === st.provider" @click="save">
          {{ busy ? "保存中…" : (st && cfg.provider === st.provider ? "当前方案" : "切换方案") }}
        </button>
        <div class="dim" style="margin-top:8px;">完整配置（API Key、生成参数）请在桌面版「图图设置」里填。</div>
      </div>
      <div class="card" v-if="st">
        <h2>运行状态</h2>
        <div class="kv">
          <div class="kv-row"><span class="kv-k">本地库</span><span class="kv-v">{{ st.local.lib ? "可用" : "不可用" }}</span></div>
          <div class="kv-row"><span class="kv-k">模型</span><span class="kv-v">{{ st.local.model || "未找到" }}</span></div>
          <div class="kv-row"><span class="kv-k">体积</span><span class="kv-v">{{ st.local.model_mb }} MB</span></div>
          <div class="kv-row"><span class="kv-k">云端</span><span class="kv-v">{{ st.api.configured ? "已配置" : "未配置" }}</span></div>
          <div class="kv-row" v-if="st.local.last_error"><span class="kv-k">上次失败</span><span class="kv-v">{{ st.local.last_error }}</span></div>
        </div>
      </div>
      <div class="card" v-if="kb">
        <h2>知识库</h2>
        <div class="kv">
          <div class="kv-row"><span class="kv-k">章节</span><span class="kv-v">{{ kb.sections }} 节</span></div>
          <div class="kv-row"><span class="kv-k">文件</span><span class="kv-v">{{ (kb.files || []).join("、") }}</span></div>
        </div>
      </div>
    </div>`,
  };

  /* ---------------- 模块登记表（顺序即"功能"页的顺序） ---------------- */
  window.KDZY_MODULES = [
    { id: "detect", label: "图像检测", icon: "location", desc: "拍照/选图 · 扰动与分类", comp: DetectModule },
    { id: "preprocess", label: "数据预处理", icon: "layers", desc: "定标 · 大气校正 · 去云", comp: PreprocessModule },
    { id: "classify", label: "分类分析", icon: "home", desc: "RF / SVM / KNN + 精度", comp: ClassifyModule },
    { id: "change", label: "变化分析", icon: "refresh", desc: "转移矩阵 · 动态度", comp: ChangeModule },
    { id: "predict", label: "预测建模", icon: "map", desc: "CA-Markov / CLUE-S 多情景", comp: PredictModule },
    { id: "report", label: "报告生成", icon: "doc", desc: "八类模板 · Word/PDF", comp: null },
    { id: "files", label: "文件管理", icon: "user", desc: "个人存储 · 上传下载", comp: FilesModule },
    { id: "aisettings", label: "图图设置", icon: "chat", desc: "方案切换 · 运行状态", comp: AiSettingsModule },
  ];
})();
