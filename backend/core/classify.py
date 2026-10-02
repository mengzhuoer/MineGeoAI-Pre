# -*- coding: utf-8 -*-
# 矿地智预 MineGeoAI-Pre · by zhuoer mengzhuoda · 9.20
"""矿地智预 - 土地利用分类引擎

集成机器学习分类：随机森林 / 支持向量机 / K近邻
特征体系：4 波段反射率 + NDVI + 局部均值/方差纹理 + DEM/坡度地形特征
训练样本：从示范真值中分层随机抽样（模拟野外调查样本上传）
评估：总体精度 OA、Kappa 系数、逐类精度、混淆矩阵
"""
import numpy as np
from scipy import ndimage
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import cohen_kappa_score, confusion_matrix
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC

from . import geo, preprocess

ALGOS = {
    "rf": "随机森林 (RandomForest)",
    "svm": "支持向量机 (SVM)",
    "knn": "K近邻 (KNN)",
}


def build_features(year: int) -> np.ndarray:
    """由预处理后的干净反射率影像 + 地形数据构建 (H, W, F) 特征栈"""
    refl = preprocess.get_clean_reflectance(year)

    nir, red = refl[3], refl[2]
    ndvi = (nir - red) / np.maximum(nir + red, 1e-6)
    ndwi = (refl[1] - nir) / np.maximum(refl[1] + nir, 1e-6)

    feats = [refl[b] for b in range(4)] + [ndvi, ndwi]
    for b in range(4):
        feats.append(ndimage.uniform_filter(refl[b], 3))            # 3x3 局部均值
        feats.append(ndimage.uniform_filter(refl[b] ** 2, 3) ** 0.5)  # 局部标准差
    for name in (ndvi, refl[3]):
        feats.append(ndimage.uniform_filter(name, 7))               # 7x7 大尺度上下文
        feats.append(ndimage.gaussian_filter(name, 2))              # 平滑场

    dem = geo.load_driver("dem")
    slope = geo.load_driver("slope")
    feats += [dem / 1600.0, slope / 30.0]

    return np.stack(feats, axis=-1)


def sample_stratified(labels: np.ndarray, train_ratio: float, rng) -> tuple:
    """分层随机抽样训练/测试样本索引"""
    train_idx, test_idx = [], []
    for cid in geo.CLASS_IDS:
        idx = np.flatnonzero(labels == cid)
        rng.shuffle(idx)
        k = max(8, int(len(idx) * train_ratio))
        train_idx.append(idx[:k])
        test_idx.append(idx[k:])
    return np.concatenate(train_idx), np.concatenate(test_idx)


def classify(year: int, algorithm: str = "rf", train_ratio: float = 0.35):
    land = geo.load_landuse(year)
    feats = build_features(year)
    h, w, f = feats.shape
    X = feats.reshape(-1, f)
    y = land.reshape(-1)

    rng = np.random.default_rng(42)
    tr, te = sample_stratified(land, train_ratio, rng)
    X_tr, y_tr = X[tr], y[tr]
    X_te, y_te = X[te], y[te]

    if algorithm == "rf":
        clf = RandomForestClassifier(n_estimators=300, max_depth=18,
                                     n_jobs=-1, random_state=42)
        clf.fit(X_tr, y_tr)
    elif algorithm == "svm":
        # SVM 复杂度 O(n²)，大样本下子采样训练
        if len(X_tr) > 8000:
            sub = rng.choice(len(X_tr), 8000, replace=False)
            X_fit, y_fit = X_tr[sub], y_tr[sub]
        else:
            X_fit, y_fit = X_tr, y_tr
        clf = SVC(kernel="rbf", C=8.0, gamma="scale", cache_size=400)
        clf.fit(X_fit, y_fit)
    elif algorithm == "knn":
        clf = KNeighborsClassifier(n_neighbors=7, weights="distance", n_jobs=-1)
        clf.fit(X_tr, y_tr)
    else:
        raise ValueError(f"未知算法: {algorithm}")
    pred = clf.predict(X_te)
    oa = float((pred == y_te).mean())
    kappa = float(cohen_kappa_score(y_te, pred))
    cm = confusion_matrix(y_te, pred, labels=geo.CLASS_IDS)

    per_class = []
    for i, meta in enumerate(geo.CLASS_META):
        pa = cm[i, i] / max(cm[:, i].sum(), 1)   # 制图精度(查准)
        ua = cm[i, i] / max(cm[i, :].sum(), 1)   # 用户精度(查全)
        per_class.append({**meta, "producer_acc": round(pa * 100, 1),
                          "user_acc": round(ua * 100, 1)})

    full_pred = clf.predict(X).reshape(h, w).astype(np.uint8)
    shade = geo.hillshade(geo.load_driver("dem"))
    year_name = str(year)
    img = geo.render_landuse_png(
        full_pred, shade, legend=True,
        title=f"{geo.short_name()} {year_name} 年土地利用分类图（{ALGOS[algorithm]}）")

    import io
    buf = io.BytesIO()
    buf.write(img)

    return {
        "year": year,
        "algorithm": algorithm,
        "algorithm_name": ALGOS[algorithm],
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "overall_accuracy": round(oa * 100, 2),
        "kappa": round(kappa, 4),
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "prediction_map": buf.getvalue(),
    }
