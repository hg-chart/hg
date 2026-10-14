# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import datetime, timedelta

# 设置网页布局
st.set_page_config(page_title="设备运行数据多文件多时段汇总对比分析系统", layout="wide")

# 【系统级字体绑定】文泉驿正黑
plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

COLUMN_ALIASES = {
    "压差": "W3.FW.AHTE10CP201F",
    "负荷": "W3.UNIT1.10DEHDCSAI03",
}

st.title("📊 设备运行数据多文件多时段汇总对比分析系统")
st.markdown("---")

# 初始化全局历史方案与历史文件库
if 'saved_templates' not in st.session_state:
    st.session_state.saved_templates = {
        "默认测试方案 (5个时段示例)": [
            {"start": "2026-08-01 01:01:00", "end": "2026-08-05 01:01:50", "run_sec": "0", "stop_sec": "-"},
            {"start": "2026-09-19 01:01:50", "end": "2026-09-25 13:09:50", "run_sec": "0", "stop_sec": "-"},
            {"start": "2026-09-25 13:10:50", "end": "2026-09-29 13:09:50", "run_sec": "30", "stop_sec": "780"},
            {"start": "2026-10-4 13:09:50", "end": "2026-10-12 15:20:50", "run_sec": "30", "stop_sec": "780"},
            {"start": "2026-10-12 15:20:51", "end": "2026-10-14 15:20:50", "run_sec": "60", "stop_sec": "300"}
        ]
    }

if 'history_files' not in st.session_state:
    st.session_state.history_files = {} # 格式: {filename: file_bytes}

# --- 1. 文件上传与历史文件库管理 ---
st.subheader("1. 表格文件管理（支持新上传与历史文件快捷调用）")

uploaded_files = st.file_uploader("上传新的工业数据表格文件 (CSV / XLSX)", type=["csv", "xlsx", "xls"], accept_multiple_files=True)

if uploaded_files:
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        file_name = uploaded_file.name
        # 存入历史文件库
        st.session_state.history_files[file_name] = file_bytes
        # 同时写到本地供读取
        with open(file_name, "wb") as f:
            f.write(file_bytes)

# 如果历史文件库中有文件，提供多选快捷加载框
active_file_paths = []
if st.session_state.history_files:
    with st.expander("📁 历史上传文件库（免重复上传，随时勾选调用）", expanded=True):
        all_hist_names = list(st.session_state.history_files.keys())
        selected_hist_names = st.multiselect("勾选需要参与本次分析的历史文件", all_hist_names, default=all_hist_names)
        
        # 将勾选的历史文件写回运行目录
        for fname in selected_hist_names:
            with open(fname, "wb") as f:
                f.write(st.session_state.history_files[fname])
            active_file_paths.append(fname)
        
        if st.button("🗑️ 清空历史文件库"):
            st.session_state.history_files = {}
            st.rerun()
else:
    if uploaded_files:
        active_file_paths = [f.name for f in uploaded_files]

if active_file_paths:
    st.success(f"当前已加载 {len(active_file_paths)} 个文件参与分析。")

    try:
        dfs_list = []
        for f_path in active_file_paths:
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

        # --- 4. 多时段对比配置（含历史方案存取功能） ---
        st.subheader("4. 多时段对比配置（历史方案保存与调用）")
        
        if 'intervals' not in st.session_state:
            st.session_state.intervals = []

        with st.expander("📁 历史时段方案管理（保存与一键加载）", expanded=False):
            template_names = list(st.session_state.saved_templates.keys())
            col_t1, col_t2 = st.columns([2, 1])
            with col_t1:
                selected_template = st.selectbox("选择已保存的历史方案", template_names)
                if st.button("📥 一键加载该历史方案"):
                    st.session_state.intervals = [dict(item) for item in st.session_state.saved_templates[selected_template]]
                    st.success(f"成功加载历史方案：【{selected_template}】！")
                    st.rerun()
            with col_t2:
                new_template_name = st.text_input("给当前时段起个名字", value="我的常用方案")
                if st.button("💾 保存当前时段为历史方案"):
                    if not st.session_state.intervals:
                        st.warning("当前还没有添加任何时段，无法保存！")
                    else:
                        st.session_state.saved_templates[new_template_name] = [dict(item) for item in st.session_state.intervals]
                        st.success(f"方案【{new_template_name}】保存成功！")
                        st.rerun()

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
            st.markdown("🕒 **开始时间设置 (自动衔接)**")
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
                with st.spinner("正在高速处理多时段数据并绘图..."):
                    try:
                        df_all = df_all_raw.copy()
                        df_all = df_all.rename(columns=COLUMN_ALIASES)
                        
                        df_all[time_col] = pd.to_datetime(df_all[time_col].astype(str).str.strip(), format='mixed', errors='coerce')
                        df_all = df_all.dropna(subset=[time_col]).sort_values(time_col)
                        df_all = df_all[df_all[load_col] != 0].reset_index(drop=True)

                        if threshold is not None:
                            df_all = df_all[df_all[load_col] >= threshold].reset_index(drop=True)

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

                        processed_dfs = []
                        debug_info = []

                        for idx, item in enumerate(st.session_state.intervals):
                            s_dt = pd.to_datetime(item['start'])
                            e_dt = pd.to_datetime(item['end'])
                            sub = df_all[(df_all[time_col] >= s_dt) & (df_all[time_col] <= e_dt)].copy()
                            
                            debug_info.append(f"时段 {idx+1}: 匹配到 {len(sub)} 行")

                            if not sub.empty:
                                sub_res = sub.sort_values(time_col).reset_index(drop=True)
                                bar_c, line_c = color_palette[idx % len(color_palette)]
                                act_s = sub_res[time_col].min().strftime('%Y-%m-%d %H:%M:%S')
                                act_e = sub_res[time_col].max().strftime('%Y-%m-%d %H:%M:%S')
                                
                                run_s = item['run_sec']
                                stop_s = item['stop_sec']
                                label_desc = f"多频集速运行{run_s}s/停止{stop_s}s"
                                
                                sub_res['period_name'] = f"{idx}_{label_desc} (实际 {act_s} ~ {act_e})"
                                sub_res['bar_color'] = bar_c
                                sub_res['line_color'] = line_c
                                processed_dfs.append(sub_res)

                        st.info("🔍 各时段数据检索诊断：" + " | ".join(debug_info))

                        if not processed_dfs:
                            st.warning("在指定的所有时间段与阈值条件下均未检索到有效数据！")
                        else:
                            df_final = pd.concat(processed_dfs).reset_index(drop=True)
                            
                            x_indices = range(len(df_final))
                            time_labels = df_final[time_col].dt.strftime('%m-%d %H:%M:%S').tolist()

                            fig, ax1 = plt.subplots(figsize=(14, 8))
                            ax2 = ax1.twinx()

                            for name in df_final['period_name'].unique():
                                mask = df_final['period_name'] == name
                                subset_x = [x for x, m in zip(x_indices, mask) if m]
                                bar_c = df_final[mask]['bar_color'].iloc[0]
                                line_c = df_final[mask]['line_color'].iloc[0]
                                display_label = name.split('_', 1)[1]

                                y_vals = df_final[mask][load_col]
                                ax1.fill_between(subset_x, y_vals, color=bar_c, alpha=0.5, label=f"{display_label} 负荷")
                                ax1.plot(subset_x, y_vals, color=bar_c, linewidth=0.8, alpha=0.8)
                                ax2.plot(subset_x, df_final[mask][pressure_col], color=line_c, linewidth=1.6, marker='o', markersize=2, label=f"{display_label} 压差")

                            ax1.set_xlabel("运行时间段", fontsize=12)
                            ax1.set_ylabel(f"负荷 ({load_col})", color='black', fontsize=12)
                            ax2.set_ylabel(f"压差 ({pressure_col})", color='black', fontsize=12)

                            ax2.grid(True, axis='y', color='white', linestyle='-', linewidth=0.8, alpha=0.8)
                            ax2.set_axisbelow(True)

                            step = max(1, len(x_indices) // 10)
                            ax1.set_xticks(list(x_indices)[::step])
                            ax1.set_xticklabels([time_labels[i] for i in range(0, len(time_labels), step)], rotation=30)

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
