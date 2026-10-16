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
    """渲染数据列选择和负荷区间过滤配置"""
    st.subheader("2. 数据列选择配置")
    col1, col2, col3 = st.columns(3)

    default_load_index = min(1, len(columns) - 1)
    if "W3.UNIT1.10DEHDCSAI03" in columns:
        default_load_index = columns.index("W3.UNIT1.10DEHDCSAI03")

    with col1:
        time_col = st.selectbox("横坐标轴（时间列）请选择数据来源", columns, index=0)
    with col2:
        load_col = st.selectbox("左纵轴（机组负荷）请选择数据来源", columns, index=default_load_index)
    with col3:
        pressure_col = st.selectbox("右纵轴（压差）请选择数据来源", columns, index=min(2, len(columns) - 1))

    st.subheader("3. 负荷过滤配置（可选：支持单值下限或闭区间）")
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        min_threshold_text = st.text_input("负荷下限阈值（留空则不限制下限）", value="")
    with f_col2:
        max_threshold_text = st.text_input("负荷上限阈值（留空则只做大于等于下限过滤）", value="")

    min_threshold = None
    max_threshold = None
    filter_valid = True

    if min_threshold_text.strip():
        try:
            min_threshold = float(min_threshold_text.strip())
        except ValueError:
            filter_valid = False
            st.error("负荷下限必须是数字，例如 240。")

    if max_threshold_text.strip():
        try:
            max_threshold = float(max_threshold_text.strip())
        except ValueError:
            filter_valid = False
            st.error("负荷上限必须是数字，例如 250。")

    if filter_valid and min_threshold is not None and max_threshold is not None:
        if min_threshold > max_threshold:
            filter_valid = False
            st.error("负荷下限不能大于上限！")

    return time_col, load_col, pressure_col, min_threshold, max_threshold, filter_valid
