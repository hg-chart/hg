# -*- coding: utf-8 -*-
"""模块三：数据读取与清洗过滤（完美适配 CSV 单行表头与 Excel 多级表头）"""
import json
import os
import re
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
import pandas as pd
import streamlit as st


# ============================================================
# 通用日期时间解析（支持中文日期、点号/斜杠日期、Excel 序列号等）
# ============================================================
_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_DOT_DATE_RE = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})")
_HAS_DATE_OR_TIME_RE = re.compile(r"\d{4}|\d{1,2}:\d{2}")
_LEADING_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]+\d{1,2}:\d{2}(?::\d{2})?)?")
_HMS_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?$")


def _normalize_dt_text(text):
    """把各种写法统一成 pandas 能识别的形式。
    2026年5月21日 -> 2026-05-21；2026.9.13 -> 2026-09-13；8时30分 -> 8:30
    """
    s = str(text).strip().replace("：", ":").replace("／", "/")
    s = _CN_DATE_RE.sub(lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d} ", s)
    s = _DOT_DATE_RE.sub(lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", s)
    s = re.sub(r"(\d{1,2})\s*时\s*(\d{1,2})\s*分\s*(\d{1,2})\s*秒?", r"\1:\2:\3", s)
    s = re.sub(r"(\d{1,2})\s*时\s*(\d{1,2})\s*分?", r"\1:\2", s)
    s = re.sub(r"(\d{1,2})\s*时", r"\1:00", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_missing(value):
    return value is None or (isinstance(value, float) and value != value) or value is pd.NaT


def _to_datetime_input(value):
    """单个单元格 -> 可交给 pd.to_datetime 的值；无法识别返回 None。"""
    if _is_missing(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp, date)):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Excel 日期序列号（约 1954 年～2119 年）；其他数字不是日期，避免把普通数值误当日期
        if 20000 < float(value) < 80000:
            return datetime(1899, 12, 30) + timedelta(days=float(value))
        return None
    text = _normalize_dt_text(value)
    if not text or not _HAS_DATE_OR_TIME_RE.search(text):
        return None
    # 日期后面带了备注文字（如“2026年7月13日 工作45秒 停15分钟”）时，只取前面的日期时间部分
    m = _LEADING_DT_RE.match(text)
    if m:
        rest = text[m.end():].strip()
        if rest and re.search(r"[^\d:.\sTZ+\-]", rest):
            return m.group(0)
    return text


def parse_datetime_series(series):
    """把一列时间数据稳健地转成 datetime64；识别不了的变成 NaT。"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    cleaned = series.map(_to_datetime_input)
    return pd.to_datetime(cleaned, format="mixed", errors="coerce")


def is_date_only(parsed):
    """这列时间是否只有日期、没有具体时刻（所有有效值都恰好是 00:00:00）。"""
    valid = parsed.dropna()
    if valid.empty:
        return False
    return bool((valid == valid.dt.normalize()).all())


def _time_of_day(series):
    """只取每个单元格里的“时:分:秒”，忽略其日期部分（Excel 常把纯时间存成 1900-01-xx）。"""
    def one(v):
        if _is_missing(v):
            return pd.NaT
        if isinstance(v, (datetime, pd.Timestamp, dt_time)):
            return timedelta(hours=v.hour, minutes=v.minute, seconds=v.second)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return timedelta(days=float(v) % 1)  # Excel 时间小数
        text = _normalize_dt_text(v)
        m = _HMS_RE.match(text)
        if m:
            return timedelta(hours=int(m[1]), minutes=int(m[2]), seconds=int(m[3] or 0))
        try:
            ts = pd.Timestamp(text)
            return timedelta(hours=ts.hour, minutes=ts.minute, seconds=ts.second)
        except Exception:
            return pd.NaT

    return pd.to_timedelta(series.map(one))



# ============================================================
# 纵轴刻度：判断左右纵轴是否为同一类数据
# ============================================================
SCALE_AUTO = "自动判断（同类数据自动统一刻度）"
SCALE_SAME = "强制统一刻度"
SCALE_INDEP = "各自独立刻度"
SCALE_OPTIONS = [SCALE_AUTO, SCALE_SAME, SCALE_INDEP]

# 数据类型关键词（越靠前优先级越高，例如“压差”要先于“压力”判断）。需要新类型时在这里补充即可。
_KIND_KEYWORDS = [
    ("压差", ("压差", "差压")),
    ("负压", ("负压",)),
    ("压力", ("压力", "气压")),
    ("负荷", ("负荷", "负载")),
    ("功率", ("功率",)),
    ("电流", ("电流",)),
    ("电压", ("电压",)),
    ("温度", ("温度",)),
    ("湿度", ("湿度",)),
    ("流量", ("流量",)),
    ("转速", ("转速",)),
    ("频率", ("频率",)),
    ("液位", ("液位", "料位")),
    ("浓度", ("浓度",)),
    ("振动", ("振动",)),
]


def detect_data_kind(text):
    """根据文字里的关键词判断数据类型，认不出返回 None。"""
    text = str(text or "")
    for kind, words in _KIND_KEYWORDS:
        if any(w in text for w in words):
            return kind
    return None


def _name_stem(text):
    """去掉数字、编号符号和空白后的名称主干，如 安装前1#仓压差 / 安装前2#仓压差 -> 安装前仓压差。"""
    return re.sub(r"[\d#＃\s_\-（）()\.]+", "", str(text or ""))


def detect_axis_kind(label, col):
    """判断一个纵轴的数据类型：优先看用户起的坐标轴名称，认不出再看数据列名。"""
    return detect_data_kind(label) or detect_data_kind(col)


def axes_same_kind(left_label, left_col, right_label, right_col):
    """左右纵轴是否同类。返回 (是否同类, 说明文字)。"""
    k_left = detect_axis_kind(left_label, left_col)
    k_right = detect_axis_kind(right_label, right_col)
    if k_left and k_right:
        if k_left == k_right:
            return True, f"左右纵轴都是【{k_left}】"
        return False, f"左纵轴是【{k_left}】、右纵轴是【{k_right}】，不是同一类"
    stem_left = _name_stem(left_label or left_col)
    stem_right = _name_stem(right_label or right_col)
    if stem_left and stem_left == stem_right:
        return True, "左右纵轴的名称只有编号不同，按同类处理"
    return False, "无法判断左右纵轴是否同类，按各自独立刻度处理（可手动选择“强制统一刻度”）"


def should_unify_axes(mode, left_label, left_col, right_label, right_col):
    """根据用户选择的模式，决定两个纵轴是否使用完全相同的刻度。返回 (是否统一, 说明)。"""
    if mode == SCALE_SAME:
        return True, "已手动选择：两个纵轴使用相同刻度"
    if mode == SCALE_INDEP:
        return False, "已手动选择：两个纵轴各自独立刻度"
    return axes_same_kind(left_label, left_col, right_label, right_col)


COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

CONFIG_FILE = "factory_axis_configs.json"

def _load_all_axis_configs():
    """从本地 JSON 文件加载所有工厂的坐标轴配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_all_axis_configs(configs):
    """将所有工厂的坐标轴配置保存到本地 JSON 文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def _clean_dataframe_columns(df):
    """清洗单行表头 DataFrame：清理空白、剔除 Unnamed 空白列、解析并合并日期与时间"""
    # 1. 过滤掉所有以 Unnamed 开头的空白列
    df = df.loc[:, ~df.columns.astype(str).str.contains('^Unnamed', na=False)].copy()

    # 2. 清理列名两端的空格与BOM
    df.columns = df.columns.astype(str).str.strip().str.lstrip("\ufeff")

    # 3. 智能处理时间与日期（如存在独立“日期”列和“时间”列则合并）
    date_col = next((c for c in df.columns if "日期" in str(c)), None)
    time_col_name = next((c for c in df.columns if str(c).strip() == "时间" or "时间" in str(c)), None)

    if date_col and time_col_name and date_col != time_col_name:
        # 日期列通常每天只在第一行填写（合并单元格），先向下补齐
        dates = parse_datetime_series(df[date_col].ffill())
        tod = _time_of_day(df[time_col_name])
        # 有日期但时间格子留空的行：按约定取 00:00:00（写了内容却无法识别的仍保持为空）
        blank = df[time_col_name].isna() | df[time_col_name].astype(str).str.strip().eq("")
        tod = tod.where(~blank, pd.Timedelta(0))
        df["时间"] = dates.dt.normalize() + tod
        df = df.drop(columns=[date_col], errors="ignore")
    else:
        for col in list(df.columns):
            if "时间" in str(col) or "time" in str(col).lower():
                parsed = parse_datetime_series(df[col])
                non_null = df[col].notna().sum()
                # 至少一半以上能识别成时间才转换，避免把“运行时间(h)”这类数值列误改成空值
                if non_null > 0 and parsed.notna().sum() >= 0.5 * non_null:
                    df[col] = parsed

    # 4. 自动剔除“班别”列
    if "班别" in df.columns:
        df = df.drop(columns=["班别"], errors="ignore")

    # 5. 去除全空行
    df = df.dropna(how='all')

    return df


def load_and_process_data(active_paths):
    """读取并智能清洗合并 CSV / Excel 文件，返回原始 DataFrame 与干净的列名列表"""
    try:
        dataframes = []

        for file_path in active_paths:
            df = None
            if file_path.lower().endswith(".csv"):
                read_errors = []
                for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
                    try:
                        # CSV 统一按单行标准表头 header=0 读取
                        df = pd.read_csv(file_path, encoding=encoding, header=0)
                        break
                    except Exception as exc:
                        read_errors.append(f"{encoding}: {exc}")
                
                if df is None:
                    raise ValueError(f"无法读取 CSV 文件 {Path(file_path).name}。错误：" + "；".join(read_errors))
            else:
                # Excel 可能是多级表头，尝试 header=[0, 1]，失败则退回 header=0
                try:
                    df = pd.read_excel(file_path, header=[0, 1])
                    if isinstance(df.columns, pd.MultiIndex):
                        # 如果是多级表头，展平
                        df.columns = ["_".join([str(c).strip() for c in col if str(c) != "nan" and "Unnamed" not in str(c)]) for col in df.columns]
                except Exception:
                    df = pd.read_excel(file_path, header=0)

            # 执行通用清洗
            df = _clean_dataframe_columns(df)
            dataframes.append(df)

        df_raw = pd.concat(dataframes, ignore_index=True, sort=False)
        
        # 提取最终干净的列名列表（排除任何空值或 Unnamed）
        columns = [str(c).strip() for c in df_raw.columns if str(c).strip() and "Unnamed" not in str(c)]
        return df_raw, columns

    except Exception as exc:
        st.error(f"读取文件失败：{exc}")
        st.stop()


def render_column_and_filter_config(columns):
    """渲染数据列选择、坐标轴自定义命名、本地持久化记忆与修改按钮控制"""
    
    current_factory = st.session_state.get("selected_factory", "default_factory")
    all_configs = _load_all_axis_configs()
    factory_cfg = all_configs.get(current_factory, {})
    
    config_state_key = f"axis_config_locked_{current_factory}"
    has_persisted_config = bool(factory_cfg)
    
    if config_state_key not in st.session_state:
        st.session_state[config_state_key] = has_persisted_config

    st.subheader("2. 数据列选择与坐标轴命名配置")

    if st.session_state[config_state_key] and has_persisted_config:
        info_col1, info_col2, info_col3, btn_col = st.columns([2, 2, 2, 1])
        with info_col1:
            st.markdown(f"**横轴自定义名**：`{factory_cfg.get('time_custom') or '未命名'}`")
        with info_col2:
            st.markdown(f"**左纵轴自定义名**：`{factory_cfg.get('load_custom') or '未命名'}`")
        with info_col3:
            st.markdown(f"**右纵轴自定义名**：`{factory_cfg.get('pressure_custom') or '未命名'}`")
        with btn_col:
            if st.button("✏️ 修改", key=f"btn_edit_axis_{current_factory}", type="secondary", use_container_width=True):
                st.session_state[config_state_key] = False
                st.rerun()
                
        time_custom_label = factory_cfg.get("time_custom", "")
        load_custom_label = factory_cfg.get("load_custom", "")
        pressure_custom_label = factory_cfg.get("pressure_custom", "")
        
    else:
        st.info("💡 当前坐标轴名称尚未锁定，或您正在修改。调整完成后点击下方“保存并锁定坐标轴名称配置”即可记住此设置。")
        
        col1_top, col2_top, col3_top = st.columns(3)
        with col1_top:
            time_custom_label = st.text_input("横轴自定义名称", value=factory_cfg.get("time_custom", ""), placeholder="留空则默认取字段名")
        with col2_top:
            load_custom_label = st.text_input("左纵轴自定义名称", value=factory_cfg.get("load_custom", ""), placeholder="留空则默认取字段名")
        with col3_top:
            pressure_custom_label = st.text_input("右纵轴自定义名称", value=factory_cfg.get("pressure_custom", ""), placeholder="留空则默认取字段名")

        if st.button("💾 保存并锁定坐标轴名称配置", key=f"btn_save_axis_{current_factory}", type="primary"):
            all_configs[current_factory] = {
                "time_custom": time_custom_label,
                "load_custom": load_custom_label,
                "pressure_custom": pressure_custom_label,
            }
            _save_all_axis_configs(all_configs)
            st.session_state[config_state_key] = True
            st.success("坐标轴名称配置已成功保存并永久锁定！")
            st.rerun()

    st.markdown("---")

    current_time_var = time_custom_label.strip() if time_custom_label.strip() else "时间列"
    current_load_var = load_custom_label.strip() if load_custom_label.strip() else "左纵轴"
    current_pressure_var = pressure_custom_label.strip() if pressure_custom_label.strip() else "右纵轴"

    default_load_index = min(1, len(columns) - 1)
    for idx, col in enumerate(columns):
        if "斗提机电流" in col or "1＃" in col:
            default_load_index = idx
            break

    col1_bot, col2_bot, col3_bot = st.columns(3)
    with col1_bot:
        time_col = st.selectbox(f"横坐标轴（{current_time_var}）请选择数据来源", columns, index=0)
    with col2_bot:
        load_col = st.selectbox(f"左纵轴（{current_load_var}）请选择数据来源", columns, index=default_load_index)
    with col3_bot:
        pressure_col = st.selectbox(f"右纵轴（{current_pressure_var}）请选择数据来源", columns, index=min(2, len(columns) - 1))

    # 纵轴刻度模式：左右同类数据（如都是压差）时，两个纵轴刻度完全相同，便于直接对比
    scale_mode = st.radio(
        "纵轴刻度",
        SCALE_OPTIONS,
        horizontal=True,
        key="axis_scale_mode",
        help="自动判断：左右纵轴是同一类数据（如都是压差）时，两个纵轴的刻度范围和刻度线完全一致；"
             "不同类（如负荷对压差）时各自独立。",
    )
    _unify, _unify_reason = should_unify_axes(
        scale_mode, load_custom_label.strip(), load_col, pressure_custom_label.strip(), pressure_col
    )
    st.caption(("📏 两个纵轴将使用相同刻度：" if _unify else "📐 两个纵轴使用各自独立刻度：") + _unify_reason)

    final_time_label = time_custom_label.strip() if time_custom_label.strip() else time_col
    
    raw_load_label = load_custom_label.strip() if load_custom_label.strip() else load_col
    final_load_label = f"{raw_load_label}（{load_col}）"

    raw_pressure_label = pressure_custom_label.strip() if pressure_custom_label.strip() else pressure_col
    final_pressure_label = f"{raw_pressure_label}（{pressure_col}）"

    st.subheader("3. 数据过滤配置（可选：支持单值下限或闭区间）")
    
    available_filter_metrics = [raw_load_label, raw_pressure_label]
    
    sel_col1, sel_col2 = st.columns([1, 2])
    with sel_col1:
        selected_filter_metric = st.selectbox("选择过滤目标变量", options=available_filter_metrics, index=0)
    
    if selected_filter_metric == raw_load_label:
        filter_target_col = load_col
    else:
        filter_target_col = pressure_col

    with sel_col2:
        st.info(f"💡 当前正在对 **{selected_filter_metric}**（对应列：`{filter_target_col}`）设置数值区间过滤。")

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        min_threshold_text = st.text_input(f"{selected_filter_metric}下限阈值（留空则不限制下限）", value="")
    with f_col2:
        max_threshold_text = st.text_input(f"{selected_filter_metric}上限阈值（留空则只做大于等于下限过滤）", value="")

    min_threshold = None
    max_threshold = None
    filter_valid = True

    if min_threshold_text.strip():
        try:
            min_threshold = float(min_threshold_text.strip())
        except ValueError:
            filter_valid = False
            st.error(f"{selected_filter_metric}下限必须是数字。")

    if max_threshold_text.strip():
        try:
            max_threshold = float(max_threshold_text.strip())
        except ValueError:
            filter_valid = False
            st.error(f"{selected_filter_metric}上限必须是数字。")

    if filter_valid and min_threshold is not None and max_threshold is not None:
        if min_threshold > max_threshold:
            filter_valid = False
            st.error(f"{selected_filter_metric}下限不能大于上限！")

    return (
        time_col, load_col, pressure_col, 
        min_threshold, max_threshold, filter_valid, 
        final_time_label, final_load_label, final_pressure_label,
        filter_target_col, selected_filter_metric
    )
