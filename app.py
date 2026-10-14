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
    /* 时间输入小方框：紧凑、居中、缩小间距，减少鼠标移动距离 */
    .st-key-tb_add input, .st-key-tb_edit input {
        text-align: center; padding: 0.2rem 0.15rem; min-height: 2rem;
    }
    .st-key-tb_add [data-testid="stHorizontalBlock"],
    .st-key-tb_edit [data-testid="stHorizontalBlock"] {
        gap: 0.2rem; align-items: center;
    }
    .st-key-tb_add [data-testid="stVerticalBlock"],
    .st-key-tb_edit [data-testid="stVerticalBlock"] { gap: 0.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

TIME_FIELDS = [("年", 1.25), ("月", 0.85), ("日", 0.85), ("时", 0.85), ("分", 0.85), ("秒", 0.85)]


def unit_label(text):
    st.markdown(
        f"<div style='white-space:nowrap;text-align:center'>{text}</div>",
        unsafe_allow_html=True,
    )


def time_boxes(title, keys, values=None):
    """一行：标题 + [年]年[月]月[日]日[时]时[分]分[秒]秒 的独立小方框，返回 6 段文本。"""
    widths = [0.8]
    for _, w in TIME_FIELDS:
        widths += [w, 0.3]
    cols = st.columns(widths)
    with cols[0]:
        unit_label(title)
    parts = []
    for i, (unit, _) in enumerate(TIME_FIELDS):
        with cols[1 + 2 * i]:
            kwargs = {"key": keys[i], "label_visibility": "collapsed"}
            if values is not None:
                kwargs["value"] = values[i]
            parts.append(st.text_input(unit, **kwargs))
        with cols[2 + 2 * i]:
            unit_label(unit)
    return parts


def run_stop_boxes(run_default, stop_default, key_prefix=None):
    """一行：多频集速运行 [  ] 秒 停止 [  ] 秒。"""
    cols = st.columns([1.5, 1, 0.3, 0.7, 1, 0.3, 1.2])
    with cols[0]:
        unit_label("多频集速运行")
    with cols[1]:
        run_value = st.text_input(
            "运行秒数", value=run_default, label_visibility="collapsed",
            key=f"{key_prefix}_run" if key_prefix else None,
        )
    with cols[2]:
        unit_label("秒")
    with cols[3]:
        unit_label("停止")
    with cols[4]:
        stop_value = st.text_input(
            "停止秒数", value=stop_default, label_visibility="collapsed",
            key=f"{key_prefix}_stop" if key_prefix else None,
        )
    with cols[5]:
        unit_label("秒")
    return run_value, stop_value


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

left_form, _ = st.columns([7, 3])

with left_form:
    with st.container(key="tb_add"):
        with st.form("interval_form"):
            st.caption("➕ 添加新时段（开始时间自动衔接上一时段结束时间，可手动修改）")
            s_parts = time_boxes("开始：", ["sy", "sm", "sd", "sh", "smin", "ss"])
            e_parts = time_boxes("结束：", ["ey", "em", "ed", "eh", "emin", "es"])
            run_seconds, stop_seconds = run_stop_boxes("30", "780")
            add_interval = st.form_submit_button("➕ 添加时段到对比列表")

            if add_interval:
                try:
                    start_string = join_dt(s_parts)
                    end_string = join_dt(e_parts)
                    start_dt = pd.to_datetime(start_string)
                    end_dt = pd.to_datetime(end_string)

                    if start_dt >= end_dt:
                        st.error("开始时间必须早于结束时间！")
                    else:
                        run_text, stop_text = normalize_run_stop(run_seconds, stop_seconds)
                        new_list = list(st.session_state.intervals)
                        new_list.append({
                            "start": start_string,
                            "end": end_string,
                            "run_sec": run_text,
                            "stop_sec": stop_text,
                        })
                        mutate_intervals(new_list)
                except ValueError as exc:
                    st.error(f"输入有误：{exc}")
                except Exception as exc:
                    st.error(f"时间格式错误：{exc}")

# ------------------------------------------------------------
# 已添加时段：勾选一行 → 在下方小方框里修改；上移 / 下移 / 删除
# ------------------------------------------------------------
if st.session_state.intervals:
    intervals = st.session_state.intervals
    ver = st.session_state.edit_ver
    sel_rows = set(st.session_state.get("_sel_rows", []))

    st.write("当前已添加的对比时段（图表按此顺序依次排列）。勾选“选择”后，可在下方修改、上移/下移或删除：")
    table_df = pd.DataFrame([
        {
            "选择": i in sel_rows,
            "序号": i + 1,
            "开始时间": item["start"],
            "结束时间": item["end"],
            "多频集速运行(s)": str(item.get("run_sec", "0")),
            "多频集速停止(s)": str(item.get("stop_sec", "-")),
        }
        for i, item in enumerate(intervals)
    ])
    edited = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["序号", "开始时间", "结束时间", "多频集速运行(s)", "多频集速停止(s)"],
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", width="small"),
            "序号": st.column_config.NumberColumn("序号", width="small"),
        },
        key=f"interval_table_{ver}",
    )
    selected = [i for i, flag in enumerate(edited["选择"].tolist()) if flag]

    save = False
    with st.container(key="tb_edit"):
        panel, _ = st.columns([7, 3])
        with panel:
            if selected:
                active = selected[0]
                cur = intervals[active]
                st.caption(f"✏️ 修改时段 {active + 1}（改完点“保存修改”）")
                base = f"ed{ver}_{active}"
                try:
                    sv, ev = split_dt(cur["start"]), split_dt(cur["end"])
                except Exception:
                    sv, ev = [""] * 6, [""] * 6
                es_parts = time_boxes("开始：", [f"{base}_s{i}" for i in range(6)], sv)
                ee_parts = time_boxes("结束：", [f"{base}_e{i}" for i in range(6)], ev)
                edit_run, edit_stop = run_stop_boxes(
                    str(cur.get("run_sec", "0")), str(cur.get("stop_sec", "-")), key_prefix=base
                )
            else:
                st.caption("✏️ 勾选上方某一行，即可在这里修改它的起止时间和运行/停止秒数。")

            b1, b2, b3, b4, b5 = st.columns(5)
            with b1:
                save = st.button("💾 保存修改", type="primary", disabled=not selected, use_container_width=True)
            with b2:
                up = st.button("⬆️ 上移", disabled=not selected, use_container_width=True)
            with b3:
                down = st.button("⬇️ 下移", disabled=not selected, use_container_width=True)
            with b4:
                delete = st.button("❌ 删除", disabled=not selected, use_container_width=True)
            with b5:
                clear_all = st.button("🗑️ 清空", use_container_width=True)

    if clear_all:
        mutate_intervals([])
    elif save and selected:
        try:
            new_start = parse_interval_time(join_dt(es_parts))
            new_end = parse_interval_time(join_dt(ee_parts))
            if new_start >= new_end:
                st.error("开始时间必须早于结束时间！")
            else:
                run_text, stop_text = normalize_run_stop(edit_run, edit_stop)
                new_list = [dict(item) for item in intervals]
                new_list[active] = {
                    "start": new_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": new_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "run_sec": run_text,
                    "stop_sec": stop_text,
                }
                mutate_intervals(new_list, select=selected)
        except ValueError as exc:
            st.error(f"输入有误：{exc}")
        except Exception as exc:
            st.error(f"时间格式错误：{exc}")
    elif (up or down) and selected:
        chosen = set(selected)
        order = list(range(len(intervals)))
        if up:
            for i in sorted(chosen):
                if i > 0 and order[i - 1] not in chosen:
                    order[i - 1], order[i] = order[i], order[i - 1]
        else:
            for i in sorted(chosen, reverse=True):
                if i < len(order) - 1 and order[i + 1] not in chosen:
                    order[i + 1], order[i] = order[i], order[i + 1]
        moved_sel = [pos for pos, orig in enumerate(order) if orig in chosen]
        mutate_intervals([dict(intervals[o]) for o in order], select=moved_sel)
    elif delete and selected:
        mutate_intervals([dict(item) for i, item in enumerate(intervals) if i not in set(selected)])

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
