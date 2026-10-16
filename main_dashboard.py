# -*- coding: utf-8 -*-
"""设备运行数据多文件多时段汇总对比分析系统"""

import os
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager, ticker

# 导入 Cloudflare R2 专属模块
import r2_storage


def render_dashboard(selected_factory):
    # ============================================================
    # 0. 核心：根据传入的工厂动态隔离本地目录和 R2 前缀
    # ============================================================
    r2_storage.BASE_PREFIX = f"device-monitor/{selected_factory}/"

    VAULT_DIR = f"uploaded_vault_{selected_factory}"
    FILE_TRASH_DIR = f"file_trash_{selected_factory}"
    CHART_HISTORY_DIR = f"chart_history_{selected_factory}"
    CHART_TRASH_DIR = f"chart_trash_{selected_factory}"

    os.makedirs(VAULT_DIR, exist_ok=True)
    os.makedirs(FILE_TRASH_DIR, exist_ok=True)
    os.makedirs(CHART_HISTORY_DIR, exist_ok=True)
    os.makedirs(CHART_TRASH_DIR, exist_ok=True)

    # ============================================================
    # 1. 页面与中文字体
    # ============================================================
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

    COLUMN_ALIASES = {
        "压差": "W3.FW.AHTE10CP201F",
        "负荷": "W3.UNIT1.10DEHDCSAI03",
    }

    st.title(f"📊 设备运行数据分析系统 [{selected_factory}工作区]")
    st.markdown("---")

    # 初始化 R2 存储桶连接与数据同步
    if r2_storage._get_r2_client() is not None:
        sync_key = f"_r2_initial_sync_done_{selected_factory}"
        if not st.session_state.get(sync_key, False):
            with st.spinner(f"正在连接 Cloudflare R2 并同步 [{selected_factory}] 历史文件……"):
                r2_storage.sync_local_storage_with_r2(VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR)
            st.session_state[sync_key] = True
        st.caption(f"☁️ Cloudflare R2 存储桶：已连接（当前目录: {r2_storage.BASE_PREFIX}）")
    else:
        r2_err = r2_storage.get_r2_error()
        st.warning("Cloudflare R2 尚未连接，当前使用本地临时存储。" + (f" 提示：{r2_err}" if r2_err else ""))

    # ============================================================
    # 2. 文件库和历史时段方案（增加回收站支持）
    # ============================================================
    TEMPLATES_FILE = os.path.join(VAULT_DIR, "templates_vault.json")
    TRASH_FILE = os.path.join(VAULT_DIR, "trash_vault.json")

    def default_templates():
        return {
            "监测数据时间段1": [
                {"start": "2026-08-01 01:01:00", "end": "2026-08-05 01:01:50", "run_sec": "0", "stop_sec": "-"},
                {"start": "2026-09-19 01:01:50", "end": "2026-09-25 13:09:50", "run_sec": "0", "stop_sec": "-"},
                {"start": "2026-09-25 13:10:50", "end": "2026-09-29 13:09:50", "run_sec": "30", "stop_sec": "780"},
                {"start": "2026-10-04 13:09:50", "end": "2026-10-12 15:20:50", "run_sec": "30", "stop_sec": "780"},
                {"start": "2026-10-12 15:20:51", "end": "2026-10-14 15:20:50", "run_sec": "60", "stop_sec": "300"},
            ]
        }

    def load_persistent_templates():
        if os.path.exists(TEMPLATES_FILE):
            try:
                with open(TEMPLATES_FILE, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, dict):
                    normalized_data = {}
                    idx = 1
                    for k, v in data.items():
                        key_name = k if k.startswith("监测数据时间段") else f"监测数据时间段{idx}"
                        normalized_data[key_name] = v
                        idx += 1
                    return normalized_data
            except Exception:
                pass
        return default_templates()

    def save_persistent_templates(templates):
        try:
            with open(TEMPLATES_FILE, "w", encoding="utf-8") as file:
                json.dump(templates, file, ensure_ascii=False, indent=4)
            if r2_storage._get_r2_client() is not None:
                r2_storage.r2_upload_file(TEMPLATES_FILE)
            return True
        except Exception as exc:
            st.error(f"保存时段方案失败：{exc}")
            return False

    def load_trash_bin():
        if os.path.exists(TRASH_FILE):
            try:
                with open(TRASH_FILE, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def save_trash_bin(trash):
        try:
            with open(TRASH_FILE, "w", encoding="utf-8") as file:
                json.dump(trash, file, ensure_ascii=False, indent=4)
            if r2_storage._get_r2_client() is not None:
                r2_storage.r2_upload_file(TRASH_FILE)
            return True
        except Exception:
            return False

    session_templates_key = f"saved_templates_{selected_factory}"
    session_trash_key = f"trash_bin_{selected_factory}"
    session_intervals_key = f"intervals_{selected_factory}"

    if session_templates_key not in st.session_state:
        st.session_state[session_templates_key] = load_persistent_templates()
    if session_trash_key not in st.session_state:
        st.session_state[session_trash_key] = load_trash_bin()
    if session_intervals_key not in st.session_state:
        st.session_state[session_intervals_key] = []

    if f"plotted_fig_bytes_{selected_factory}" not in st.session_state:
        st.session_state[f"plotted_fig_bytes_{selected_factory}"] = None

    # ============================================================
    # 3. 上传及选择数据文件
    # ============================================================
    st.subheader(f"1. 表格文件管理 [{selected_factory}]（支持上传和调用历史文件）")

    uploaded_files = st.file_uploader(
        f"上传工业数据表格文件（CSV / XLSX / XLS） - {selected_factory}",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key=f"uploader_{selected_factory}"
    )

    if uploaded_files:
        for uploaded_file in uploaded_files:
            safe_name = Path(uploaded_file.name).name
            target = os.path.join(VAULT_DIR, safe_name)
            with open(target, "wb") as file:
                file.write(uploaded_file.getbuffer())
            if r2_storage._get_r2_client() is not None:
                r2_storage.r2_upload_file(target)
        st.success("文件已成功保存到当前工厂文件库并同步至 Cloudflare R2。")

    existing_files = sorted(
        name for name in os.listdir(VAULT_DIR)
        if name.lower().endswith((".csv", ".xlsx", ".xls"))
    )

    active_paths = []
    if existing_files:
        with st.expander("📁 选择需要分析的文件", expanded=True):
            st.write("请在下方勾选本次分析所需的文件：")

            sel_dict_key = f"file_selections_{selected_factory}"
            if sel_dict_key not in st.session_state:
                st.session_state[sel_dict_key] = {}

            for name in existing_files:
                if name not in st.session_state[sel_dict_key]:
                    st.session_state[sel_dict_key][name] = True

            selected_files = []
            for name in existing_files:
                fc1, fc2 = st.columns([0.1, 0.9])
                with fc1:
                    is_sel = st.checkbox(
                        "选择", 
                        value=st.session_state[sel_dict_key].get(name, True), 
                        key=f"file_chk_{selected_factory}_{name}", 
                        label_visibility="collapsed"
                    )
                    st.session_state[sel_dict_key][name] = is_sel
                    if is_sel:
                        selected_files.append(name)
                with fc2:
                    st.text(f"📄 {name}")

            active_paths = [os.path.join(VAULT_DIR, name) for name in selected_files]

        st.success(f"当前已选择 {len(active_paths)} 个文件参与分析。")

    # ============================================================
    # 4. 文件删除与回收站管理
    # ============================================================
    with st.expander("🗑️ 文件删除与回收站管理（如需清理历史文件请展开）", expanded=False):
        st.write("勾选不需要的文件进行批量删除，删除后的文件可随时在下方回收站恢复：")
        
        if existing_files:
            del_dict_key = f"file_del_selections_{selected_factory}"
            if del_dict_key not in st.session_state:
                st.session_state[del_dict_key] = {}
                
            for name in existing_files:
                if name not in st.session_state[del_dict_key]:
                    st.session_state[del_dict_key][name] = False
                    
            for name in existing_files:
                dc1, dc2 = st.columns([0.1, 0.9])
                with dc1:
                    d_sel = st.checkbox("删除选择", value=st.session_state[del_dict_key].get(name, False), key=f"file_del_chk_{selected_factory}_{name}", label_visibility="collapsed")
                    st.session_state[del_dict_key][name] = d_sel
                with dc2:
                    st.text(f"📄 {name}")

            if st.button("🗑️ 批量删除选中的文件", key=f"btn_del_files_{selected_factory}"):
                deleted_any = False
                for name, is_sel in list(st.session_state[del_dict_key].items()):
                    if is_sel:
                        src_path = os.path.join(VAULT_DIR, name)
                        dst_path = os.path.join(FILE_TRASH_DIR, name)
                        if os.path.exists(src_path):
                            shutil.move(src_path, dst_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_upload_file(dst_path)
                                r2_storage.r2_delete_key(src_path.replace("\\", "/"))
                            st.session_state[del_dict_key][name] = False
                            deleted_any = True
                if deleted_any:
                    st.success("已将选中的文件移入回收站！")
                    st.rerun()
                else:
                    st.warning("请先勾选需要删除的文件。")
        else:
            st.info("当前文件库中暂无文件。")

        trashed_files = sorted(
            name for name in os.listdir(FILE_TRASH_DIR)
            if name.lower().endswith((".csv", ".xlsx", ".xls"))
        )

        if trashed_files:
            st.markdown("---")
            st.markdown("♻️ **文件回收站**")
            for trash_name in trashed_files:
                tc1, tc2, tc3 = st.columns([4, 1, 1])
                with tc1:
                    st.text(f"📄 {trash_name}")
                with tc2:
                    if st.button("♻️ 恢复", key=f"restore_file_{selected_factory}_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(FILE_TRASH_DIR, trash_name)
                        dst_v_path = os.path.join(VAULT_DIR, trash_name)
                        if os.path.exists(src_t_path):
                            shutil.move(src_t_path, dst_v_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_upload_file(dst_v_path)
                                r2_storage.r2_delete_key(src_t_path.replace("\\", "/"))
                            st.session_state[sel_dict_key][trash_name] = True
                            st.success(f"已成功恢复文件：{trash_name}")
                            st.rerun()
                with tc3:
                    if st.button("🔥 彻底删除", key=f"perma_del_file_{selected_factory}_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(FILE_TRASH_DIR, trash_name)
                        if os.path.exists(src_t_path):
                            os.remove(src_t_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_delete_key(src_t_path.replace("\\", "/"))
                            st.success(f"已彻底删除文件：{trash_name}")
                            st.rerun()

    if not active_paths:
        st.info("请先上传或选择 CSV、Excel 数据文件。")
        return

    # ============================================================
    # 5. 读取 CSV / Excel
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
                    raise ValueError(f"无法读取 CSV 文件 {Path(file_path).name}。")
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
        return

    if not columns:
        st.error("所选文件没有可用的数据列。")
        return

    # ============================================================
    # 6. 数据列和负荷过滤
    # ============================================================
    st.subheader("2. 数据列选择配置")
    col1, col2, col3 = st.columns(3)

    default_load_index = min(1, len(columns) - 1)
    if "W3.UNIT1.10DEHDCSAI03" in columns:
        default_load_index = columns.index("W3.UNIT1.10DEHDCSAI03")

    with col1:
        time_col = st.selectbox("横坐标轴（时间列）请选择数据来源", columns, index=0, key=f"t_col_{selected_factory}")
    with col2:
        load_col = st.selectbox("左纵轴（机组负荷）请选择数据来源", columns, index=default_load_index, key=f"l_col_{selected_factory}")
    with col3:
        pressure_col = st.selectbox("右纵轴（压差）请选择数据来源", columns, index=min(2, len(columns) - 1), key=f"p_col_{selected_factory}")

    st.subheader("3. 负荷过滤配置（可选）")
    threshold_text = st.text_input("负荷下限阈值（留空则使用全部负荷数据）", value="", key=f"thresh_{selected_factory}")
    threshold = None
    threshold_valid = True

    if threshold_text.strip():
        try:
            threshold = float(threshold_text.strip())
        except ValueError:
            threshold_valid = False
            st.error("负荷下限必须是数字，例如 240。")

    # ============================================================
    # 7. 机组运行数据时间段选择
    # ============================================================
    st.markdown(f"### 4. 机组运行数据时间段选择 <span style='color:red; font-size:18px;'>（必选）</span>", unsafe_allow_html=True)

    template_options = {}
    saved_templates = st.session_state[session_templates_key]
    trash_bin = st.session_state[session_trash_key]
    intervals = st.session_state[session_intervals_key]

    for name, intervals_list in saved_templates.items():
        if intervals_list and isinstance(intervals_list, list):
            try:
                first_start_date = str(intervals_list[0].get("start", "")).split()[0]
                last_end_date = str(intervals_list[-1].get("end", "")).split()[0]
                label = f"{name} ({first_start_date} ~ {last_end_date})"
            except Exception:
                label = f"{name} (时段解析异常)"
        else:
            label = f"{name} (无有效时段)"
        template_options[label] = name

    if template_options:
        options_list = list(template_options.keys())
        for opt_label in options_list:
            actual_key = template_options[opt_label]
            sc1, sc2, sc3 = st.columns([5, 1, 1])
            with sc1:
                st.markdown(f"📌 **{opt_label}**")
            with sc2:
                if st.button("确认选择", key=f"select_{selected_factory}_{actual_key}", use_container_width=True):
                    st.session_state[session_intervals_key] = [
                        dict(item) for item in saved_templates[actual_key]
                    ]
                    st.session_state[f"current_scheme_name_{selected_factory}"] = opt_label
                    st.success(f"已成功加载：{actual_key}")
                    st.rerun()
            with sc3:
                if st.button("删除", key=f"delete_{selected_factory}_{actual_key}", use_container_width=True):
                    trash_bin[actual_key] = saved_templates[actual_key]
                    save_trash_bin(trash_bin)
                    del saved_templates[actual_key]
                    save_persistent_templates(saved_templates)
                    st.success(f"已将 {actual_key} 移入回收站。")
                    st.rerun()
    else:
        st.info("暂无可用的时间段方案。")

    st.markdown("---")

    if intervals:
        st.write("当前已选择的时间段：")
        table_data = []
        for idx, item in enumerate(intervals):
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
            key=f"intervals_editor_{selected_factory}"
        )

        bcol1, bcol2, bcol3, bcol4, bcol5, bcol6 = st.columns(6)
        with bcol1:
            if st.button("💾 保存修改", key=f"s_mod_{selected_factory}", use_container_width=True):
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
                    st.session_state[session_intervals_key] = new_intervals
                    st.success("修改已成功保存！")
                    st.rerun()
                except Exception as ex:
                    st.error(f"保存失败: {ex}")

        with bcol2:
            if st.button("💾 另存为新方案", key=f"s_new_{selected_factory}", use_container_width=True):
                if not intervals:
                    st.warning("当前没有时段。")
                else:
                    existing_nums = []
                    for k in saved_templates.keys():
                        if k.startswith("监测数据时间段"):
                            try:
                                num = int(k.replace("监测数据时间段", ""))
                                existing_nums.append(num)
                            except ValueError:
                                pass
                    next_num = max(existing_nums) + 1 if existing_nums else 1
                    new_name = f"监测数据时间段{next_num}"
                    saved_templates[new_name] = [dict(item) for item in intervals]
                    if save_persistent_templates(saved_templates):
                        st.success(f"已成功保存为“{new_name}”！")
                        st.rerun()

        with bcol5:
            if st.button("❌ 删除", key=f"s_del_{selected_factory}", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要删除的时段！")
                else:
                    for idx in sorted(selected_indices, reverse=True):
                        intervals.pop(idx)
                    st.success("已删除选中时段！")
                    st.rerun()

        with bcol6:
            if st.button("🗑️ 清空", key=f"s_clr_{selected_factory}", use_container_width=True):
                st.session_state[session_intervals_key] = []
                st.success("已清空所有时段！")
                st.rerun()

        st.markdown("---")

    # 默认时间计算
    default_start = datetime.now()
    if intervals:
        try:
            default_start = pd.to_datetime(intervals[-1]["end"]).to_pydatetime()
        except Exception:
            pass

    default_end = default_start + timedelta(minutes=50)

    with st.container(border=True):
        st.markdown("➕ **添加新时段**")
        with st.form(f"interval_form_{selected_factory}"):
            sc1, sc2, sc3, sc4 = st.columns([2.8, 1, 1, 1])
            with sc1:
                start_date = st.date_input("开始日期", value=default_start.date(), key=f"s_d_{selected_factory}")
            with sc2:
                start_hour = st.number_input("时", min_value=0, max_value=23, value=default_start.hour, key=f"s_h_{selected_factory}")
            with sc3:
                start_minute = st.number_input("分", min_value=0, max_value=59, value=default_start.minute, key=f"s_min_{selected_factory}")
            with sc4:
                start_second = st.number_input("秒", min_value=0, max_value=59, value=default_start.second, key=f"s_sec_{selected_factory}")

            ec1, ec2, ec3, ec4 = st.columns([2.8, 1, 1, 1])
            with ec1:
                end_date = st.date_input("结束日期", value=default_end.date(), key=f"e_d_{selected_factory}")
            with ec2:
                end_hour = st.number_input("时", min_value=0, max_value=23, value=default_end.hour, key=f"e_h_{selected_factory}")
            with ec3:
                end_minute = st.number_input("分", min_value=0, max_value=59, value=default_end.minute, key=f"e_min_{selected_factory}")
            with ec4:
                end_second = st.number_input("秒", min_value=0, max_value=59, value=default_end.second, key=f"e_sec_{selected_factory}")

            run_col, stop_col, btn_col = st.columns([2, 2, 1.5])
            with run_col:
                run_seconds = st.text_input("多频集速运行秒数", value="30", key=f"run_s_{selected_factory}")
            with stop_col:
                stop_seconds = st.text_input("停止秒数", value="780", key=f"stop_s_{selected_factory}")
            with btn_col:
                st.write("")
                add_interval = st.form_submit_button("添加时段", use_container_width=True)

            if add_interval:
                try:
                    start_dt = datetime(start_date.year, start_date.month, start_date.day, int(start_hour), int(start_minute), int(start_second))
                    end_dt = datetime(end_date.year, end_date.month, end_date.day, int(end_hour), int(end_minute), int(end_second))
                    if start_dt >= end_dt:
                        st.error("开始时间必须早于结束时间！")
                    else:
                        intervals.append({
                            "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "run_sec": run_seconds.strip() or "0",
                            "stop_sec": stop_seconds.strip() or "-",
                        })
                        st.success("时段添加成功！")
                        st.rerun()
                except Exception as exc:
                    st.error(f"格式错误：{exc}")

    st.markdown("---")

    # ============================================================
    # 8. 生成多时段趋势图
    # ============================================================
    if st.button("🚀 开始生成多时段对比趋势图", type="primary", key=f"btn_plot_{selected_factory}"):
        if not threshold_valid:
            st.error("请先把负荷下限阈值修改为有效数字。")
        elif not intervals:
            st.warning("请至少添加一个对比时间段！")
        else:
            with st.spinner("正在处理多时段数据并绘图……"):
                try:
                    df = df_raw.copy()
                    df = df.rename(columns=COLUMN_ALIASES)
                    actual_time_col = COLUMN_ALIASES.get(time_col, time_col)
                    actual_load_col = COLUMN_ALIASES.get(load_col, load_col)
                    actual_pressure_col = COLUMN_ALIASES.get(pressure_col, pressure_col)

                    df[actual_time_col] = pd.to_datetime(df[actual_time_col].astype(str).str.strip(), format="mixed", errors="coerce")
                    df[actual_load_col] = pd.to_numeric(df[actual_load_col], errors="coerce")
                    df[actual_pressure_col] = pd.to_numeric(df[actual_pressure_col], errors="coerce")
                    df = df.dropna(subset=[actual_time_col, actual_load_col]).sort_values(actual_time_col).reset_index(drop=True)
                    df = df[df[actual_load_col] != 0].copy()

                    if threshold is not None:
                        df = df[df[actual_load_col] >= threshold].copy()

                    fig, ax1 = plt.subplots(figsize=(16, 8))
                    ax2 = ax1.twinx()

                    for index, interval in enumerate(intervals):
                        start_dt = pd.to_datetime(interval["start"])
                        end_dt = pd.to_datetime(interval["end"])
                        part = df[(df[actual_time_col] >= start_dt) & (df[actual_time_col] <= end_dt)].copy()
                        if part.empty:
                            continue
                        ax1.plot(part[actual_time_col], part[actual_load_col], label=f"时段 {index+1} 负荷")
                        ax2.plot(part[actual_time_col], part[actual_pressure_col], linestyle="--", label=f"时段 {index+1} 压差")

                    plt.title(f"机组负荷/压差对比趋势图 [{selected_factory}]", fontsize=14, pad=20)
                    ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)
                    fig.tight_layout()

                    import io
                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", dpi=300, bbox_inches="tight")
                    buf.seek(0)
                    st.session_state[f"plotted_fig_bytes_{selected_factory}"] = buf.getvalue()
                    plt.close(fig)
                    st.success("多时段对比趋势图生成成功！")
                except Exception as e:
                    st.error(f"绘图出错：{e}")

    # ============================================================
    # 9. 渲染与下载
    # ============================================================
    fig_bytes = st.session_state.get(f"plotted_fig_bytes_{selected_factory}")
    if fig_bytes:
        st.markdown("---")
        st.subheader("📊 生成的对比趋势图预览")
        st.image(fig_bytes, use_container_width=True)
        st.download_button(
            label="⬇️ 下载趋势图 PNG",
            data=fig_bytes,
            file_name=f"{selected_factory}_comparison.png",
            mime="image/png",
            key=f"dl_btn_{selected_factory}",
            type="primary",
            use_container_width=True
        )
