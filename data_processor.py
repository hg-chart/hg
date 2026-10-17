# -*- coding: utf-8 -*-
"""模块三：数据读取与清洗过滤（支持多层复合表头智能展平与日期时间合并）"""
import json
import os
from pathlib import Path
import pandas as pd
import streamlit as st

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


def _flatten_multiindex_headers(df):
    """
    智能化清洗工厂多层复合表头：
    1. 自动前向填充合并单元格（如跨行的日期）
    2. 将多层级表头扁平化展平（如：1# + 斗提机电流(A) -> 1#斗提机电流(A)）
    3. 自动合并“日期”与“时间”列为标准的“时间”列，并剔除“班别”
    """
    # 如果是多层表头（MultiIndex）
    if isinstance(df.columns, pd.MultiIndex):
        # 1. 尝试前向填充合并单元格产生的 NaN（主要针对日期列）
        df = df.ffill()

        new_cols = []
        for col in df.columns:
            # 过滤掉 Unnamed 或空白的层级名称
            parts = [str(c).strip() for c in col if c is not None and "Unnamed" not in str(c) and str(c).strip() != "nan"]
            
            if not parts:
                new_cols.append("未知列")
                continue

            # 匹配常规字段
            combined_name = "".join(parts)
            if "日期" in combined_name:
                new_cols.append("日期")
            elif "时间" in combined_name:
                new_cols.append("时间")
            elif "班别" in combined_name:
                new_cols.append("班别")
            else:
                if len(parts) >= 2:
                    sub_tag = parts[-1]   # 如 1#
                    main_name = parts[0]  # 如 斗提机电流(A)
                    if "#" in sub_tag or "#号" in sub_tag or len(sub_tag) <= 4:
                        new_cols.append(f"{sub_tag}{main_name}")
                    else:
                        new_cols.append("_".join(parts))
                else:
                    new_cols.append(parts[0])
        
        df.columns = new_cols

    # 2. 清理列名空白与 BOM
    df.columns = df.columns.astype(str).str.strip().str.lstrip("\ufeff")

    # 3. 智能处理时间与日期合并
    # 检查是否存在明确的“日期”和“时间”列
    date_col = next((c for c in df.columns if "日期" in str(c)), None)
    time_col_name = next((c for c in df.columns if str(c).strip() == "时间" or "时间" in str(c)), None)

    if date_col and time_col_name and date_col != time_col_name:
        df[date_col] = df[date_col].ffill()
        try:
            # 拼接成完整时间字符串并转为 datetime
            combined_series = df[date_col].astype(str).str.strip() + " " + df[time_col_name].astype(str).str.strip()
            df["时间"] = pd.to_datetime(combined_series, errors="coerce")
        except Exception:
            pass
        # 清理掉旧的独立日期列，避免干扰
        df = df.drop(columns=[date_col], errors="ignore")
    else:
        # 如果只有单独的一个时间列，尝试直接转为 datetime
        for col in df.columns:
            if "时间" in str(col) or "time" in str(col).lower():
                df[col] = pd.to_datetime(df[col], errors="coerce")

    # 4. 自动剔除不需要的“班别”列
    if "班别" in df.columns:
        df = df.drop(columns=["班别"], errors="ignore")

    return df


def load_and_process_data(active_paths):
    """读取并智能清洗合并 CSV / Excel 文件，返回原始 DataFrame 与扁平化后的列名列表"""
    try:
        dataframes = []

        for file_path in active_paths:
            if file_path.lower().endswith(".csv"):
                df = None
                read_errors = []
                for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
                    try:
                        # 兼容可能带有 2 行复合表头的 CSV
                        df = pd.read_csv(file_path, encoding=encoding, header=[0, 1])
                        break
                    except Exception as exc:
                        read_errors.append(f"{encoding}: {exc}")
                
                # 如果多层表头读取失败，退回到单行表头读取
                if df is None:
                    try:
                        df = pd.read_csv(file_path, encoding="utf-8-sig")
                    except Exception as e:
                        raise ValueError(f"无法读取 CSV 文件 {Path(file_path).name}。错误：{e}")
            else:
                # Excel 读取：自动适配多级表头（前 2 行）
                try:
                    df = pd.read_excel(file_path, header=[0, 1])
                except Exception:
                    df = pd.read_excel(file_path, header=0)

            # 调用智能清洗函数
            df = _flatten_multiindex_headers(df)
            dataframes.append(df)

        df_raw = pd.concat(dataframes, ignore_index=True, sort=False)
        
        # 清理列名空白字符
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
        if "1#斗提机电流" in col or "W3.UNIT1.10DEHDCSAI03" in col:
            default_load_index = idx
            break

    col1_bot, col2_bot, col3_bot = st.columns(3)
    with col1_bot:
        time_col = st.selectbox(f"横坐标轴（{current_time_var}）请选择数据来源", columns, index=0)
    with col2_bot:
        load_col = st.selectbox(f"左纵轴（{current_load_var}）请选择数据来源", columns, index=default_load_index)
    with col3_bot:
        pressure_col = st.selectbox(f"右纵轴（{current_pressure_var}）请选择数据来源", columns, index=min(2, len(columns) - 1))

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
