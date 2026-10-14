# -*- coding: utf-8 -*-
"""设备运行数据多文件多时段汇总对比分析系统"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager


# ============================================================
# 1. 页面与中文字体
# ============================================================

st.set_page_config(
    page_title="设备运行数据多文件多时段汇总对比分析系统",
    layout="wide",
)

matplotlib.rcParams["axes.unicode_minus"] = False

# packages.txt 安装文泉驿字体。这里既检查字体名称，也主动加载常见字体文件。
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
    logging.error(
        "没有检测到中文字体。请检查根目录 packages.txt 是否包含 "
        "fonts-wqy-zenhei、fonts-wqy-microhei、fontconfig，并查看部署日志。"
    )

COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

st.title("📊 设备运行数据多文件多时段汇总对比分析系统")
st.markdown("---")


# ============================================================
# 2. 文件库和历史时段方案
# ============================================================

VAULT_DIR = "uploaded_vault"
os.makedirs(VAULT_DIR, exist_ok=True)
TEMPLATES_FILE = os.path.join(VAULT_DIR, "templates_vault.json")


def default_templates():
    return {
        "默认测试方案 (5个时段示例)": [
            {"start": "2026-08-01 01:01:00", "end": "2026-08-05 01:01:50", "run_sec": "0", "stop_sec": "-"},
            {"start": "2026-09-19 01:01:50", "end": "2026-09-25 13:09:50", "run_sec": "0", "stop_sec": "-"},
            {"start": "2026-09-25 13:10:50", "end": "2026-09-29 13:09:50", "run_sec": "30", "stop_sec": "780"},
            {"start": "2026-10-04 13:09:50", "end": "2026-10-12 15:20:50", "run_sec": "30", "stop_sec": "780"},
            {"start": "2026-10-12 15:20:51", "end": "2026-10-14 15:20:50", "run_sec": "60", "stop_sec": "300"},
        ]
    }


@st.cache_resource
def load_persistent_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
        except Exception:
            logging.exception("读取历史时段方案失败，将使用默认方案。")
    return default_templates()


def save_persistent_templates(templates):
    try:
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as file:
            json.dump(templates, file, ensure_ascii=False, indent=4)
        return True
    except Exception as exc:
        st.error(f"保存时段方案失败：{exc}")
        return False


if "saved_templates" not in st.session_state:
    st.session_state.saved_templates = load_persistent_templates()
if "intervals" not in st.session_state:
    st.session_state.intervals = []


# ============================================================
# 3. 上传及选择数据文件
# ============================================================

st.subheader("1. 表格文件管理（支持上传和调用历史文件）")

uploaded_files = st.file_uploader(
    "上传工业数据表格文件（CSV / XLSX / XLS）",
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        safe_name = Path(uploaded_file.name).name
        target = os.path.join(VAULT_DIR, safe_name)
        with open(target, "wb") as file:
            file.write(uploaded_file.getbuffer())
    st.success("文件已保存到当前运行环境的文件库。")

existing_files = sorted(
    name for name in os.listdir(VAULT_DIR)
    if name.lower().endswith((".csv", ".xlsx", ".xls"))
)

active_paths = []
if existing_files:
    with st.expander("📁 文件库（勾选本次分析所需文件）", expanded=True):
        selected_files = st.multiselect(
            "选择参与分析的文件",
            existing_files,
            default=existing_files,
        )
        active_paths = [os.path.join(VAULT_DIR, name) for name in selected_files]

        if st.button("🗑️ 清空文件库中的所有表格文件"):
            for name in existing_files:
                try:
                    os.remove(os.path.join(VAULT_DIR, name))
                except OSError as exc:
                    st.warning(f"删除 {name} 失败：{exc}")
            st.rerun()

if not active_paths:
    st.info("请先上传或选择 CSV、Excel 数据文件。")
    st.stop()

st.success(f"当前已选择 {len(active_paths)} 个文件参与分析。")


# ============================================================
# 4. 读取 CSV / Excel
# ============================================================

try:
    dataframes = []

    for file_path in active_paths:
        if file_path.lower().endswith(".csv"):
            df = None
            read_errors = []
            for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                    read_errors.append(f"{encoding}: {exc}")
            if df is None:
                raise ValueError(
                    f"无法读取 CSV 文件 {Path(file_path).name}。"
                    + "；".join(read_errors)
                )
        else:
            with pd.ExcelFile(file_path) as excel:
                sheet_names = excel.sheet_names
            sheet_frames = [
                pd.read_excel(file_path, sheet_name=sheet)
                for sheet in sheet_names
            ]
            df = pd.concat(sheet_frames, ignore_index=True) if sheet_frames else pd.DataFrame()

        df.columns = df.columns.astype(str).str.strip().str.lstrip("\ufeff")
        dataframes.append(df)

    df_raw = pd.concat(dataframes, ignore_index=True, sort=False)
    columns = [str(c).strip() for c in df_raw.columns if str(c).strip()]

except Exception as exc:
    st.error(f"读取文件失败：{exc}")
    st.stop()

if not columns:
    st.error("所选文件没有可用的数据列。")
    st.stop()


# ============================================================
# 5. 数据列和负荷过滤
# ============================================================

st.subheader("2. 数据列选择配置")
col1, col2, col3 = st.columns(3)

with col1:
    time_col = st.selectbox("横坐标轴（时间列）", columns, index=0)
with col2:
    load_col = st.selectbox("负荷左纵轴", columns, index=min(1, len(columns) - 1))
with col3:
    pressure_col = st.selectbox("压差右纵轴", columns, index=min(2, len(columns) - 1))

st.subheader("3. 负荷过滤配置（可选）")
threshold_text = st.text_input("负荷下限阈值（留空则使用全部负荷数据）", value="")
threshold = None
threshold_valid = True

if threshold_text.strip():
    try:
        threshold = float(threshold_text.strip())
    except ValueError:
        threshold_valid = False
        st.error("负荷下限必须是数字，例如 240。")


# ============================================================
# 6. 多时段配置与历史方案
# ============================================================

st.subheader("4. 多时段对比配置")

with st.expander("📁 历史时段方案管理", expanded=False):
    template_names = list(st.session_state.saved_templates.keys())
    tcol1, tcol2 = st.columns([2, 1])

    with tcol1:
        if template_names:
            chosen_template = st.selectbox("选择已保存的历史方案", template_names)
            if st.button("📥 一键加载该历史方案"):
                st.session_state.intervals = [
                    dict(item) for item in st.session_state.saved_templates[chosen_template]
                ]
                st.success(f"已加载历史方案：{chosen_template}")
                st.rerun()
        else:
            st.info("尚无保存的历史方案。")

    with tcol2:
        template_name = st.text_input("当前方案名称", value="我的常用方案")
        if st.button("💾 保存当前时段方案"):
            if not st.session_state.intervals:
                st.warning("当前没有时段，无法保存。")
            elif not template_name.strip():
                st.warning("请填写方案名称。")
            else:
                st.session_state.saved_templates[template_name.strip()] = [
                    dict(item) for item in st.session_state.intervals
                ]
                if save_persistent_templates(st.session_state.saved_templates):
                    st.success(f"方案“{template_name.strip()}”已保存。")
                    st.rerun()

# 已有时段列表展示区（采用类似图二的年月日时分秒独立分栏输入）
if st.session_state.intervals:
    st.markdown("📋 **当前已添加的对比时段列表：**")

    for idx, interval in enumerate(st.session_state.intervals):
        with st.container(border=True):
            st.markdown(f"**#{idx + 1}**")
            
            # 解析原有的时间字符串以填充默认值
            try:
                s_dt = pd.to_datetime(interval["start"])
            except Exception:
                s_dt = datetime.now()
            try:
                e_dt = pd.to_datetime(interval["end"])
            except Exception:
                e_dt = datetime.now() + timedelta(minutes=50)

            st.markdown("🕒 **开始时间**")
            sy1, sy2, sy3, sy4, sy5, sy6 = st.columns(6)
            with sy1:
                s_y = st.text_input("年", value=str(s_dt.year), key=f"s_y_{idx}")
            with sy2:
                s_m = st.text_input("月", value=f"{s_dt.month:02d}", key=f"s_m_{idx}")
            with sy3:
                s_d = st.text_input("日", value=f"{s_dt.day:02d}", key=f"s_d_{idx}")
            with sy4:
                s_h = st.text_input("时", value=f"{s_dt.hour:02d}", key=f"s_h_{idx}")
            with sy5:
                s_min = st.text_input("分", value=f"{s_dt.minute:02d}", key=f"s_min_{idx}")
            with sy6:
                s_s = st.text_input("秒", value=f"{s_dt.second:02d}", key=f"s_s_{idx}")

            st.markdown("🕒 **结束时间**")
            ey1, ey2, ey3, ey4, ey5, ey6 = st.columns(6)
            with ey1:
                e_y = st.text_input("年 ", value=str(e_dt.year), key=f"e_y_{idx}")
            with ey2:
                e_m = st.text_input("月 ", value=f"{e_dt.month:02d}", key=f"e_m_{idx}")
            with ey3:
                e_d = st.text_input("日 ", value=f"{e_dt.day:02d}", key=f"e_d_{idx}")
            with ey4:
                e_h = st.text_input("时 ", value=f"{e_dt.hour:02d}", key=f"e_h_{idx}")
            with ey5:
                e_min = st.text_input("分 ", value=f"{e_dt.minute:02d}", key=f"e_min_{idx}")
            with ey6:
                e_s = st.text_input("秒 ", value=f"{e_dt.second:02d}", key=f"e_s_{idx}")

            r_col, st_col, b_col1, b_col2, b_col3, b_col4 = st.columns([1.5, 1.5, 1, 1, 1, 1])
            with r_col:
                new_run = st.text_input("运行秒数", value=str(interval.get("run_sec", "0")), key=f"run_{idx}")
            with st_col:
                new_stop = st.text_input("停止秒数", value=str(interval.get("stop_sec", "-")), key=f"stop_{idx}")

            with b_col1:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("💾修改", key=f"update_{idx}", use_container_width=True):
                    try:
                        new_start = f"{s_y.strip()}-{s_m.strip().zfill(2)}-{s_d.strip().zfill(2)} {s_h.strip().zfill(2)}:{s_min.strip().zfill(2)}:{s_s.strip().zfill(2)}"
                        new_end = f"{e_y.strip()}-{e_m.strip().zfill(2)}-{e_d.strip().zfill(2)} {e_h.strip().zfill(2)}:{e_min.strip().zfill(2)}:{e_s.strip().zfill(2)}"
                        pd.to_datetime(new_start)
                        pd.to_datetime(new_end)
                        st.session_state.intervals[idx] = {
                            "start": new_start,
                            "end": new_end,
                            "run_sec": new_run.strip() or "0",
                            "stop_sec": new_stop.strip() or "-",
                        }
                        st.success("已更新")
                        st.rerun()
                    except Exception as e:
                        st.error(f"格式错误: {e}")

            with b_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                up_disabled = (idx == 0)
                if st.button("⬆️上移", key=f"up_{idx}", disabled=up_disabled, use_container_width=True):
                    st.session_state.intervals[idx], st.session_state.intervals[idx - 1] = (
                        st.session_state.intervals[idx - 1],
                        st.session_state.intervals[idx],
                    )
                    st.rerun()

            with b_col3:
                st.markdown("<br>", unsafe_allow_html=True)
                down_disabled = (idx == len(st.session_state.intervals) - 1)
                if st.button("⬇️下移", key=f"down_{idx}", disabled=down_disabled, use_container_width=True):
                    st.session_state.intervals[idx], st.session_state.intervals[idx + 1] = (
                        st.session_state.intervals[idx + 1],
                        st.session_state.intervals[idx],
                    )
                    st.rerun()

            with b_col4:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("❌删除", key=f"del_{idx}", use_container_width=True):
                    st.session_state.intervals.pop(idx)
                    st.rerun()

    if st.button("🗑️ 清空所有时段"):
        st.session_state.intervals = []
        st.rerun()
else:
    st.info("当前暂无对比时段，请在下方添加。")

st.markdown("---")

# 自动衔接时间计算
default_start = datetime.now()
if st.session_state.intervals:
    try:
        default_start = pd.to_datetime(st.session_state.intervals[-1]["end"]).to_pydatetime()
    except Exception:
        pass
else:
    try:
        parsed = pd.to_datetime(
            df_raw[time_col].astype(str).str.strip(),
            format="mixed",
            errors="coerce",
        )
        earliest = parsed.min()
        if pd.notna(earliest):
            default_start = earliest.to_pydatetime()
    except Exception:
        pass

default_end = default_start + timedelta(minutes=50)

# 放在已有时间段窗口下方的添加表单
with st.form("interval_form"):
    st.markdown("➕ **添加新时段（开始时间已自动衔接上一时段结束时间）**")

    st.markdown("🕒 **开始时间**")
    sy1, sy2, sy3, sy4, sy5, sy6 = st.columns(6)
    with sy1:
        start_year = st.text_input("年", value=str(default_start.year), key="sy")
    with sy2:
        start_month = st.text_input("月", value=f"{default_start.month:02d}", key="sm")
    with sy3:
        start_day = st.text_input("日", value=f"{default_start.day:02d}", key="sd")
    with sy4:
        start_hour = st.text_input("时", value=f"{default_start.hour:02d}", key="sh")
    with sy5:
        start_minute = st.text_input("分", value=f"{default_start.minute:02d}", key="smin")
    with sy6:
        start_second = st.text_input("秒", value=f"{default_start.second:02d}", key="ss")

    st.markdown("🕒 **结束时间**")
    ey1, ey2, ey3, ey4, ey5, ey6 = st.columns(6)
    with ey1:
        end_year = st.text_input("年 ", value=str(default_end.year), key="ey")
    with ey2:
        end_month = st.text_input("月 ", value=f"{default_end.month:02d}", key="em")
    with ey3:
        end_day = st.text_input("日 ", value=f"{default_end.day:02d}", key="ed")
    with ey4:
        end_hour = st.text_input("时 ", value=f"{default_end.hour:02d}", key="eh")
    with ey5:
        end_minute = st.text_input("分 ", value=f"{default_end.minute:02d}", key="emin")
    with ey6:
        end_second = st.text_input("秒 ", value=f"{default_end.second:02d}", key="es")

    run_col, stop_col = st.columns(2)
    with run_col:
        run_seconds = st.text_input("运行秒数", value="30")
    with stop_col:
        stop_seconds = st.text_input("停止秒数（若运行为0可不填）", value="780")

    add_interval = st.form_submit_button("➕ 确认添加时段", use_container_width=True)

    if add_interval:
        try:
            start_string = (
                f"{start_year.strip()}-{start_month.strip().zfill(2)}-{start_day.strip().zfill(2)} "
                f"{start_hour.strip().zfill(2)}:{start_minute.strip().zfill(2)}:{start_second.strip().zfill(2)}"
            )
            end_string = (
                f"{end_year.strip()}-{end_month.strip().zfill(2)}-{end_day.strip().zfill(2)} "
                f"{end_hour.strip().zfill(2)}:{end_minute.strip().zfill(2)}:{end_second.strip().zfill(2)}"
            )
            start_dt = pd.to_datetime(start_string)
            end_dt = pd.to_datetime(end_string)

            if start_dt >= end_dt:
                st.error("开始时间必须早于结束时间！")
            else:
                run_text = run_seconds.strip() or "0"
                stop_text = "-" if run_text in ("0", "0.0") else (stop_seconds.strip() or "-")
                st.session_state.intervals.append({
                    "start": start_string,
                    "end": end_string,
                    "run_sec": run_text,
                    "stop_sec": stop_text,
                })
                st.success("时段添加成功！")
                st.rerun()
        except Exception as exc:
            st.error(f"时间格式错误：{exc}")

st.markdown("---")


# ============================================================
# 7. 生成多时段趋势图
# ============================================================

if st.button("🚀 开始生成多时段对比趋势图", type="primary"):
    if not threshold_valid:
        st.error("请先把负荷下限阈值修改为有效数字。")
    elif not st.session_state.intervals:
        st.warning("请至少添加一个对比时间段！")
    else:
        with st.spinner("正在处理多时段数据并绘图……"):
            fig = None
            try:
                df = df_raw.copy()

                rename_map = {
                    col: COLUMN_ALIASES[col]
                    for col in df.columns
                    if col in COLUMN_ALIASES
                }
                df = df.rename(columns=COLUMN_ALIASES)
                actual_time_col = rename_map.get(time_col, time_col)
                actual_load_col = rename_map.get(load_col, load_col)
                actual_pressure_col = rename_map.get(pressure_col, pressure_col)

                required = [actual_time_col, actual_load_col, actual_pressure_col]
                missing = [col for col in required if col not in df.columns]
                if missing:
                    raise KeyError("找不到所选数据列：" + "、".join(missing))

                df[actual_time_col] = pd.to_datetime(
                    df[actual_time_col].astype(str).str.strip(),
                    format="mixed",
                    errors="coerce",
                )
                df[actual_load_col] = pd.to_numeric(df[actual_load_col], errors="coerce")
                df[actual_pressure_col] = pd.to_numeric(df[actual_pressure_col], errors="coerce")
                df = df.dropna(subset=[actual_time_col, actual_load_col])
                df = df.sort_values(actual_time_col).reset_index(drop=True)
                df = df[df[actual_load_col] != 0].copy()

                if threshold is not None:
                    df = df[df[actual_load_col] >= threshold].copy()

                palette = [
                    ("#85B2FF", "#1E3F66"),
                    ("#52C41A", "#135200"),
                    ("#FF7875", "#820014"),
                    ("#B37FEB", "#391085"),
                    ("#FF9C6E", "#873800"),
                    ("#36CBCB", "#00474F"),
                    ("#FF85C0", "#990033"),
                    ("#D3F261", "#5B8C00"),
                ]

                plotted_periods = []
                diagnostics = []

                for index, interval in enumerate(st.session_state.intervals):
                    start_dt = pd.to_datetime(interval["start"])
                    end_dt = pd.to_datetime(interval["end"])
                    part = df[
                        (df[actual_time_col] >= start_dt)
                        & (df[actual_time_col] <= end_dt)
                    ].copy()
                    diagnostics.append(f"时段 {index + 1}：匹配到 {len(part)} 行")

                    if part.empty:
                        continue

                    part = part.sort_values(actual_time_col).reset_index(drop=True)
                    fill_color, line_color = palette[index % len(palette)]
                    actual_start = part[actual_time_col].min().strftime("%Y-%m-%d %H:%M:%S")
                    actual_end = part[actual_time_col].max().strftime("%Y-%m-%d %H:%M:%S")
                    run_value = interval.get("run_sec", "0")
                    stop_value = interval.get("stop_sec", "-")
                    description = (
                        f"多频集速运行{run_value}s/停止{stop_value}s "
                        f"(实际 {actual_start} ~ {actual_end})"
                    )
                    plotted_periods.append({
                        "data": part,
                        "fill_color": fill_color,
                        "line_color": line_color,
                        "description": description,
                    })

                st.info("🔍 各时段数据检索诊断：" + " | ".join(diagnostics))

                if not plotted_periods:
                    st.warning("指定时间段和负荷阈值下均未检索到有效数据。")
                else:
                    fig, ax1 = plt.subplots(figsize=(16, 8))
                    ax2 = ax1.twinx()

                    all_x_labels = []
                    cursor = 0

                    for period in plotted_periods:
                        part = period["data"]
                        count = len(part)
                        x_values = list(range(cursor, cursor + count))
                        cursor += count
                        all_x_labels.extend(
                            part[actual_time_col].dt.strftime("%m-%d %H:%M:%S").tolist()
                        )

                        ax1.fill_between(
                            x_values,
                            part[actual_load_col].to_numpy(),
                            color=period["fill_color"],
                            alpha=0.50,
                            label=f"{period['description']} 负荷",
                        )
                        ax1.plot(
                            x_values,
                            part[actual_load_col].to_numpy(),
                            color=period["fill_color"],
                            linewidth=0.8,
                            alpha=0.9,
                        )
                        ax2.plot(
                            x_values,
                            part[actual_pressure_col].to_numpy(),
                            color=period["line_color"],
                            linewidth=1.5,
                            label=f"{period['description']} 压差",
                        )

                    ax1.set_xlabel("运行时间段", fontsize=12)
                    ax1.set_ylabel(f"负荷（{actual_load_col}）", fontsize=12, color="black")
                    ax2.set_ylabel(f"压差（{actual_pressure_col}）", fontsize=12, color="black")

                    ax1.grid(True, axis="y", linestyle="-", linewidth=0.6, alpha=0.35)
                    ax1.set_axisbelow(True)

                    total_points = len(all_x_labels)
                    tick_step = max(1, total_points // 10)
                    tick_positions = list(range(0, total_points, tick_step))
                    ax1.set_xticks(tick_positions)
                    ax1.set_xticklabels(
                        [all_x_labels[i] for i in tick_positions],
                        rotation=30,
                        ha="right",
                    )

                    if threshold is not None:
                        threshold_display = (
                            str(int(threshold)) if threshold.is_integer() else str(threshold)
                        )
                        title = f"机组负荷/压差对比趋势图（最低负荷 ≥ {threshold_display}）"
                    else:
                        title = "机组负荷/压差对比趋势图"

                    ax1.set_title(title, fontsize=15, pad=16)

                    handles1, labels1 = ax1.get_legend_handles_labels()
                    handles2, labels2 = ax2.get_legend_handles_labels()
                    ax1.legend(
                        handles1 + handles2,
                        labels1 + labels2,
                        loc="upper center",
                        bbox_to_anchor=(0.5, -0.23),
                        fontsize=8,
                        ncol=2,
                        framealpha=0.9,
                    )

                    fig.subplots_adjust(bottom=0.32, top=0.90, left=0.09, right=0.91)
                    st.pyplot(fig, use_container_width=True)
                    st.success("图表生成成功！")

                    import io
                    image_buffer = io.BytesIO()
                    fig.savefig(
                        image_buffer,
                        format="png",
                        dpi=180,
                        bbox_inches="tight",
                        facecolor="white",
                    )
                    st.download_button(
                        "⬇️ 下载趋势图 PNG",
                        data=image_buffer.getvalue(),
                        file_name="设备运行数据多时段对比趋势图.png",
                        mime="image/png",
                    )

            except Exception as exc:
                st.error(f"计算或绘图过程中发生错误：{exc}")
            finally:
                if fig is not None:
                    plt.close(fig)
