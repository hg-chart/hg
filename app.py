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

# 注入 CSS 确保手机端输入框可以横向排布在一行
st.markdown("""
<style>
.inline-time-container {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
}
.inline-time-container > div {
    flex: 1;
}
.inline-time-container > div:first-child {
    flex: 2.2;
}
</style>
""", unsafe_allow_html=True)

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

# 用于保存图表渲染状态，防止下载后图表消失
if "plotted_fig_bytes" not in st.session_state:
    st.session_state.plotted_fig_bytes = None
if "plotted_title" not in st.session_state:
    st.session_state.plotted_title = ""


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

# 默认负荷左纵轴为 W3.UNIT1.10DEHDCSAI03（如果存在于列中）
default_load_index = min(1, len(columns) - 1)
if "W3.UNIT1.10DEHDCSAI03" in columns:
    default_load_index = columns.index("W3.UNIT1.10DEHDCSAI03")

with col1:
    time_col = st.selectbox("横坐标轴（时间列）", columns, index=0)
with col2:
    load_col = st.selectbox("负荷左纵轴", columns, index=default_load_index)
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

# 1. 先在上方展示已添加的对比时段表格及管理按钮区
if st.session_state.intervals:
    st.write("当前已添加的对比时段（图表按此顺序依次排列）。勾选“选择”后，可在下方修改、上移/下移或删除：")

    table_data = []
    for idx, item in enumerate(st.session_state.intervals):
        table_data.append({
            "选择": False,
            "序号": idx + 1,
            "开始时间": item["start"],
            "结束时间": item["end"],
            "多频集速运行(s)": item.get("run_sec", "0"),
            "多频集速停止(s)": item.get("stop_sec", "-"),
        })

    df_intervals = pd.DataFrame(table_data)

    edited_df = st.data_editor(
        df_intervals,
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", required=True),
            "序号": st.column_config.NumberColumn("序号", disabled=True),
        },
        disabled=["序号"],
        hide_index=True,
        use_container_width=True,
        key="intervals_editor"
    )

    bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns(5)

    with bcol1:
        if st.button("💾 保存修改", use_container_width=True):
            try:
                new_intervals = []
                for _, row in edited_df.iterrows():
                    s_str = str(row["开始时间"]).strip()
                    e_str = str(row["结束时间"]).strip()
                    pd.to_datetime(s_str)
                    pd.to_datetime(e_str)
                    new_intervals.append({
                        "start": s_str,
                        "end": e_str,
                        "run_sec": str(row["多频集速运行(s)"]).strip() or "0",
                        "stop_sec": str(row["多频集速停止(s)"]).strip() or "-",
                    })
                st.session_state.intervals = new_intervals
                st.success("修改已成功保存！")
                st.rerun()
            except Exception as ex:
                st.error(f"保存失败，请检查时间格式是否正确: {ex}")

    with bcol2:
        if st.button("⬆️ 上移", use_container_width=True):
            selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
            if not selected_indices:
                st.warning("请先勾选要上移的时段！")
            elif len(selected_indices) > 1:
                st.warning("每次只能上移一个时段！")
            else:
                idx = selected_indices[0]
                if idx == 0:
                    st.info("已经是第一个时段，无法上移。")
                else:
                    st.session_state.intervals[idx], st.session_state.intervals[idx - 1] = (
                        st.session_state.intervals[idx - 1],
                        st.session_state.intervals[idx],
                    )
                    st.rerun()

    with bcol3:
        if st.button("⬇️ 下移", use_container_width=True):
            selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
            if not selected_indices:
                st.warning("请先勾选要下移的时段！")
            elif len(selected_indices) > 1:
                st.warning("每次只能下移一个时段！")
            else:
                idx = selected_indices[0]
                if idx == len(st.session_state.intervals) - 1:
                    st.info("已经是最后一个时段，无法下移。")
                else:
                    st.session_state.intervals[idx], st.session_state.intervals[idx + 1] = (
                        st.session_state.intervals[idx + 1],
                        st.session_state.intervals[idx],
                    )
                    st.rerun()

    with bcol4:
        if st.button("❌ 删除", use_container_width=True):
            selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
            if not selected_indices:
                st.warning("请先勾选要删除的时段！")
            else:
                for idx in sorted(selected_indices, reverse=True):
                    st.session_state.intervals.pop(idx)
                st.success("已删除选中时段！")
                st.rerun()

    with bcol5:
        if st.button("🗑️ 清空", use_container_width=True):
            st.session_state.intervals = []
            st.success("已清空所有时段！")
            st.rerun()

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

# ============================================================
# 2. 放在下方的“添加新时段”表单（使用 CSS 强制同行显示）
# ============================================================
with st.container(border=True):
    st.markdown("➕ **添加新时段**（自动智能衔接，支持秒级精准配置）")
    with st.form("interval_form"):
        st.markdown("📅 **开始时间**")
        st.markdown('<div class="inline-time-container">', unsafe_allow_html=True)
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            start_date = st.date_input("开始日期", value=default_start.date(), key="s_date", label_visibility="collapsed")
        with sc2:
            start_hour = st.number_input("时", min_value=0, max_value=23, value=default_start.hour, key="s_h", label_visibility="collapsed")
        with sc3:
            start_minute = st.number_input("分", min_value=0, max_value=59, value=default_start.minute, key="s_m", label_visibility="collapsed")
        with sc4:
            start_second = st.number_input("秒", min_value=0, max_value=59, value=default_start.second, key="s_s", label_visibility="collapsed")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("📅 **结束时间**")
        st.markdown('<div class="inline-time-container">', unsafe_allow_html=True)
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            end_date = st.date_input("结束日期", value=default_end.date(), key="e_date", label_visibility="collapsed")
        with ec2:
            end_hour = st.number_input("时 ", min_value=0, max_value=23, value=default_end.hour, key="e_h", label_visibility="collapsed")
        with ec3:
            end_minute = st.number_input("分 ", min_value=0, max_value=59, value=default_end.minute, key="e_m", label_visibility="collapsed")
        with ec4:
            end_second = st.number_input("秒 ", min_value=0, max_value=59, value=default_end.second, key="e_s", label_visibility="collapsed")
        st.markdown('</div>', unsafe_allow_html=True)

        run_col, stop_col, btn_col = st.columns([2, 2, 1.5])
        with run_col:
            run_seconds = st.text_input("多频集速运行秒数", value="30")
        with stop_col:
            stop_seconds = st.text_input("停止秒数（若为0可不填）", value="780")
        with btn_col:
            st.write("")
            add_interval = st.form_submit_button("添加时段", use_container_width=True)

        if add_interval:
            try:
                start_dt = datetime(
                    start_date.year, start_date.month, start_date.day,
                    int(start_hour), int(start_minute), int(start_second)
                )
                end_dt = datetime(
                    end_date.year, end_date.month, end_date.day,
                    int(end_hour), int(end_minute), int(end_second)
                )

                if start_dt >= end_dt:
                    st.error("开始时间必须早于结束时间！")
                else:
                    start_string = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                    end_string = end_dt.strftime("%Y-%m-%d %H:%M:%S")
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
                    
                    import io
                    image_buffer = io.BytesIO()
                    fig.savefig(
                        image_buffer,
                        format="png",
                        dpi=180,
                        bbox_inches="tight",
                        facecolor="white",
                    )
                    st.session_state.plotted_fig_bytes = image_buffer.getvalue()
                    st.session_state.plotted_title = title

            except Exception as exc:
                st.error(f"计算或绘图过程中发生错误：{exc}")
            finally:
                if fig is not None:
                    plt.close(fig)

# 持续渲染已保存的图表，确保下载或其他操作后图表依然留在页面上
if st.session_state.plotted_fig_bytes is not None:
    st.success("图表生成成功！")
    st.image(st.session_state.plotted_fig_bytes, caption=st.session_state.plotted_title, use_container_width=True)
    st.download_button(
        "⬇️ 下载趋势图 PNG",
        data=st.session_state.plotted_fig_bytes,
        file_name="设备运行数据多时段对比趋势图.png",
        mime="image/png",
    )
