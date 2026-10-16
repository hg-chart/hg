# -*- coding: utf-8 -*-
"""模块四：运行时间段方案管理"""
import os
import json
import logging
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import r2_storage

TEMPLATES_FILE_NAME = "templates_vault.json"
TRASH_FILE_NAME = "trash_vault.json"


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


def load_persistent_templates(vault_dir):
    templates_file = os.path.join(vault_dir, TEMPLATES_FILE_NAME)
    if os.path.exists(templates_file):
        try:
            with open(templates_file, "r", encoding="utf-8") as file:
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
            logging.exception("读取历史时段方案失败，将使用默认方案。")
    return default_templates()


def save_persistent_templates(templates, vault_dir):
    templates_file = os.path.join(vault_dir, TEMPLATES_FILE_NAME)
    try:
        with open(templates_file, "w", encoding="utf-8") as file:
            json.dump(templates, file, ensure_ascii=False, indent=4)
        if r2_storage._get_r2_client() is not None:
            r2_storage.r2_upload_file(templates_file)
        return True
    except Exception as exc:
        st.error(f"保存时段方案失败：{exc}")
        return False


def load_trash_bin(vault_dir):
    trash_file = os.path.join(vault_dir, TRASH_FILE_NAME)
    if os.path.exists(trash_file):
        try:
            with open(trash_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_trash_bin(trash, vault_dir):
    trash_file = os.path.join(vault_dir, TRASH_FILE_NAME)
    try:
        with open(trash_file, "w", encoding="utf-8") as file:
            json.dump(trash, file, ensure_ascii=False, indent=4)
        if r2_storage._get_r2_client() is not None:
            r2_storage.r2_upload_file(trash_file)
        return True
    except Exception:
        return False


def render_time_intervals_manager(vault_dir, df_raw, time_col):
    """渲染时间段方案选择、编辑、回收站及新增时段的完整交互逻辑"""
    if "saved_templates" not in st.session_state:
        st.session_state.saved_templates = load_persistent_templates(vault_dir)
    if "trash_bin" not in st.session_state:
        st.session_state.trash_bin = load_trash_bin(vault_dir)
    if "intervals" not in st.session_state:
        st.session_state.intervals = []

    st.markdown("### 4. 机组运行数据时间段选择 <span style='color:red; font-size:18px;'>（必选）</span>", unsafe_allow_html=True)

    template_options = {}
    for name, intervals_list in st.session_state.saved_templates.items():
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
                if st.button("确认选择", key=f"select_{actual_key}", use_container_width=True):
                    st.session_state.intervals = [
                        dict(item) for item in st.session_state.saved_templates[actual_key]
                    ]
                    st.session_state["current_scheme_name"] = opt_label
                    st.success(f"已成功加载：{actual_key}")
                    st.rerun()
            with sc3:
                if st.button("删除", key=f"delete_{actual_key}", use_container_width=True):
                    st.session_state.trash_bin[actual_key] = st.session_state.saved_templates[actual_key]
                    save_trash_bin(st.session_state.trash_bin, vault_dir)
                    del st.session_state.saved_templates[actual_key]
                    save_persistent_templates(st.session_state.saved_templates, vault_dir)
                    st.success(f"已将 {actual_key} 移入回收站。")
                    st.rerun()
    else:
        st.info("暂无可用的时间段方案。")

    if st.session_state.trash_bin:
        with st.expander("🗑️ 回收站（防止误删除）", expanded=False):
            st.write("以下是被删除的时间段方案，您可以选择恢复或彻底删除：")
            trash_options = list(st.session_state.trash_bin.keys())
            for trash_name in trash_options:
                trash_intervals = st.session_state.trash_bin[trash_name]
                first_s = trash_intervals[0].get("start", "") if trash_intervals else ""
                last_e = trash_intervals[-1].get("end", "") if trash_intervals else ""
                
                tc1, tc2, tc3 = st.columns([4, 1, 1])
                with tc1:
                    st.text(f"{trash_name} ({first_s} ~ {last_e})")
                with tc2:
                    if st.button("♻️ 恢复", key=f"restore_{trash_name}", use_container_width=True):
                        st.session_state.saved_templates[trash_name] = trash_intervals
                        save_persistent_templates(st.session_state.saved_templates, vault_dir)
                        del st.session_state.trash_bin[trash_name]
                        save_trash_bin(st.session_state.trash_bin, vault_dir)
                        st.success(f"已恢复方案：{trash_name}")
                        st.rerun()
                with tc3:
                    if st.button("🔥 彻底删除", key=f"perma_del_{trash_name}", use_container_width=True):
                        del st.session_state.trash_bin[trash_name]
                        save_trash_bin(st.session_state.trash_bin, vault_dir)
                        st.success(f"已彻底删除方案：{trash_name}")
                        st.rerun()

    st.markdown("---")

    if st.session_state.intervals:
        st.write("当前已选择的时间段（双击数值可以直接修改）。勾选“选择”后，可上移/下移或删除：")
        table_data = []
        for idx, item in enumerate(st.session_state.intervals):
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
            key="intervals_editor"
        )

        bcol1, bcol2, bcol3, bcol4, bcol5, bcol6 = st.columns(6)

        with bcol1:
            if st.button("💾 保存修改", use_container_width=True):
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
                    st.session_state.intervals = new_intervals
                    st.success("修改已成功保存！")
                    st.rerun()
                except Exception as ex:
                    st.error(f"保存失败，请检查时间格式是否正确: {ex}")

        with bcol2:
            if st.button("💾 另存为新方案", use_container_width=True):
                if not st.session_state.intervals:
                    st.warning("当前没有时段，无法保存。")
                else:
                    existing_nums = []
                    for k in st.session_state.saved_templates.keys():
                        if k.startswith("监测数据时间段"):
                            try:
                                num = int(k.replace("监测数据时间段", ""))
                                existing_nums.append(num)
                            except ValueError:
                                pass
                    next_num = max(existing_nums) + 1 if existing_nums else 1
                    new_name = f"监测数据时间段{next_num}"
                    
                    st.session_state.saved_templates[new_name] = [
                        dict(item) for item in st.session_state.intervals
                    ]
                    
                    f_date = st.session_state.intervals[0].get("start", "").split()[0]
                    l_date = st.session_state.intervals[-1].get("end", "").split()[0]
                    st.session_state["current_scheme_name"] = f"{new_name} ({f_date} ~ {l_date})"
                    
                    if save_persistent_templates(st.session_state.saved_templates, vault_dir):
                        st.success(f"已成功保存为“{new_name}”！")
                        st.rerun()

        with bcol3:
            if st.button("⬆️ 上移", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要上移的时段！")
                elif len(selected_indices) > 1:
                    st.warning("每次只能上移一个时段！")
                else:
                    idx = selected_indices[0]
                    if idx == 0:
                        st.info("已经是第一个时段，无法上移。")
                    else:
                        st.session_state.intervals[idx], st.session_state.intervals[idx - 1] = (
                            st.session_state.intervals[idx - 1],
                            st.session_state.intervals[idx],
                        )
                        st.rerun()

        with bcol4:
            if st.button("⬇️ 下移", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要下移的时段！")
                elif len(selected_indices) > 1:
                    st.warning("每次只能下移一个时段！")
                else:
                    idx = selected_indices[0]
                    if idx == len(st.session_state.intervals) - 1:
                        st.info("已经是最后一个时段，无法下移。")
                    else:
                        st.session_state.intervals[idx], st.session_state.intervals[idx + 1] = (
                            st.session_state.intervals[idx + 1],
                            st.session_state.intervals[idx],
                        )
                        st.rerun()

        with bcol5:
            if st.button("❌ 删除", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要删除的时段！")
                else:
                    for idx in sorted(selected_indices, reverse=True):
                        st.session_state.intervals.pop(idx)
                    if not st.session_state.intervals:
                        st.session_state.pop("plotted_fig_bytes", None)
                    st.success("已删除选中时段！")
                    st.rerun()

        with bcol6:
            if st.button("🗑️ 清空", use_container_width=True):
                st.session_state.intervals = []
                st.session_state.pop("plotted_fig_bytes", None)
                st.success("已清空所有时段！")
                st.rerun()

        st.markdown("---")

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

    with st.container(border=True):
        st.markdown("➕ **添加新时段**（自动智能衔接，支持秒级精准配置）")
        with st.form("interval_form"):
            st.markdown("📅 **开始时间**")
            sc1, sc2, sc3, sc4 = st.columns([2.8, 1, 1, 1])
            with sc1:
                start_date = st.date_input("日期", value=default_start.date(), key="s_date", label_visibility="collapsed")
            with sc2:
                start_hour = st.number_input("时", min_value=0, max_value=23, value=default_start.hour, key="s_h")
            with sc3:
                start_minute = st.number_input("分", min_value=0, max_value=59, value=default_start.minute, key="s_m")
            with sc4:
                start_second = st.number_input("秒", min_value=0, max_value=59, value=default_start.second, key="s_s")

            st.markdown("📅 **结束时间**")
            ec1, ec2, ec3, ec4 = st.columns([2.8, 1, 1, 1])
            with ec1:
                end_date = st.date_input("日期", value=default_end.date(), key="e_date", label_visibility="collapsed")
            with ec2:
                end_hour = st.number_input("时 ", min_value=0, max_value=23, value=default_end.hour, key="e_h")
            with ec3:
                end_minute = st.number_input("分 ", min_value=0, max_value=59, value=default_end.minute, key="e_m")
            with ec4:
                end_second = st.number_input("秒 ", min_value=0, max_value=59, value=default_end.second, key="e_s")

            run_col, stop_col, btn_col = st.columns([2, 2, 1.5])
            with run_col:
                run_seconds = st.text_input("多频集速运行秒数", value="30")
            with stop_col:
                stop_seconds = st.text_input("停止秒数（运行秒数若为0，此项不用填，系统自动设置为-）", value="780")
            with btn_col:
                st.write("")
                add_interval = st.form_submit_button("添加时段", use_container_width=True)

            if add_interval:
                try:
                    start_dt = datetime(
                        start_date.year, start_date.month, start_date.day,
                        int(start_hour), int(start_minute), int(start_second)
                    )
                    end_dt = datetime(
                        end_date.year, end_date.month, end_date.day,
                        int(end_hour), int(end_minute), int(end_second)
                    )

                    if start_dt >= end_dt:
                        st.error("开始时间必须早于结束时间！")
                    else:
                        start_string = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                        end_string = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                        run_text = run_seconds.strip() or "0"
                        stop_text = "-" if run_text in ("0", "0.0") else (stop_seconds.strip() or "-")
                        st.session_state.intervals.append({
                            "start": start_string,
                            "end": end_string,
                            "run_sec": run_text,
                            "stop_sec": stop_text,
                        })
                        st.success("时段添加成功！")
                        st.rerun()
                except Exception as exc:
                    st.error(f"时间格式错误：{exc}")

    st.markdown("---")
