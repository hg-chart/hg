# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import datetime, timedelta

# 设置网页布局
st.set_page_config(page_title="设备运行数据多文件多时段汇总对比分析系统", layout="wide")

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

st.title("📊 设备运行数据多文件多时段汇总对比分析系统")
st.markdown("---")

# --- 1. 文件上传区域 ---
st.subheader("1. 表格文件上传（支持多选 CSV / XLSX）")
uploaded_files = st.file_uploader("请上传您的工业数据表格文件", type=["csv", "xlsx", "xls"], accept_multiple_files=True)

if uploaded_files:
    file_paths = []
    dfs_list = []
    
    for uploaded_file in uploaded_files:
        with open(uploaded_file.name, "wb") as f:
            f.write(uploaded_file.getbuffer())
        file_paths.append(uploaded_file.name)
    
    st.success(f"已成功上传 {len(uploaded_files)} 个文件。")

    # 极速读取所有文件并兼容多编码
    try:
        for f_path in file_paths:
            if f_path.lower().endswith('.csv'):
                df_temp = None
                for enc in ['utf-8', 'gbk', 'gb18030', 'latin1']:
                    try:
                        df_temp = pd.read_csv(f_path, encoding=enc)
                        break
                    except Exception:
                        continue
                if df_temp is None:
                    df_temp = pd.read_csv(f_path, encoding='utf-8', errors='ignore')
            else:
                xls = pd.ExcelFile(f_path)
                sheets = [pd.read_excel(f_path, sheet_name=s) for s in xls.sheet_names]
                df_temp = pd.concat(sheets, ignore_index=True) if sheets else pd.DataFrame()
            
            df_temp.columns = df_temp.columns.astype(str).str.strip().str.lstrip('\ufeff')
            dfs_list.append(df_temp)
        
        df_all_raw = pd.concat(dfs_list, ignore_index=True) if dfs_list else pd.DataFrame()
        cols = [str(c).strip() for c in df_all_raw.columns if pd.notna(c) and str(c).strip() != ""]
    except Exception as e:
        cols = []
        st.error(f"读取文件失败: {e}")

    if cols:
        # --- 2. 数据列选择配置 ---
        st.subheader("2. 数据列选择配置")
        col1, col2, col3 = st.columns(3)
        with col1:
            time_col = st.selectbox("横坐标轴 (时间列)", cols, index=0 if len(cols)>0 else 0)
        with col2:
            load_col = st.selectbox("负荷左纵轴", cols, index=1 if len(cols)>1 else 0)
        with col3:
            pressure_col = st.selectbox("压差右纵轴", cols, index=2 if len(cols)>2 else 0)

        # --- 3. 负荷阈值过滤 ---
        st.subheader("3. 负荷过滤配置（可选）")
        threshold_input = st.text_input("负荷下限阈值 (留空则取全部数据)", value="")
        threshold = float(threshold_input) if threshold_input.strip() else None

        # --- 4. 多时段对比配置（年月日时分秒独立格子输入 + 自动衔接） ---
        st.subheader("4. 多时段对比配置（自动时间衔接）")
        
        if 'intervals' not in st.session_state:
            st.session_state.intervals = []

        # 默认起始时间（优先取上一时段结束时间，其次取表格最早时间）
        default_dt = datetime.now()
        if st.session_state.intervals:
            try:
                default_dt = pd.to_datetime(st.session_state.intervals[-1]['end'])
            except Exception:
                pass
        else:
            try:
                df_all_raw[time_col] = pd.to_datetime(df_all_raw[time_col].astype(str).str.strip(), format='mixed', errors='coerce')
                valid_min = df_all_raw[time_col].min()
                if pd.notna(valid_min):
                    default_dt = valid_min
            except Exception:
                pass

        default_end_dt = default_dt + timedelta(minutes=50)

        with st.form("interval_form"):
            st.markdown("🕒 **开始时间设置**")
            sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
            with sc1: s_y = st.text_input("开始-年", value=str(default_dt.year))
            with sc2: s_m = st.text_input("开始-月", value=f"{default_dt.month:02d}")
            with sc3: s_d = st.text_input("开始-日", value=f"{default_dt.day:02d}")
            with sc4: s_h = st.text_input("开始-时", value=f"{default_dt.hour:02d}")
            with sc5: s_min = st.text_input("开始-分", value=f"{default_dt.minute:02d}")
            with sc6: s_sec = st.text_input("开始-秒", value=f"{default_dt.second:02d}")

            st.markdown("🕒 **结束时间设置**")
            ec1, ec2, ec3, ec4, ec5, ec6 = st.columns(6)
            with ec1: e_y = st.text_input("结束-年", value=str(default_end_dt.year))
            with ec2: e_m = st.text_input("结束-月", value=f"{default_end_dt.month:02d}")
            with ec3: e_d = st.text_input("结束-日", value=f"{default_end_dt.day:02d}")
            with ec4: e_h = st.text_input("结束-时", value=f"{default_end_dt.hour:02d}")
            with ec5: e_min = st.text_input("结束-分", value=f"{default_end_dt.minute:02d}")
            with ec6: e_sec = st.text_input("结束-秒", value=f"{default_end_dt.second:02d}")

            rc1, rc2 = st.columns(2)
            with rc1:
                run_sec = st.text_input("多频集速运行秒数", "30")
            with rc2:
                stop_sec = st.text_input("停止秒数 (若运行为0可不填)", "780")
            
            submitted = st.form_submit_button("➕ 添加该时段到对比列表")
            if submitted:
                try:
                    start_str = f"{s_y.strip()}-{s_m.strip().zfill(2)}-{s_d.strip().zfill(2)} {s_h.strip().zfill(2)}:{s_min.strip().zfill(2)}:{s_sec.strip().zfill(2)}"
                    end_str = f"{e_y.strip()}-{e_m.strip().zfill(2)}-{e_d.strip().zfill(2)} {e_h.strip().zfill(2)}:{e_min.strip().zfill(2)}:{e_sec.strip().zfill(2)}"
                    
                    dt_s = pd.to_datetime(start_str)
                    dt_e = pd.to_datetime(end_str)
                    
                    if dt_s >= dt_e:
                        st.error("开始时间必须早于结束时间！")
                    else:
                        st.session_state.intervals.append({
                            "start": start_str,
                            "end": end_str,
                            "run_sec": run_sec,
                            "stop_sec": stop_sec if (run_sec != "0" and run_sec != "0.0") else "-"
                        })
                        st.success("添加成功！已自动为您衔接下一个时段的开始时间。")
                        st.rerun()
                except Exception as err:
                    st.error(f"时间格式错误或数值无效: {err}")

        # 显示已添加的时段列表
        if st.session_state.intervals:
            st.write("当前已添加的对比时段：")
            df_intervals = pd.DataFrame(st.session_state.intervals)
            st.dataframe(df_intervals, use_container_width=True)
            
            if st.button("🗑️ 清空所有时段"):
                st.session_state.intervals = []
                st.rerun()

        st.markdown("---")

        # --- 5. 生成图表按钮 ---
        if st.button("🚀 开始生成多时段对比趋势图", type="primary"):
            if not st.session_state.intervals:
                st.warning("请至少添加一个对比时间段！")
            else:
                with st.spinner("正在高速处理数据并绘图..."):
                    try:
                        df_all = df_all_raw.copy()
                        df_all = df_all.rename(columns=COLUMN_ALIASES)
                        
                        df_all[time_col] = pd.to_datetime(df_all[time_col].astype(str).str.strip(), format='mixed', errors='coerce')
                        df_all = df_all.dropna(subset=[time_col]).sort_values(time_col)
                        df_all = df_all[df_all[load_col] != 0].reset_index(drop=True)

                        if threshold is not None:
                            df_all = df_all[df_all[load_col] >= threshold].reset_index(drop=True)

                        fig, ax1 = plt.subplots(figsize=(14, 8))
                        ax2 = ax1.twinx()

                        color_palette = [
                            ("#85B2FF", "#1E3F66"),
                            ("#52C41A", "#135200"),
                            ("#FF7875", "#820014"),
                            ("#B37FEB", "#391085"),
                            ("#FF9C6E", "#873800"),
                            ("#36CBCB", "#00474F"),
                            ("#FF85C0", "#990033"),
                            ("#D3F261", "#5B8C00")
                        ]

                        has_valid_data = False
                        for idx, item in enumerate(st.session_state.intervals):
                            s_dt = pd.to_datetime(item['start'])
                            e_dt = pd.to_datetime(item['end'])
                            sub = df_all[(df_all[time_col] >= s_dt) & (df_all[time_col] <= e_dt)]
                            
                            if not sub.empty:
                                has_valid_data = True
                                bar_c, line_c = color_palette[idx % len(color_palette)]
                                run_s = item['run_sec']
                                stop_s = item['stop_sec']
                                label_desc = f"多频集速运行{run_s}s/停止{stop_s}s"
                                
                                act_s = sub[time_col].min().strftime('%Y-%m-%d %H:%M:%S')
                                act_e = sub[time_col].max().strftime('%Y-%m-%d %H:%M:%S')
                                
                                x_vals = range(len(sub))
                                y_load = sub[load_col]
                                y_press = sub[pressure_col]

                                ax1.fill_between(x_vals, y_load, color=bar_c, alpha=0.5, label=f"{label_desc} (实际 {act_s} ~ {act_e}) 负荷")
                                ax1.plot(x_vals, y_load, color=bar_c, linewidth=0.8, alpha=0.8)
                                ax2.plot(x_vals, y_press, color=line_c, linewidth=1.6, marker='o', markersize=2, label=f"{label_desc} (实际 {act_s} ~ {act_e}) 压差")

                        if not has_valid_data:
                            st.warning("在指定的时间段与阈值条件下未检索到有效数据！")
                        else:
                            ax1.set_xlabel("运行时间段", fontsize=12)
                            ax1.set_ylabel(f"负荷 ({load_col})", color='black', fontsize=12)
                            ax2.set_ylabel(f"压差 ({pressure_col})", color='black', fontsize=12)

                            ax2.grid(True, axis='y', color='white', linestyle='-', linewidth=0.8, alpha=0.8)
                            ax2.set_axisbelow(True)

                            if threshold is not None:
                                t_val = int(threshold) if threshold.is_integer() else threshold
                                plt.title(f"机组负荷/压差对比趋势图（最低负荷 ≥ {t_val}）", fontsize=14, pad=15)
                            else:
                                plt.title("机组负荷/压差对比趋势图", fontsize=14, pad=15)

                            lines_1, labels_1 = ax1.get_legend_handles_labels()
                            lines_2, labels_2 = ax2.get_legend_handles_labels()
                            ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper center', bbox_to_anchor=(0.5, -0.18), fontsize=9, ncol=2, framealpha=0.9)

                            fig.subplots_adjust(bottom=0.28)
                            
                            st.pyplot(fig)
                            st.success("图表生成成功！")

                    except Exception as err:
                        st.error(f"计算或绘图过程中发生错误: {err}")
else:
    st.info("请先在上方的文件上传框中选择并上传您的工业 CSV 或 Excel 文件。")
