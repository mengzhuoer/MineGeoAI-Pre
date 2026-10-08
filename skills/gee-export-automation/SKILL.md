---
name: gee-export-automation
description: 通过浏览器自动化接管 Google Earth Engine Code Editor：把本地 JS 导出脚本注入 ACE 编辑器、点 Run、在 Tasks 面板 Run all 批量提交 Export 任务到 Google Drive；也可只读查询任务状态。适用于按 AOI/年份/指数批量导出栅格（Export.image.toDrive）。凡涉及"跑 GEE 脚本、批量导出遥感影像、把 JS 填进 Earth Engine、提交 GEE 导出任务、Export.image.toDrive、检查 GEE 任务进度"，都应使用本技能——即使用户没说"自动化"或"浏览器"。
---

# GEE Code Editor 浏览器自动化（注入 JS + 批量提交导出任务）

用途：把本地写好的 GEE JS 脚本灌入 code.earthengine.google.com 的编辑器并提交 Export
任务，替代手动复制粘贴和逐个点任务。适用于 Export.image.toDrive / toAsset 批量导出
（按 AOI、按年份、按指数循环的脚本尤其合适），以及查看任务运行状态。

本文件中的 API 名称以 Playwright 风格给出作参考；换用其它浏览器自动化栈时，替换为
对应的等价调用即可（核心是"在页面上下文执行 JS"与"读取页面可访问性树/快照"两个能力）。

## 前提

1. 需要一个能驱动浏览器的运行环境（AI 助手自带的浏览器控制能力，或本地以 CDP /
   Playwright 启动的 Chromium）。**手工打开的外部浏览器（夸克/Edge 等）通常无法被
   接管**——除非以调试端口启动。
2. **Google 登录**：打开 code.earthengine.google.com，若跳转到 accounts.google.com
   登录页，让**用户自己在浏览器窗口输入账号密码**（绝不代输/索要凭据）。账号需已
   注册 Earth Engine（凡用过 GEE 的账号均可）。
3. 网络需能访问 Google（代理按用户环境配置）。页面打不开时先确认
   https://code.earthengine.google.com 可达，再排查脚本。

## 核心流程（每个脚本一轮）

1. 找到 GEE 标签页（标题含 "Earth Engine Code Editor"）并绑定；没有则新建标签页
   并导航到 https://code.earthengine.google.com/ 。
2. 读本地脚本全文（40KB+、含中文注释没问题），作为参数传入页面 evaluate，
   **不要**用键盘逐字输入。
3. **注入编辑器**——GEE 编辑器是 **ACE**，不是 CodeMirror（`.CodeMirror` 选择器不存在，
   探测会超时，勿重试）：

   ```js
   // 在页面上下文执行（locator.evaluate / page.evaluate 等价位置）
   const res = (t) => {
     const el = document.querySelector(".ace_editor");
     if (!el) return { ok: false, why: "no ace editor" };
     const ed = (el.env && el.env.editor) ? el.env.editor : ace.edit(el);
     ed.setValue(t, -1);            // -1 = 光标回到开头
     ed.focus();
     ed.clearSelection();
     const v = ed.getValue();
     return { ok: true, len: v.length, hasMark: v.indexOf("<脚本内唯一标记串>") >= 0 };
   };
   ```
   用返回的 `len` 与脚本内唯一标记串（如 driveFolder 名、AOI 坐标）双重校验写入完整。

4. **运行脚本**：按角色定位 Run 按钮（`role=button[name="Run"]`）并先确认唯一
   （Tasks 面板展开时会出现多个 Run，先关面板）。Run 后用页面快照确认 Console 出现
   脚本自己的 print 输出且无 "Error"——脚本先在客户端跑一遍，有错（波段名不对、集合
   为空、配额）要先修脚本，不要急着提交任务。
5. **提交任务**：打开 **Tasks** 面板 → 点击 **Run all**。
   **不要逐个点任务的 Run 按钮**（20 个任务 × 弹窗太慢）；Run all 无确认弹窗；
   提交中表现为 Clear / Run all 与全部任务按钮变 disabled，面板显示 "Updating..."。
6. **验证提交**：等 8–10 秒再取快照：`Unsubmitted` 区消失或清空，`Submitted tasks`
   区列出全部任务名（ndvi_2000 … ndbi_2020 之类）。
7. 多脚本（如多矿区）依次重复 2–6。**不同脚本的 Export 任务显示名可能完全相同**
   （都叫 ndvi_2000），任务列表里无法区分来源——只能靠脚本内 `CONFIG.driveFolder`
   把不同来源路由到不同 Drive 文件夹，写脚本时就必须给每个区域独立 folder 名。

## 关键陷阱

- **Tasks 面板在 shadow DOM 里**：`document.body.innerText` 与 `querySelector` 都读不到
  "Unsubmitted / Submitted tasks" 文本（evaluate 返回空），**必须用浏览器自动化工具的
  整页快照（accessibility snapshot）** 穿透读取。
- 编辑器 DOM：`.ace_editor` 容器 + 隐藏 `textarea.ace_text-input`（value 是 `\u0001\u0001`
  哨兵字符，别误判成脚本没写进去）——以 `ed.getValue()` 为准。
- 单步操作超时通常 3 秒；长等待用显式的 `waitForTimeout(ms)`。
- **多区域同名任务混排**：Submitted 区条目数会大于去重后的任务名数；快照里无法区分
  来源。**判断某个区域"跑完没"，以 Drive 对应文件夹的文件数为准**（应为 年数 × 指数数
  个 tif），不要依赖任务名。
- 任务提交后服务端排队：小 AOI（几百 km²）单任务几分钟到十几分钟；LST（热红外）
  明显最慢。失败任务（云量/配额）需重新注入脚本后单独点该任务的 Run。
- 完成文件落在 `CONFIG.driveFolder` 指定的 Drive 文件夹，文件名 = `fileNamePrefix`
  （约定 `指数名_年份.tif`——与 MineGeoAI-Pre 的入库工具约定一致）。

## 完成后向用户报告

注入并运行了哪些脚本、提交的任务总数与明细、Drive 目标文件夹、预计耗时、
失败任务的重跑方式。
