# -*- coding: utf-8 -*-
"""模块三：数据读取与清洗过滤"""
from pathlib import Path
import pandas as pd
import streamlit as st

COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

def load_and_process_data(active_paths):
    """读取并合并 CSV / Excel 文件，返回原始 DataFrame 与列名列表"""
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
        return df_raw, columns

    except Exception as exc:
        st.error(f"读取文件失败：{exc}")
        st.stop()


def render_column_and_filter_config(columns):
    """渲染数据列选择、坐标轴自定义命名、坐标轴名称锁定记忆与修改按钮控制"""
    
    # 获取当前选中的工厂名称（用于实现按工厂隔离保存配置）
    current_factory = st.session_state.get("selected_factory", "default_factory")
    config_state_key = f"axis_config_locked_{current_factory}"
    cache_key_prefix = f"factory_axis_cfg_{current_factory}"
    
    has_cached_config = cache_key_prefix in st.session_state
    
    if config_state_key not in st.session_state:
        st.session_state[config_state_key] = has_cached_config

    st.subheader("2. 数据列选择与坐标轴命名配置")

    # 1. 蓝色框部分：数据来源选择下拉框（保持动态，不参与锁定）
    default_load_index = min(1, len(columns) - 1)
    if "W3.UNIT1.10DEHDCSAI03" in columns:
        default_load_index = columns.index("W3.UNIT1.10DEHDCSAI03")

    col1_bot, col2_bot, col3_bot = st.columns(3)
    with col1_bot:
        time_col = st.selectbox("横坐标轴（时间列）请选择数据来源", columns, index=0)
    with col2_bot:
        load_col = st.selectbox("左纵轴请选择数据来源", columns, index=default_load_index)
    with col3_bot:
        pressure_col = st.selectbox("右纵轴请选择数据来源", columns, index=min(2, len(columns) - 1))

    st.markdown("---")

    # 2. 红色框部分：坐标轴自定义名称（支持锁定记忆与修改按钮）
    if st.session_state[config_state_key] and has_cached_config:
        cfg = st.session_state[cache_key_prefix]
        
        info_col1, info_col2, info_col3, btn_col = st.columns([2, 2, 2, 1])
        with info_col1:
            st.markdown(f"**横轴自定义名**：`{cfg['time_custom'] or '未命名'}`")
        with info_col2:
            st.markdown(f"**左纵轴自定义名**：`{cfg['load_custom'] or '未命名'}`")
        with info_col3:
            st.markdown(f"**右纵轴自定义名**：`{cfg['pressure_custom'] or '未命名'}`")
        with btn_col:
            if st.button("✏️ 修改", key=f"btn_edit_axis_{current_factory}", type="secondary", use_container_width=True):
                st.session_state[config_state_key] = False
                st.rerun()
                
        time_custom_label = cfg["time_custom"]
        load_custom_label = cfg["load_custom"]
        pressure_custom_label = cfg["pressure_custom"]
        
    else:
        st.info("💡 当前坐标轴名称尚未锁定，或您正在修改。调整完成后点击下方“保存并锁定坐标轴名称配置”即可记住此设置。")
        
        default_cfg = st.session_state.get(cache_key_prefix, {})
        
        col1_top, col2_top, col3_top = st.columns(3)
        with col1_top:
            time_custom_label = st.text_input("横轴自定义名称", value=default_cfg.get("time_custom", ""), placeholder="留空则默认取字段名")
        with col2_top:
            load_custom_label = st.text_input("左纵轴自定义名称", value=default_cfg.get("load_custom", ""), placeholder="留空则默认取字段名")
        with col3_top:
            pressure_custom_label = st.text_input("右纵轴自定义名称", value=default_cfg.get("pressure_custom", ""), placeholder="留空则默认取字段名")

        if st.button("💾 保存并锁定坐标轴名称配置", key=f"btn_save_axis_{current_factory}", type="primary"):
            st.session_state[cache_key_prefix] = {
                "time_custom": time_custom_label,
                "load_custom": load_custom_label,
                "pressure_custom": pressure_custom_label,
            }
            st.session_state[config_state_key] = True
            st.success("坐标轴名称配置已成功保存并锁定！")
            st.rerun()

    # 动态计算最终显示名称
    final_time_label = time_custom_label.strip() if time_custom_label.strip() else time_col
    
    raw_load_label = load_custom_label.strip() if load_custom_label.strip() else load_col
    final_load_label = f"{raw_load_label}（{load_col}）"

    raw_pressure_label = pressure_custom_label.strip() if pressure_custom_label.strip() else pressure_col
    final_pressure_label = f"{raw_pressure_label}（{pressure_col}）"

    # 第三部分：交互式选择要过滤的目标变量
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
