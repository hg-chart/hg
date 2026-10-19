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
# 工厂隔离：所有目录都由“当前会话选中的工厂”推导，不再使用任何全局共用目录或软链接
factory = st.session_state.get("selected_factory")
if not factory:
    st.error("尚未选择工厂，已停止加载（防止不同工厂的数据混用）。请从系统入口进入并选择工厂。")
    st.stop()

VAULT_DIR = f"uploaded_vault_{factory}"
FILE_TRASH_DIR = f"file_trash_{factory}"
CHART_HISTORY_DIR = f"chart_history_{factory}"
CHART_TRASH_DIR = f"chart_trash_{factory}"

for _d in (VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR, CHART_TRASH_DIR):
    os.makedirs(_d, exist_ok=True)

# 切换工厂时，清掉上一个工厂遗留的图表相关状态
if st.session_state.get("_dash_scope") != factory:
    st.session_state["_dash_scope"] = factory
    for _k in ("plotted_fig_bytes", "current_pressure_col", "current_filter_metric"):
        st.session_state.pop(_k, None)

if r2_storage._get_r2_client() is not None:
    _sync_key = f"_r2_synced_{factory}"
    if not st.session_state.get(_sync_key, False):
        with st.spinner(f"正在同步工厂【{factory}】的云端文件……"):
            _ok = r2_storage.sync_local_storage_with_r2(VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR)
        if _ok:
            st.session_state[_sync_key] = True
    st.caption(f"☁️ Cloudflare R2 存储桶：已连接（私有存储）｜当前工厂：{factory}")
    _quarantined = st.session_state.get(f"_sync_quarantined_{factory}") or []
    if _quarantined:
        with st.expander(f"⚠️ 已隔离 {len(_quarantined)} 个不属于本工厂云端目录的本地文件", expanded=False):
            st.write("这些文件不在工厂【" + factory + "】的 R2 目录里，已从文件库移出，避免混入分析。"
                     "文件没有被删除，存放在服务器的 _quarantine_" + factory + " 文件夹中：")
            for _n in _quarantined:
                st.text(f"📄 {_n}")
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

# 左、右纵轴都可以选 0 个或多个数据列：time_col 是单个列名，left_cols / right_cols 是列名列表
(
    time_col, left_cols, right_cols,
    min_threshold, max_threshold, filter_valid,
    final_time_label, final_left_label, final_right_label,
    filter_target_col, filter_metric_name, axis_info
) = data_processor.render_column_and_filter_config(columns)

time_intervals_manager.render_time_intervals_manager(VAULT_DIR, df_raw, time_col)

# 传入图表生成模块
chart_generator.render_chart_generator(
    df_raw, time_col, left_cols, right_cols,
    min_threshold, max_threshold, filter_valid,
    final_time_label, final_left_label, final_right_label,
    filter_target_col, filter_metric_name, axis_info
)

cloud_chart_manager.render_cloud_chart_manager(CHART_HISTORY_DIR, CHART_TRASH_DIR)
