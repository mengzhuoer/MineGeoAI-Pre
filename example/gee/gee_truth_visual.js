// 矿地智预 MineGeoAI-Pre · 二区冲刺工作包
/**
 * 目视解译底图生成脚本（真值标注辅助）
 * ============================================================
 * 用途：
 *   1. 在 Code Editor 地图上叠加"待判读年份"的高分底图与采样点，逐点目视判读；
 *   2. 导出一张 10 m Sentinel-2 真彩色 GeoTIFF（含近红外）到 Drive，
 *      供 QGIS/ENVI 离线解译与截图留证。
 *
 * 使用：
 *   1. https://code.earthengine.google.com 粘贴本脚本
 *   2. 改 CONFIG.aoi（默认平朔全矿区）与 truthYear（判读哪一年）
 *   3. Run 后逐层勾选查看；Tasks 面板点 RUN 导出 GeoTIFF
 *
 * 影像源策略（与《目视解译指南》对应）：
 *   2016 年及以后 → Sentinel-2 10 m（生长季中值，最优）
 *   2010—2015    → Landsat 8 合成（30 m，辅助 Google Earth 历史影像）
 *   2010 年以前   → Landsat 5 合成（30 m，仅辅助，主要靠 GE 历史影像）
 */

var CONFIG = {
  aoi: ee.Geometry.Rectangle([112.27, 39.36, 112.49, 39.55]), // 平朔全矿区（黑岱沟换成 111.15,39.58,111.35,39.80）
  truthYear: 2020,        // 待判读年份（改成 2010/2015 可看历史）
  pointsAsset: '',        // 可选：把采样点 GeoJSON 上传 GEE Assets 后填 ID，如 'users/你的用户名/truth_points'
  driveFolder: 'MineGeoAI_truth'
};

// ---------- Sentinel-2（2016 起，10 m） ----------
function maskS2(img) {
  var scl = img.select('SCL');
  var clear = scl.neq(0).and(scl.neq(1)).and(scl.neq(3))
    .and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10));
  return img.updateMask(clear).divide(10000);
}
function s2Composite(year) {
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(CONFIG.aoi)
    .filterDate(year + '-06-01', year + '-09-30')
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
    .map(maskS2)
    .median().clip(CONFIG.aoi);
}

// ---------- Landsat 5/8（30 m，历史年份辅助） ----------
function lsComposite(year) {
  var start = ee.Date.fromYMD(year, 6, 1);
  var end = ee.Date.fromYMD(year, 9, 30);
  var tm = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
    .filterBounds(CONFIG.aoi).filterDate(start, end)
    .filter(ee.Filter.lt('CLOUD_COVER', 50))
    .map(function (img) {
      img = img.select(['SR_B1', 'SR_B2', 'SR_B3'])
        .multiply(0.0000275).add(-0.2);
      return img;
    });
  var oli = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
    .filterBounds(CONFIG.aoi).filterDate(start, end)
    .filter(ee.Filter.lt('CLOUD_COVER', 50))
    .map(function (img) {
      img = img.select(['SR_B4', 'SR_B3', 'SR_B2'])
        .multiply(0.0000275).add(-0.2);
      return img.rename(['SR_B3', 'SR_B2', 'SR_B1']);
    });
  return tm.merge(oli).median().clip(CONFIG.aoi);
}

// ---------- 地图叠加 ----------
Map.centerObject(CONFIG.aoi, 11);
Map.addLayer(ee.Image().paint(CONFIG.aoi, 1, 3), { palette: 'red' }, 'AOI 边界');

if (CONFIG.truthYear >= 2016) {
  var s2 = s2Composite(CONFIG.truthYear);
  Map.addLayer(s2, { bands: ['B4', 'B3', 'B2'], min: 0, max: 0.3 }, 'S2 ' + CONFIG.truthYear + ' 真彩色(10m)');
  Map.addLayer(s2, { bands: ['B8', 'B4', 'B3'], min: 0, max: 0.4 }, 'S2 ' + CONFIG.truthYear + ' 假彩色(植被呈红)', false);
} else {
  var ls = lsComposite(CONFIG.truthYear);
  Map.addLayer(ls, { bands: ['SR_B3', 'SR_B2', 'SR_B1'], min: 0, max: 0.3 },
    'Landsat ' + CONFIG.truthYear + ' 真彩色(30m)');
}

if (CONFIG.pointsAsset) {
  var pts = ee.FeatureCollection(CONFIG.pointsAsset);
  Map.addLayer(pts, { color: 'ff0000' }, '采样点');
  print('采样点数：', pts.size());
}

// ---------- 导出 10 m 底图（仅 2016+ 年份） ----------
if (CONFIG.truthYear >= 2016) {
  Export.image.toDrive({
    image: s2Composite(CONFIG.truthYear).select(['B4', 'B3', 'B2', 'B8']).toFloat().unmask(-9999),
    description: 's2_truth_' + CONFIG.truthYear,
    fileNamePrefix: 's2_truth_' + CONFIG.truthYear,
    folder: CONFIG.driveFolder,
    region: CONFIG.aoi,
    scale: 10,
    crs: 'EPSG:32649',
    maxPixels: 1e10,
    fileFormat: 'GeoTIFF'
  });
  print('Tasks 面板点 RUN 导出 10 m 底图（约 60—90 MB），下载后可导入 QGIS 配合点位 CSV 解译');
} else {
  print('★ ' + CONFIG.truthYear + ' 年无 Sentinel-2（2015 年中发射），判读请以 Google Earth Pro 历史影像为主、Landsat 合成为辅');
}
