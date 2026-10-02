// 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
/**
 * 矿地智预 MineGeoAI-Pre · GEE 光谱指数导出脚本
 * ============================================================
 * 用途：导出 NDVI / BSI / NDBI（可选 LST）逐年栅格，供
 *       tools/import_real_dataset.py 的 --indices-dir 使用
 *
 * 使用方法：
 *   1. 打开 https://code.earthengine.google.com （需 Google 账号，学术用途免费）
 *   2. 把本脚本全部粘贴进去
 *   3. 修改下方 CONFIG 配置区（年份、AOI、导出坐标系）
 *   4. 点 Run → 右侧 Tasks 面板出现导出任务 → 逐个点 RUN
 *   5. 任务完成后，从 Google Drive 指定文件夹下载 tif 到本地
 *
 * 数据源：Landsat 5/7/8/9 Collection 2 Level 2（地表反射率产品，已做大气校正）
 * 合成策略：生长季（6-9 月）中值合成，抑制残余云与物候噪声
 *
 * 输出文件名（与接入工具约定一致，含"指数名_年份"即可自动识别）：
 *   ndvi_2000.tif / bsi_2000.tif / ndbi_2000.tif / lst_2000.tif ...
 */

// ============================================================
// ① 配置区
// ============================================================
var CONFIG = {
  years: [2000, 2005, 2010, 2015, 2020],   // 与地块数据集年份保持一致

  startMonth: 6,        // 生长季起（北方矿区 6-9 月植被最旺，裸土/建成区区分度最好）
  endMonth: 9,          // 生长季止
  maxCloud: 60,         // 元数据云量预筛阈值（%）

  crs: 'EPSG:32649',    // 导出坐标系：UTM 49N（山西用这个；陕西/内蒙部分区域 48N）
  scale: 30,            // 米。★务必导出投影坐标系，不要用经纬度，否则东西向像元被压缩

  driveFolder: 'MineGeoAI_indices_pingshuo_full',
  indices: ['ndvi', 'bsi', 'ndbi', 'lst']   // 只要三项可注释掉 'lst'（它计算量大且非必需）
};

// ------------------------------------------------------------
// ② 研究区 AOI（二选一，默认方式 A）
// ------------------------------------------------------------
// 方式 A：矩形（左上角经度, 左上角纬度, 右下角经度, 右下角纬度）
var AOI = ee.Geometry.Rectangle([112.27, 39.36, 112.49, 39.55]); // 平朔全矿区：安太堡(39.466N,112.338E)/安家岭采排区 + 原示范区

// 方式 B：用自己上传的矢量（Assets 上传 shp/geojson 后复制 ID）
// var AOI = ee.FeatureCollection('users/你的用户名/你的矿区范围').geometry();

// 方式 C：按中心点缓冲（示例：平朔一带，半径 6 km）
// var AOI = ee.Geometry.Point([112.37, 39.39]).buffer(6000).bounds();

// ============================================================
// ③ 预处理函数
// ============================================================

/** 云掩膜（Collection 2 QA_PIXEL 位运算）
 *  bit1 膨胀云 / bit2 卷云 / bit3 云 / bit4 云影 / bit5 雪 */
function maskClouds(img) {
  var qa = img.select('QA_PIXEL');
  var clear = qa.bitwiseAnd(1 << 1).eq(0)
    .and(qa.bitwiseAnd(1 << 2).eq(0))
    .and(qa.bitwiseAnd(1 << 3).eq(0))
    .and(qa.bitwiseAnd(1 << 4).eq(0))
    .and(qa.bitwiseAnd(1 << 5).eq(0));
  return img.updateMask(clear);
}

/**
 * ★ 波段列表必须按传感器区分（这是最容易踩的坑）：
 *   Landsat 5 TM / 7 ETM+：只有 6 个光学波段 SR_B1~B5、SR_B7
 *                           —— 没有 SR_B6！其第 6 波段是热红外 ST_B6
 *   Landsat 8 OLI / 9 OLI-2：SR_B1~SR_B7 全有，热红外是 ST_B10
 *   若给 L5/L7 传 SR_B6 会直接报错：
 *   "Band pattern 'SR_B6' did not match any bands"
 */
var SR_TM = ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'];
var SR_OLI = ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'];

/** 地表反射率定标：Collection 2 L2 必须做 DN → 反射率换算
 *  ★ 波段列表与热红外波段名由调用方传入（不能在 map() 里用 getInfo() 探测，GEE 禁止） */
function scaleSR(img, srBands, thermalBand) {
  img = img.addBands(img.select(srBands).multiply(0.0000275).add(-0.2), null, true);
  // 热红外定标：K = DN * 0.00341802 + 149.0
  return img.addBands(img.select(thermalBand).multiply(0.00341802).add(149.0), null, true);
}

/** Landsat 5 TM / 7 ETM+ → 统一波段名（在各自影像集上分别调用，避免跨传感器取波段报错） */
function prepTM(img) {
  img = scaleSR(img, SR_TM, 'ST_B6');
  return ee.Image.cat([
    img.select('SR_B1').rename('blue'),
    img.select('SR_B2').rename('green'),
    img.select('SR_B3').rename('red'),
    img.select('SR_B4').rename('nir'),
    img.select('SR_B5').rename('swir1'),
    img.select('SR_B7').rename('swir2'),
    img.select('ST_B6').rename('thermal')
  ]).copyProperties(img, ['system:time_start']);
}

/** Landsat 8 OLI / 9 OLI-2 → 统一波段名 */
function prepOLI(img) {
  img = scaleSR(img, SR_OLI, 'ST_B10');
  return ee.Image.cat([
    img.select('SR_B2').rename('blue'),
    img.select('SR_B3').rename('green'),
    img.select('SR_B4').rename('red'),
    img.select('SR_B5').rename('nir'),
    img.select('SR_B6').rename('swir1'),
    img.select('SR_B7').rename('swir2'),
    img.select('ST_B10').rename('thermal')
  ]).copyProperties(img, ['system:time_start']);
}

/** 计算四种指数 */
function addIndices(img) {
  var blue = img.select('blue'), red = img.select('red');
  var nir = img.select('nir'), swir1 = img.select('swir1');

  // NDVI 归一化植被指数 —— 植被旺盛度
  var ndvi = nir.subtract(red).divide(nir.add(red)).rename('ndvi');

  // BSI 裸土指数 —— 剥离面、排土场的裸土特征
  var bsi = swir1.add(red).subtract(nir.add(blue))
    .divide(swir1.add(red).add(nir).add(blue)).rename('bsi');

  // NDBI 归一化建筑指数 —— 区分"城市建成区"与"矿区裸土"的关键
  var ndbi = swir1.subtract(nir).divide(swir1.add(nir)).rename('ndbi');

  // LST 地表亮度温度（℃）—— 未做大气校正，可用于 CVA 变化向量
  var lst = img.select('thermal').subtract(273.15).rename('lst');

  return ee.Image.cat([ndvi, bsi, ndbi, lst]).copyProperties(img, ['system:time_start']);
}

// ============================================================
// ④ 逐年生长季合成
// ============================================================
function annualComposite(year) {
  var start = ee.Date.fromYMD(year, CONFIG.startMonth, 1);
  var end = ee.Date.fromYMD(year, CONFIG.endMonth, 1).advance(1, 'month');
  var bbox = AOI.bounds();

  // 按传感器分别预处理后再合并（关键：各传感器波段名不同）
  var tm = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
    .merge(ee.ImageCollection('LANDSAT/LE07/C02/T1_L2'))
    .filterBounds(bbox).filterDate(start, end)
    .filter(ee.Filter.lt('CLOUD_COVER', CONFIG.maxCloud))
    .map(maskClouds).map(prepTM);

  var oli = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
    .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
    .filterBounds(bbox).filterDate(start, end)
    .filter(ee.Filter.lt('CLOUD_COVER', CONFIG.maxCloud))
    .map(maskClouds).map(prepOLI);

  var col = tm.merge(oli).map(addIndices);
  print('年份 ' + year + ' 生长季可用影像数：', col.size());

  // 中值合成：对残余云和噪声最稳健
  return col.median().clip(AOI);
}

// ============================================================
// ⑤ 预览（导出前先目视确认，避免白跑任务）
// ============================================================
var preview = annualComposite(CONFIG.years[0]);
Map.centerObject(AOI, 11);
Map.addLayer(preview.select('ndvi'),
  { min: -0.2, max: 0.8, palette: ['#a50026', '#ffffbf', '#006837'] }, 'NDVI 预览');
Map.addLayer(preview.select('ndbi'),
  { min: -0.4, max: 0.4, palette: ['#2166ac', '#f7f7f7', '#b2182b'] }, 'NDBI 预览', false);
Map.addLayer(preview.select('bsi'),
  { min: -0.3, max: 0.6, palette: ['#f7fbff', '#fdae61', '#7f0000'] }, 'BSI 预览', false);
Map.addLayer(ee.Image().paint(AOI, 1, 3), { palette: 'red' }, '研究区边界');
print('★ 先在地图上确认范围与数值合理，再执行下方导出');

// ============================================================
// ⑥ 批量导出
// ============================================================
CONFIG.years.forEach(function (year) {
  var composite = annualComposite(year);
  CONFIG.indices.forEach(function (name) {
    Export.image.toDrive({
      // ★ unmask(-9999)：GEE 默认把掩膜像元（云区等）写成 0，
      //   而 NDVI=0 会被本地工具误判为"低植被"。写 -9999 后工具会正确识别为无效值
      image: composite.select(name).toFloat().unmask(-9999),
      description: name + '_' + year,
      fileNamePrefix: name + '_' + year,     // ★ 文件名必须含"指数名_年份"
      folder: CONFIG.driveFolder,
      region: AOI,
      scale: CONFIG.scale,
      crs: CONFIG.crs,
      maxPixels: 1e10,
      fileFormat: 'GeoTIFF',
      formatOptions: { cloudOptimized: true }
    });
  });
});

print('====================================================');
print('已在 Tasks 面板生成 ' + CONFIG.years.length + ' 年 × ' +
      CONFIG.indices.length + ' 指数 = ' + (CONFIG.years.length * CONFIG.indices.length) + ' 个导出任务');
print('▲ 需要手动逐个点击 RUN（GEE 不允许脚本自动执行导出）');
print('▲ 同时运行建议不超过 4-6 个，避免排队超时');
print('====================================================');

/**
 * ============================================================
 * 导出后接入软件
 * ============================================================
 * 1. Google Drive 下载 tif 到本地目录，例如 E:/indices/
 *    ndvi_2000.tif  bsi_2000.tif  ndbi_2000.tif  lst_2000.tif
 *    ndvi_2005.tif  ...（共 5 年 × 4 指数）
 *
 * 2. 运行接入工具：
 *    python tools/import_real_dataset.py ^
 *      --clcd-dir "E:/CLCD" --years 2000 2005 2010 2015 2020 ^
 *      --aoi aoi.geojson --dem dem.tif ^
 *      --indices-dir "E:/indices" ^
 *      --mine mine.geojson ^
 *      --dataset-id pingshuo-full --name "pingshuo-full" ^
 *      --out-dir backend/data/pingshuo-full
 *
 * 3. 刷新浏览器 → 右下角数据选择器出现新矿区 → 查看检测与预测结果
 *
 * ============================================================
 * 常见问题
 * ============================================================
 * Q: 某年影像数很少或为 0
 * A: 看 print 输出的数量。山西夏季多云，若某年生长季 < 3 景，
 *    把 startMonth/endMonth 放宽到 5-10 月，或提高 maxCloud。
 *    2000 年前后只有 Landsat 5/7（重访 16 天），可用影像本身较少。
 *
 * Q: 数值范围异常（如 NDVI 都接近 0）
 * A: 检查 scaleSR 是否生效（Collection 2 必须做 0.0000275 / -0.2 定标）。
 *
 * Q: 导出后某些区域是 0 或数字全为 0
 * A: 那是云掩膜留下的空白像元。脚本已用 unmask(-9999) 处理，
 *    本地工具会把 -9999 识别为无效值并用邻域中位数填充。
 *    若你手动改了导出代码，务必保留 unmask(-9999)。
 *
 * Q: 报错 Band pattern 'SR_B6' did not match any bands
 * A: 对 Landsat 5/7 影像取了 SR_B6，但 TM/ETM+ 没有这个波段（只有 SR_B1~B5、SR_B7）。
 *    脚本已用 SR_TM / SR_OLI 两个列表区分传感器，若你自己改了波段选择请保留这个区分。
 *
 * Q: 2003 年后 Landsat 7 有条带（SLC-off）
 * A: 中值合成已能大幅抑制条带影响。若条带仍明显，
 *    可在 annualComposite 里过滤掉 L7：
 *    .filter(ee.Filter.eq('SPACECRAFT_ID', 'LANDSAT_7'))  # 或直接不用 LE07 影像集
 *
 * Q: 想加自己的指数（NDWI、铁矿指数等）
 * A: 在 addIndices() 里加一行，并在 CONFIG.indices 里加名字。
 *    本地工具按文件名识别，无需改代码。
 *
 * Q: 导出慢 / 配额不足
 * A: 按年份分批跑；或只导 ndvi/bsi/ndbi 三项（lst 仅参与 CVA，非必需）。
 *
 * Q: 需要更高分辨率
 * A: 把数据源换成 Sentinel-2（10 m）：
 *    ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')，波段 B2/B3/B4/B8/B11/B12，
 *    反射率除以 10000，云掩膜用 'QA60' 或 s2cloudless。
 */
