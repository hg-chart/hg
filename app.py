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
if "edit_ver" not in st.session_state:
    st.session_state.edit_ver = 0


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


def mutate_intervals(new_list, select=None):
    """统一修改时段列表：刷新编辑控件、让新增表单重新衔接上一时段结束时间。"""
    st.session_state.intervals = new_list
    st.session_state.edit_ver += 1
    st.session_state["_sync_form"] = True
    st.session_state["_sel_rows"] = list(select) if isinstance(select, (list, tuple, set)) else []
    st.rerun()


def parse_interval_time(text):
    """解析并标准化时间字符串，失败时抛出异常。"""
    value = pd.to_datetime(str(text).strip())
    if pd.isna(value):
        raise ValueError("时间为空")
    return value


def normalize_run_stop(run_text, stop_text):
    """校验运行/停止秒数；运行为 0 时停止秒数记为 '-'。"""
    run_text = str(run_text).strip() or "0"
    try:
        run_value = float(run_text)
    except ValueError:
        raise ValueError("运行秒数必须是数字")
    if run_value < 0:
        raise ValueError("运行秒数不能为负数")

    if run_value == 0:
        return run_text, "-"

    stop_text = str(stop_text).strip()
    if not stop_text or stop_text == "-":
        return run_text, "-"
    try:
        stop_value = float(stop_text)
    except ValueError:
        raise ValueError("停止秒数必须是数字")
    if stop_value < 0:
        raise ValueError("停止秒数不能为负数")
    return run_text, stop_text


with st.expander("📁 历史时段方案管理", expanded=False):
    template_names = list(st.session_state.saved_templates.keys())
    tcol1, tcol2 = st.columns([2, 1])

    with tcol1:
        if template_names:
            chosen_template = st.selectbox("选择已保存的历史方案", template_names)
            if st.button("📥 一键加载该历史方案"):
                mutate_intervals([
                    dict(item) for item in st.session_state.saved_templates[chosen_template]
                ], select=0)
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

def compute_form_start():
    """新增表单的默认开始时间：有时段则取最后一个时段的结束时间，否则取数据最早时间。"""
    if st.session_state.intervals:
        try:
            return pd.to_datetime(st.session_state.intervals[-1]["end"]).to_pydatetime()
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
                return earliest.to_pydatetime()
        except Exception:
            pass
    return datetime.now().replace(microsecond=0)


def fill_form_fields(start_dt):
    """把开始/结束时间写入表单控件的 session_state（必须在控件创建之前调用）。"""
    end_dt = start_dt + timedelta(minutes=50)
    for prefix, dt in (("s", start_dt), ("e", end_dt)):
        st.session_state[f"{prefix}y"] = str(dt.year)
        st.session_state[f"{prefix}m"] = f"{dt.month:02d}"
        st.session_state[f"{prefix}d"] = f"{dt.day:02d}"
        st.session_state[f"{prefix}h"] = f"{dt.hour:02d}"
        st.session_state[f"{prefix}min"] = f"{dt.minute:02d}"
        st.session_state[f"{prefix}s"] = f"{dt.second:02d}"


st.markdown(
    """
    <style>
    /* 时段表格：单行、紧凑、小方框 */
    .st-key-grid { overflow-x: auto; }
    .st-key-grid [data-testid="stHorizontalBlock"] {
        gap: 0.15rem; flex-wrap: nowrap !important; align-items: center; min-width: 1150px;
    }
    .st-key-grid [data-testid="stColumn"], .st-key-grid [data-testid="column"] {
        min-width: 0 !important;
    }
    .st-key-grid [data-testid="stVerticalBlock"] { gap: 0.35rem; }
    .st-key-grid input {
        text-align: center; padding: 0.2rem 0.1rem; min-height: 2rem;
    }
    .st-key-grid button {
        padding: 0.1rem 0.2rem; min-height: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 列宽：序号 | 开始(年月日时分秒) | → | 结束(年月日时分秒) | 运行 秒 | 停止 秒 | ⬆ ⬇ ❌
TIME_W = [1.3, 0.3] + [0.9, 0.3] * 5
GRID_W = [0.4] + TIME_W + [0.35] + TIME_W + [0.9, 0.3, 0.9, 0.3] + [0.4, 0.4, 0.4]
C_START, C_ARROW, C_END = 1, 13, 14
C_RUN, C_STOP, C_BTN = 26, 28, 30
TIME_UNITS = ["年", "月", "日", "时", "分", "秒"]


def unit_label(text):
    st.markdown(
        f"<div style='white-space:nowrap;text-align:center;padding-top:0.3rem'>{text}</div>",
        unsafe_allow_html=True,
    )


def head_label(text):
    st.markdown(
        f"<div style='white-space:nowrap;font-weight:600;color:#666;font-size:0.85rem'>{text}</div>",
        unsafe_allow_html=True,
    )


def time_cells(cols, offset, keys, values=None):
    """在已创建的列中画 6 个“小方框 + 单位”，返回 6 段文本。"""
    parts = []
    for i, unit in enumerate(TIME_UNITS):
        with cols[offset + 2 * i]:
            kwargs = {"key": keys[i], "label_visibility": "collapsed"}
            if values is not None:
                kwargs["value"] = values[i]
            parts.append(st.text_input(unit, **kwargs))
        with cols[offset + 2 * i + 1]:
            unit_label(unit)
    return parts


def run_stop_cells(cols, run_val, stop_val, key_prefix):
    with cols[C_RUN]:
        run_text = st.text_input("运行", value=run_val, key=f"{key_prefix}_run", label_visibility="collapsed")
    with cols[C_RUN + 1]:
        unit_label("秒")
    with cols[C_STOP]:
        stop_text = st.text_input("停止", value=stop_val, key=f"{key_prefix}_stop", label_visibility="collapsed")
    with cols[C_STOP + 1]:
        unit_label("秒")
    return run_text, stop_text


def join_dt(parts):
    y, mo, d, h, mi, s = [str(p).strip() for p in parts]
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)} {h.zfill(2)}:{mi.zfill(2)}:{s.zfill(2)}"


def split_dt(text):
    dt = pd.to_datetime(text)
    return [str(dt.year), f"{dt.month:02d}", f"{dt.day:02d}",
            f"{dt.hour:02d}", f"{dt.minute:02d}", f"{dt.second:02d}"]


# 首次进入，或时段列表发生变化后：开始时间自动衔接上一时段结束时间
if st.session_state.pop("_sync_form", False) or "sy" not in st.session_state:
    fill_form_fields(compute_form_start())

intervals = st.session_state.intervals
ver = st.session_state.edit_ver
row_inputs = []
action = None
add_pressed = False
clear_all = False

with st.container(key="grid"):
    # 表头
    hc = st.columns(GRID_W)
    with hc[0]:
        head_label("#")
    with hc[C_START]:
        head_label("开始时间")
    with hc[C_END]:
        head_label("结束时间")
    with hc[C_RUN]:
        head_label("多频集速运行")
    with hc[C_STOP]:
        head_label("多频集速停止")
    with hc[C_BTN]:
        head_label("上移/下移/删除")

    # 已有时段：每一行都可直接修改
    for i, item in enumerate(intervals):
        cols = st.columns(GRID_W)
        base = f"g{ver}_{i}"
        with cols[0]:
            unit_label(str(i + 1))
        try:
            sv, ev = split_dt(item["start"]), split_dt(item["end"])
        except Exception:
            sv, ev = [""] * 6, [""] * 6
        s_parts = time_cells(cols, C_START, [f"{base}_s{k}" for k in range(6)], sv)
        with cols[C_ARROW]:
            unit_label("→")
        e_parts = time_cells(cols, C_END, [f"{base}_e{k}" for k in range(6)], ev)
        run_text, stop_text = run_stop_cells(
            cols, str(item.get("run_sec", "0")), str(item.get("stop_sec", "-")), base
        )
        with cols[C_BTN]:
            if st.button("⬆️", key=f"{base}_up", disabled=(i == 0), use_container_width=True, help="上移"):
                action = ("up", i)
        with cols[C_BTN + 1]:
            if st.button("⬇️", key=f"{base}_down", disabled=(i == len(intervals) - 1), use_container_width=True, help="下移"):
                action = ("down", i)
        with cols[C_BTN + 2]:
            if st.button("❌", key=f"{base}_del", use_container_width=True, help="删除该时段"):
                action = ("del", i)
        row_inputs.append((s_parts, e_parts, run_text, stop_text))

    # 新增行：开始时间自动衔接上一时段结束时间，可手动修改
    ac = st.columns(GRID_W)
    with ac[0]:
        unit_label("➕")
    add_s = time_cells(ac, C_START, ["sy", "sm", "sd", "sh", "smin", "ss"])
    with ac[C_ARROW]:
        unit_label("→")
    add_e = time_cells(ac, C_END, ["ey", "em", "ed", "eh", "emin", "es"])
    add_run, add_stop = run_stop_cells(ac, "30", "780", "add")
    with ac[C_BTN]:
        add_pressed = st.button("➕", key="add_btn", use_container_width=True, help="添加这一行为新时段")

if intervals:
    clear_all = st.button("🗑️ 清空所有时段")
else:
    st.info("还没有时段：在上面“➕”这一行填写起止时间后点 ➕ 添加。")

# ---------- 汇总各行输入（无效的行保留原值） ----------
new_list, errors = [], []
for i, (s_parts, e_parts, run_text, stop_text) in enumerate(row_inputs):
    try:
        s = parse_interval_time(join_dt(s_parts))
        e = parse_interval_time(join_dt(e_parts))
        if s >= e:
            raise ValueError("开始时间必须早于结束时间")
        r, st_text = normalize_run_stop(run_text, stop_text)
        new_list.append({
            "start": s.strftime("%Y-%m-%d %H:%M:%S"),
            "end": e.strftime("%Y-%m-%d %H:%M:%S"),
            "run_sec": r,
            "stop_sec": st_text,
        })
    except Exception as exc:
        errors.append(f"第 {i + 1} 行：{exc}")
        new_list.append(dict(intervals[i]))

if clear_all:
    mutate_intervals([])
elif action:
    kind, idx = action
    if kind == "up" and idx > 0:
        new_list[idx - 1], new_list[idx] = new_list[idx], new_list[idx - 1]
    elif kind == "down" and idx < len(new_list) - 1:
        new_list[idx + 1], new_list[idx] = new_list[idx], new_list[idx + 1]
    elif kind == "del":
        new_list.pop(idx)
    mutate_intervals(new_list)
elif add_pressed:
    try:
        s = parse_interval_time(join_dt(add_s))
        e = parse_interval_time(join_dt(add_e))
        if s >= e:
            st.error("新增时段：开始时间必须早于结束时间！")
        else:
            r, st_text = normalize_run_stop(add_run, add_stop)
            new_list.append({
                "start": s.strftime("%Y-%m-%d %H:%M:%S"),
                "end": e.strftime("%Y-%m-%d %H:%M:%S"),
                "run_sec": r,
                "stop_sec": st_text,
            })
            mutate_intervals(new_list)
    except ValueError as exc:
        st.error(f"新增时段输入有误：{exc}")
    except Exception as exc:
        st.error(f"新增时段时间格式错误：{exc}")
elif not errors and new_list != intervals:
    # 直接改了某个小方框：保存，并让新增行的开始时间重新衔接
    mutate_intervals(new_list)

if errors:
    st.error("表格中有无效内容（已保留原值）：" + "；".join(errors))

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

                # 统一“负荷/压差”别名，同时同步更新实际使用的列名，避免 KeyError
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

                        # 负荷：填充面积 + 细线；压差：另一纵轴曲线
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

                    # 提供 PNG 下载，方便保存或转发
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
