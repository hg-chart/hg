# -*- coding: utf-8 -*-
"""设备运行数据多文件多时段汇总对比分析系统"""

import os
import json
import logging
import uuid
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
                    {**dict(item), "_uid": uuid.uuid4().hex[:10]}
                    for item in st.session_state.saved_templates[chosen_template]
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
                    {key: value for key, value in item.items() if key != "_uid"}
                    for item in st.session_state.intervals
                ]
                if save_persistent_templates(st.session_state.saved_templates):
                    st.success(f"方案“{template_name.strip()}”已保存。")
                    st.rerun()

# 为每个时段分配稳定标识，避免调整顺序后编辑框串位
def ensure_interval_ids():
    changed = False
    for item in st.session_state.intervals:
        if "_uid" not in item:
            item["_uid"] = uuid.uuid4().hex[:10]
            changed = True
    return changed


ensure_interval_ids()

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
# 当上一个时段结束时间或时段数量变化时，使用新的 widget key，
# 使新增时段的开始时间自动衔接上一时段结束时间，同时允许用户手动改动。
start_key_seed = f"{len(st.session_state.intervals)}_{default_start.strftime('%Y%m%d%H%M%S')}"
left_form, _ = st.columns([1, 1])

with left_form:
    with st.form("interval_form"):
        st.markdown("🕒 **开始时间（默认自动衔接上一时段结束时间，可手动修改）**")
        sy1, sy2, sy3, sy4, sy5, sy6 = st.columns(6)
        with sy1:
            start_year = st.text_input("年", value=str(default_start.year), key=f"sy_{start_key_seed}")
        with sy2:
            start_month = st.text_input("月", value=f"{default_start.month:02d}", key=f"sm_{start_key_seed}")
        with sy3:
            start_day = st.text_input("日", value=f"{default_start.day:02d}", key=f"sd_{start_key_seed}")
        with sy4:
            start_hour = st.text_input("时", value=f"{default_start.hour:02d}", key=f"sh_{start_key_seed}")
        with sy5:
            start_minute = st.text_input("分", value=f"{default_start.minute:02d}", key=f"smin_{start_key_seed}")
        with sy6:
            start_second = st.text_input("秒", value=f"{default_start.second:02d}", key=f"ss_{start_key_seed}")

        st.markdown("🕒 **结束时间**")
        ey1, ey2, ey3, ey4, ey5, ey6 = st.columns(6)
        with ey1:
            end_year = st.text_input("年 ", value=str(default_end.year), key=f"ey_{start_key_seed}")
        with ey2:
            end_month = st.text_input("月 ", value=f"{default_end.month:02d}", key=f"em_{start_key_seed}")
        with ey3:
            end_day = st.text_input("日 ", value=f"{default_end.day:02d}", key=f"ed_{start_key_seed}")
        with ey4:
            end_hour = st.text_input("时 ", value=f"{default_end.hour:02d}", key=f"eh_{start_key_seed}")
        with ey5:
            end_minute = st.text_input("分 ", value=f"{default_end.minute:02d}", key=f"emin_{start_key_seed}")
        with ey6:
            end_second = st.text_input("秒 ", value=f"{default_end.second:02d}", key=f"es_{start_key_seed}")

        run_col, stop_col = st.columns(2)
        with run_col:
            run_seconds = st.text_input("多频集速运行秒数", value="30", key=f"run_{start_key_seed}")
        with stop_col:
            stop_seconds = st.text_input("多频集速停止秒数（运行秒数为 0 时可不填）", value="780", key=f"stop_{start_key_seed}")

        add_interval = st.form_submit_button("➕ 添加时段到对比列表", use_container_width=True)

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
                        "_uid": uuid.uuid4().hex[:10],
                        "start": start_string,
                        "end": end_string,
                        "run_sec": run_text,
                        "stop_sec": stop_text,
                    })
                    st.success("时段添加成功！")
                    st.rerun()
            except Exception as exc:
                st.error(f"时间格式错误：{exc}")

if st.session_state.intervals:
    st.write("当前已添加的对比时段：点击下面任意一条记录，即可在此列表区域直接编辑、移动或删除。")

    # 以可点击的时段行代替静态 dataframe；选择后编辑器就在列表下方显示。
    current_uids = [item["_uid"] for item in st.session_state.intervals]
    if st.session_state.get("selected_interval_uid") not in current_uids:
        st.session_state.selected_interval_uid = current_uids[0]

    for index, interval in enumerate(st.session_state.intervals):
        uid = interval["_uid"]
        selected_now = st.session_state.selected_interval_uid == uid
        label = f"{'🔵 已选中  ' if selected_now else '　'}时段 {index + 1}　｜　{interval.get('start', '')} 至 {interval.get('end', '')}　｜　运行 {interval.get('run_sec', '0')} 秒 / 停止 {interval.get('stop_sec', '-')} 秒"
        if st.button(label, key=f"select_row_{uid}", use_container_width=True, type="primary" if selected_now else "secondary"):
            st.session_state.selected_interval_uid = uid
            st.rerun()

    # 在列表区域内直接显示当前选中时段的编辑表单
    selected_uid = st.session_state.get("selected_interval_uid")
    selected_index = next((i for i, item in enumerate(st.session_state.intervals) if item["_uid"] == selected_uid), 0)
    interval = st.session_state.intervals[selected_index]
    uid = interval["_uid"]
    st.markdown(f"#### ✏️ 编辑已选中的时段 {selected_index + 1}")
    st.caption("年月日时分秒分别填写在独立格子中；修改后点击保存。")
    start_dt0 = pd.to_datetime(interval.get("start", datetime.now()))
    end_dt0 = pd.to_datetime(interval.get("end", datetime.now() + timedelta(minutes=50)))

    with st.form(f"edit_selected_interval_{uid}"):
        st.markdown("**开始时间**")
        a1, a2, a3, a4, a5, a6 = st.columns(6)
        with a1: esy = st.text_input("年", value=f"{start_dt0.year:04d}", key=f"esy_{uid}")
        with a2: esm = st.text_input("月", value=f"{start_dt0.month:02d}", key=f"esm_{uid}")
        with a3: esd = st.text_input("日", value=f"{start_dt0.day:02d}", key=f"esd_{uid}")
        with a4: esh = st.text_input("时", value=f"{start_dt0.hour:02d}", key=f"esh_{uid}")
        with a5: esmin = st.text_input("分", value=f"{start_dt0.minute:02d}", key=f"esmin_{uid}")
        with a6: ess = st.text_input("秒", value=f"{start_dt0.second:02d}", key=f"ess_{uid}")
        st.markdown("**结束时间**")
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        with b1: eey = st.text_input("年 ", value=f"{end_dt0.year:04d}", key=f"eey_{uid}")
        with b2: eem = st.text_input("月 ", value=f"{end_dt0.month:02d}", key=f"eem_{uid}")
        with b3: eed = st.text_input("日 ", value=f"{end_dt0.day:02d}", key=f"eed_{uid}")
        with b4: eeh = st.text_input("时 ", value=f"{end_dt0.hour:02d}", key=f"eeh_{uid}")
        with b5: eemin = st.text_input("分 ", value=f"{end_dt0.minute:02d}", key=f"eemin_{uid}")
        with b6: ees = st.text_input("秒 ", value=f"{end_dt0.second:02d}", key=f"ees_{uid}")
        edit_run_col, edit_stop_col = st.columns(2)
        with edit_run_col:
            edit_run = st.text_input("多频集速运行秒数", value=str(interval.get("run_sec", "0")), key=f"edit_run_{uid}")
        with edit_stop_col:
            edit_stop = st.text_input("多频集速停止秒数（运行秒数为 0 时可不填）", value=str(interval.get("stop_sec", "-")), key=f"edit_stop_{uid}")
        save_edit = st.form_submit_button("💾 保存此时段修改", use_container_width=True)

    if save_edit:
        try:
            start_string = f"{esy.strip()}-{esm.strip().zfill(2)}-{esd.strip().zfill(2)} {esh.strip().zfill(2)}:{esmin.strip().zfill(2)}:{ess.strip().zfill(2)}"
            end_string = f"{eey.strip()}-{eem.strip().zfill(2)}-{eed.strip().zfill(2)} {eeh.strip().zfill(2)}:{eemin.strip().zfill(2)}:{ees.strip().zfill(2)}"
            start_dt = pd.to_datetime(start_string, format="%Y-%m-%d %H:%M:%S", errors="raise")
            end_dt = pd.to_datetime(end_string, format="%Y-%m-%d %H:%M:%S", errors="raise")
            if start_dt >= end_dt:
                st.error("开始时间必须早于结束时间！")
            else:
                run_text = edit_run.strip() or "0"
                stop_text = "-" if run_text in ("0", "0.0") else (edit_stop.strip() or "-")
                interval["start"] = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                interval["end"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                interval["run_sec"] = run_text
                interval["stop_sec"] = stop_text
                st.success(f"时段 {selected_index + 1} 修改成功。")
                st.rerun()
        except Exception as exc:
            st.error(f"时间格式错误，请检查各输入格：{exc}")

    # 顺序和删除按钮紧贴当前选中时段的编辑区域，不再分散到各个展开窗口。
    c_up, c_down, c_delete, c_clear = st.columns(4)
    with c_up:
        if st.button("⬆️ 上移", key=f"move_up_selected_{uid}", disabled=(selected_index == 0), use_container_width=True):
            st.session_state.intervals[selected_index - 1], st.session_state.intervals[selected_index] = st.session_state.intervals[selected_index], st.session_state.intervals[selected_index - 1]
            st.rerun()
    with c_down:
        if st.button("⬇️ 下移", key=f"move_down_selected_{uid}", disabled=(selected_index == len(st.session_state.intervals) - 1), use_container_width=True):
            st.session_state.intervals[selected_index + 1], st.session_state.intervals[selected_index] = st.session_state.intervals[selected_index], st.session_state.intervals[selected_index + 1]
            st.rerun()
    with c_delete:
        if st.button("🗑️ 删除选中时段", key=f"delete_selected_{uid}", use_container_width=True):
            st.session_state.intervals = [item for item in st.session_state.intervals if item.get("_uid") != uid]
            remaining = st.session_state.intervals
            st.session_state.selected_interval_uid = remaining[min(selected_index, len(remaining)-1)]["_uid"] if remaining else None
            st.rerun()
    with c_clear:
        if st.button("🧹 清空所有时段", key="clear_all_intervals", use_container_width=True):
            st.session_state.intervals = []
            st.session_state.selected_interval_uid = None
            st.rerun()

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
