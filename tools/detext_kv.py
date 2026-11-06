#!/usr/bin/env python3
"""KV 背景去字脚本（离线工具，不参与页面运行时）。

用途：把官网 web12 首页 KV（1920×1080）上的两行白色主标题「疾风掠影 / 迎战飓风龙」
去掉，输出仓库内成品图 assets/kv-bg-v3.png 与 assets/kv-bg-v3.webp。

方案来自《龙之谷》新版本介绍页 V3 技术方案 2.3「方案 B（研发兜底）」：
  1. 只对文字字形加外发光的受影响区生成遮罩：用「接近白 + 局部硬边」双条件识别
     字形（软光带、饱和天空、红色速度线不会被误判），字形外扩约 12px；
  2. 遮罩内部用多尺度金字塔归一化填充恢复低频底色，各方向同时收敛，
     不做整体高斯模糊、纯色填充、横向拉伸或整块复制；
  3. 从遮罩外环带取高频残差，以随机错位方式回贴颗粒，避免补丁过于平滑；
  4. 高斯羽化融合，遮罩外像素逐像素不变（脚本会打印校验值）。

依赖：Pillow + numpy（仅离线使用，不进页面）。
用法：
  python3 tools/detext_kv.py --input bg.jpg \
      --output-png assets/kv-bg-v3.png --output-webp assets/kv-bg-v3.webp
"""

import argparse
import json
import os

import numpy as np
from PIL import Image, ImageFilter

# 文字受影响区检索范围（原图坐标）。实测两行主标题约 x 551–1356、y 505–780，
# 外发光与深色描边外扩后取 x 500–1470、y 455–810 作为检索范围。
ROI = (500, 455, 1470, 810)  # left, top, right, bottom（右/下为开区间）

WHITE_MIN_CHANNEL = 120   # 字形白度下限（通道最小值）
WHITE_MAX_CHANNEL = 175   # 亮度下限
WHITE_MAX_SAT = 0.50      # 饱和度上限（排除饱和蓝天空、红色速度线）
SHARP_DELTA = 10          # 与局部模糊的差值下限，只保留硬边叠加物（文字）
GROW_RADIUS = 12          # 字形外扩，覆盖描边与外发光
GAP_BRIDGE = 40           # 同一行内窄缝（笔画间）桥接上限，像素
FEATHER_SIGMA = 16        # 羽化半径
GRAIN_AMOUNT = 0.9        # 颗粒回贴强度


def load_rgb(path):
    im = Image.open(path)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    return im


def _blur(arr, sigma):
    """对 H×W×C 或 H×W 数组做逐通道高斯模糊。"""
    single = arr.ndim == 2
    work = arr[:, :, None] if single else arr
    out = np.zeros(work.shape, dtype=np.float32)
    for c in range(work.shape[2]):
        out[:, :, c] = np.asarray(
            Image.fromarray(work[:, :, c].astype(np.uint8), 'L')
            .filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32)
    return out[:, :, 0] if single else out


def build_mask(arr):
    """返回 bool 遮罩：白色字形 + 深色描边与青色外发光的外扩区。"""
    mn = arr.min(axis=2)
    mx = arr.max(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    delta = np.abs(arr - _blur(arr, 15)).max(axis=2)

    roi = np.zeros(mn.shape, dtype=bool)
    left, top, right, bottom = ROI
    roi[top:bottom, left:right] = True

    cue = ((mn > WHITE_MIN_CHANNEL) & (mx > WHITE_MAX_CHANNEL)
           & (sat < WHITE_MAX_SAT) & (delta > SHARP_DELTA) & roi)

    # 以 cue 实际范围为准（加外扩余量），避免检索框四边留白被一并修补
    ys, xs = np.nonzero(cue)
    if ys.size == 0:
        return np.zeros_like(cue)
    box = (max(int(xs.min()) - GROW_RADIUS, left), max(int(ys.min()) - GROW_RADIUS, top),
           min(int(xs.max()) + GROW_RADIUS, right), min(int(ys.max()) + GROW_RADIUS, bottom))
    keep = np.zeros_like(cue)
    keep[box[1]:box[3] + 1, box[0]:box[2] + 1] = True

    # 外扩：模糊后取低阈值，相当于半径约 GROW_RADIUS 的膨胀
    grown = _blur(cue.astype(np.float32) * 255.0, GROW_RADIUS)
    mask = (grown > 12) & keep

    # 桥接同一行内的窄缝（笔画间隙），超过 GAP_BRIDGE 的空隙保持不填，
    # 避免把整行拉成一条横带、在补丁里造成横向拖影。
    for y in range(box[1], box[3] + 1):
        row = mask[y]
        xs = np.nonzero(row)[0]
        if xs.size == 0:
            continue
        runs = np.split(xs, np.nonzero(np.diff(xs) > 1)[0] + 1)
        for a, b in zip(runs[:-1], runs[1:]):
            if b[0] - a[-1] <= GAP_BRIDGE:
                row[a[-1]:b[0] + 1] = True

    # 收口：轻微膨胀抹平锯齿
    return _blur(mask.astype(np.float32) * 255.0, 4) > 24


def pyramid_fill(arr, mask, levels=9):
    """多尺度归一化填充：逐级下采样聚合已知像素，再逐级上采样填补空洞。"""
    known = (~mask).astype(np.float32)
    pyr = [(arr * known[:, :, None], known)]
    for _ in range(levels):
        ci, cw = pyr[-1]
        if ci.shape[0] < 8 or ci.shape[1] < 8:
            break
        h2, w2 = (ci.shape[0] // 2) * 2, (ci.shape[1] // 2) * 2
        ci, cw = ci[:h2, :w2], cw[:h2, :w2]
        si = ci.reshape(h2 // 2, 2, w2 // 2, 2, 3).sum(axis=(1, 3))
        sw = cw.reshape(h2 // 2, 2, w2 // 2, 2).sum(axis=(1, 3))
        pyr.append((si, sw))

    ci, cw = pyr[-1]
    avg = ci.sum(axis=(0, 1)) / max(float(cw.sum()), 1e-6)
    filled, weight = ci.copy(), cw.copy()
    empty = weight < 1e-6
    filled[empty] = avg
    weight[empty] = 1.0
    out = filled / weight[:, :, None]

    for level in range(len(pyr) - 2, -1, -1):
        ci, cw = pyr[level]
        height, width = cw.shape
        up = np.stack([
            np.asarray(Image.fromarray(out[:, :, c], 'F').resize((width, height), Image.BILINEAR))
            for c in range(3)], axis=2)
        weight = np.maximum(cw, 1e-6)
        value = ci / weight[:, :, None]
        out = np.where((cw > 1e-6)[:, :, None], value, up)
    return out


def ring_grain(arr, mask, amount=GRAIN_AMOUNT):
    """从遮罩外环带取高频残差，随机错位平铺回贴颗粒。"""
    resid = arr - _blur(arr, 3)
    ring = _blur(mask.astype(np.float32) * 255.0, 24) > 24
    band = ring & ~mask
    grain = np.zeros_like(arr)
    band_idx = np.argwhere(band)
    mask_idx = np.argwhere(mask)
    if band_idx.shape[0] == 0 or mask_idx.shape[0] == 0:
        return grain
    rng = np.random.default_rng(20260716)
    picks = rng.integers(0, band_idx.shape[0], size=mask_idx.shape[0])
    src = band_idx[picks]
    grain[mask_idx[:, 0], mask_idx[:, 1]] = resid[src[:, 0], src[:, 1]]
    return grain * amount


def detext(arr, mask):
    base = pyramid_fill(arr, mask)
    grain = ring_grain(arr, mask)
    filled = np.clip(base + grain, 0, 255)

    # 羽化：遮罩内为 1，边界向内约 1/3σ 递减到 0，遮罩外逐像素不变
    feather = _blur(mask.astype(np.float32) * 255.0, FEATHER_SIGMA)
    alpha = np.clip(feather * 3.0 / 255.0, 0.0, 1.0)
    alpha = np.where(mask, np.maximum(alpha, 0.999), alpha)

    out = arr * (1.0 - alpha[:, :, None]) + filled * alpha[:, :, None]
    return np.clip(out, 0, 255), alpha


def residual_text_stats(arr):
    """去字后核查：区域内「近白 + 硬边」像素数，用于确认没有文字残留。"""
    mn = arr.min(axis=2)
    mx = arr.max(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    delta = np.abs(arr - _blur(arr, 15)).max(axis=2)
    roi = np.zeros(mn.shape, dtype=bool)
    left, top, right, bottom = ROI
    roi[top:bottom, left:right] = True
    cue = ((mn > WHITE_MIN_CHANNEL) & (mx > WHITE_MAX_CHANNEL)
           & (sat < WHITE_MAX_SAT) & (delta > SHARP_DELTA) & roi)
    return int(cue.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output-png', required=True)
    ap.add_argument('--output-webp', required=True)
    ap.add_argument('--webp-quality', type=int, default=85)
    ap.add_argument('--compare-dir', help='可选：输出去字前后对照裁图，便于验收比对')
    args = ap.parse_args()

    im = load_rgb(args.input)
    arr = np.asarray(im).astype(np.float32)
    mask = build_mask(arr)
    out, alpha = detext(arr, mask)

    res = Image.fromarray(out.astype(np.uint8), 'RGB')
    res.save(args.output_png, optimize=True)
    res.save(args.output_webp, format='WEBP', quality=args.webp_quality, method=6)

    if args.compare_dir:
        os.makedirs(args.compare_dir, exist_ok=True)
        box = (ROI[0] - 40, ROI[1] - 60, ROI[2] + 40, ROI[3] + 65)
        im.crop(box).save(os.path.join(args.compare_dir, 'kv-before.png'))
        res.crop(box).save(os.path.join(args.compare_dir, 'kv-after.png'))

    ys, xs = np.nonzero(mask)
    outside = alpha == 0
    diff = np.abs(out - arr).max(axis=2)
    stats = {
        'size': list(im.size),
        'mask_bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if xs.size else [],
        'mask_px': int(mask.sum()),
        'text_cue_before': residual_text_stats(arr),
        'text_cue_after': residual_text_stats(out),
        'outside_mask_px': int(outside.sum()),
        'outside_max_abs_diff': float(diff[outside].max()) if outside.any() else 0.0,
    }
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    main()
