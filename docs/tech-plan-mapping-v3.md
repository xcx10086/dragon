# 《龙之谷》新版本介绍页 V3 技术方案落地映射

对应需求：story 7160621378《《龙之谷》新版本介绍页 V3（删除征名/预约活动模块，背景移除「疾风掠影/迎战飓风龙」标题文字）》
对应技术方案文档：https://pcnsq97h225v.feishu.cn/docx/JAaLdef4RoCh5RxjqWhcsrv2n0c（rev 2）

## 1. 删除范围（index.html）

| 删除对象 | 原位置（V2） | 处理 |
| --- | --- | --- |
| 活动入口四卡 + 倒计时面板 | `<section id="activities">` | 整段删除，含 4 张 activity-card、`#countdown`、`.activity-* / .countdown* / .cd-*` 样式 |
| 外传职业征名活动 | `<section id="name">` | 整段删除，含奖池、规则、活动主视觉两张 CDN 图、`.campaign* / .info-* / .prize* / .rule-list` 样式 |
| 新职业预约活动 | `<section id="reserve">` | 整段删除，含进度条 `#progressWrap`、里程碑 `#milestones`、账号区 `#accountBox`、`.reserve* / .progress* / .mile* / .account-box / .tips` 样式 |
| 征名六步弹窗 | `<div id="nameModal">` + `#nameStep` | 整段删除，含 `.modal / .name-pop / .np-*` 样式与 6 步渲染、发送验证码、企微二维码等 JS |
| 首屏「立即预约」CTA | `.hero .cta-group` | 双 CTA 收敛为单 CTA「新版本信息」 |
| 活动期标签 | `.hero .period` | 改为「上线时间 2026.07.16」 |
| 导航 / 页脚 / 悬浮入口 | `#navLinks`、`.footer-links`、`.dock` | 去掉「征名活动」「预约活动」链接与「预约」悬浮按钮 |
| 文案与头信息 | `title`、`meta description`、页脚 `about`、`CONFIG.VERSION.points` | 移除征名/预约相关表述 |

JS 侧同步删除：倒计时模块（`TARGET_TIME` + `pad` 定时器）、征名模块（`RE_CN / RE_PHONE / RE_CODE`、`dn_name_submit` 本地态）、预约模块（`CONFIG.RESERVE`、`dn_reserved`、`thousands`）；模块注释重新编号为 1–8。

## 2. 首屏背景去字（技术方案 2.3 方案 B）

- 成品：`assets/kv-bg-v3.png`（1920×1080 源图）、`assets/kv-bg-v3.webp`（页内引用，约 240 KB）。
- 工具：`tools/detext_kv.py`（Pillow + numpy，离线运行，不参与页面运行时；页面仍为零构建、零第三方运行时）。
- 流程：白度 + 局部硬边双条件识别字形（排除软光带、饱和天空、红色速度线）→ 字形外扩 12px 取遮罩 → 多尺度金字塔归一化填充恢复低频底色 → 环带高频残差随机回贴颗粒 → 高斯羽化融合。
- 自检（脚本输出）：遮罩 212,533 px，遮罩外像素 1,719,083 px 逐像素零差异（`outside_max_abs_diff = 0.0`）；区域内白色硬边像素由 92,812 降至 2,792（剩余为补丁颗粒与检索框边缘的真实背景，非文字）。
- 页面引用：`<link rel="preload" as="image" href="assets/kv-bg-v3.webp">`、`<img id="kvImg" src="assets/kv-bg-v3.webp">`，`CONFIG.KV_IMAGE / KV_FALLBACK` 驱动两级降级（WebP 失败 → PNG，均失败 → 渐变底色），不回退官网带字原图。

## 3. 未覆盖 / 待确认

- 官网 KV 商用授权：成品图源自官网 web12 KV（`static.web.sdo.com/.../20261029/bg.jpg`），投放前仍需设计侧确认授权与是否改由设计直接出去字图。
- 质量验收：OCR 比对、PSNR、1920/1280/750 三档截图需图形环境留痕；当前沙箱无浏览器与 OCR，仅完成像素级自检（遮罩外零差异 + 白字像素归零）与人工目视裁切图核查。
- 去字区域原天空光带、半透明暗纹在填补后趋于平滑渐变，属方案 B（无设计分层素材）的已知代价。
