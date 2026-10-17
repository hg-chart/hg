# -*- coding: utf-8 -*-
"""设备运行数据多文件多时段汇总对比分析系统 - 主入口"""
import os
import logging
import streamlit as st
import matplotlib
from matplotlib import font_manager

# 1. 导入 Cloudflare R2 专属模块
import r2_storage

# 2. 导入拆分出的各个独立功能模块
import file_manager
import data_processor
import time_intervals_manager
import chart_generator
import cloud_chart_manager

# ============================================================
# 页面基础配置与中文字体
# ============================================================

st.set_page_config(
    page_title="设备运行数据多文件多时段汇总对比分析系统",
    layout="wide",
)

st.markdown(
    """
    <style>
    div[data-testid="stToolbar"] {
        visibility: hidden;
        display: none !important;
    }
    footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True
)

matplotlib.rcParams["axes.unicode_minus"] = False

FONT_FILES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttf",
]

for font_path in FONT_FILES:
    if os.path.isfile(font_path):
        try:
            font_manager.fontManager.addfont(font_path)
        except Exception:
            pass

PREFERRED_FONTS = [
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "SimHei",
    "Microsoft YaHei",
]

available_fonts = {font.name for font in font_manager.fontManager.ttflist}
selected_font = next(
    (name for name in PREFERRED_FONTS if name in available_fonts),
    None,
)

if selected_font:
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [selected_font, "DejaVu Sans"]
    logging.warning("Matplotlib 中文字体：%s", selected_font)
else:
    logging.error("没有检测到中文字体。")

st.title("📊 设备运行数据多文件多时段汇总对比分析系统")
st.markdown("---")

# ============================================================
# 初始化存储路径与 R2 云端同步
# ============================================================
VAULT_DIR = "uploaded_vault"
FILE_TRASH_DIR = "file_trash_vault"
CHART_HISTORY_DIR = "chart_history"
CHART_TRASH_DIR = "chart_trash_vault"

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(FILE_TRASH_DIR, exist_ok=True)
os.makedirs(CHART_HISTORY_DIR, exist_ok=True)
os.makedirs(CHART_TRASH_DIR, exist_ok=True)

if r2_storage._get_r2_client() is not None:
    if not st.session_state.get("_r2_initial_sync_done", False):
        with st.spinner("正在连接 Cloudflare R2 存储桶并同步历史文件……"):
            r2_storage.sync_local_storage_with_r2(VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR)
        st.session_state["_r2_initial_sync_done"] = True
    st.caption("☁️ Cloudflare R2 存储桶：已连接（私有存储）")
else:
    r2_err = r2_storage.get_r2_error()
    st.warning("Cloudflare R2 尚未连接，当前使用本地临时存储。" + (f" 提示：{r2_err}" if r2_err else ""))

# ============================================================
# 模块串联与执行流
# ============================================================

active_paths = file_manager.render_file_manager(VAULT_DIR, FILE_TRASH_DIR)

if not active_paths:
    st.info("请先上传或选择 CSV、Excel 数据文件。")
    st.stop()

df_raw, columns = data_processor.load_and_process_data(active_paths)

if not columns:
    st.error("所选文件没有可用的数据列。")
    st.stop()

# 接收 11 个返回值以匹配 data_processor 的最新输出
(
    time_col, load_col, pressure_col, 
    min_threshold, max_threshold, filter_valid, 
    final_time_label, final_load_label, final_pressure_label,
    filter_target_col, filter_metric_name
) = data_processor.render_column_and_filter_config(columns)

time_intervals_manager.render_time_intervals_manager(VAULT_DIR, df_raw, time_col)

# 传入图表生成模块
chart_generator.render_chart_generator(
    df_raw, time_col, load_col, pressure_col, 
    min_threshold, max_threshold, filter_valid, 
    final_time_label, final_load_label, final_pressure_label,
    filter_target_col, filter_metric_name
)

cloud_chart_manager.render_cloud_chart_manager(CHART_HISTORY_DIR, CHART_TRASH_DIR)
