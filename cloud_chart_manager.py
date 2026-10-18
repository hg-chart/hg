# -*- coding: utf-8 -*-
"""模块六：云端历史图表检索与回收站管理"""
import os
import shutil
import streamlit as st
import r2_storage


def render_cloud_chart_manager(chart_history_dir, chart_trash_dir):
    """渲染云端历史图表按三级（方案大类、右纵轴来源、历史趋势图标签）检索与调用界面"""
    st.markdown("---")
    st.subheader("☁️ 云端历史对比趋势图按来源与标签检索调用")

    # —— 工厂隔离：图表目录必须是当前工厂自己的；切换工厂时清空上一个工厂的选择 ——
    factory = st.session_state.get("selected_factory")
    if not factory:
        st.error("尚未选择工厂，已停止加载云端图表。")
        return
    if os.path.basename(os.path.normpath(chart_trash_dir)) != f"chart_trash_{factory}":
        st.error(f"图片回收站目录（{chart_trash_dir}）与当前工厂【{factory}】不一致，已停止，防止数据串厂。")
        return
    os.makedirs(chart_history_dir, exist_ok=True)
    os.makedirs(chart_trash_dir, exist_ok=True)
    if st.session_state.get("_ccm_scope") != factory:
        st.session_state["_ccm_scope"] = factory
        for _k in ("active_chart_key", "active_chart_name", "active_chart_scheme",
                   "active_chart_pressure", "active_chart_tag",
                   "sel_scheme", "sel_pressure", "sel_tag", "_active_chart_cache"):
            st.session_state.pop(_k, None)
    st.caption(f"当前工厂：{factory}（只显示该工厂自己的历史图表）")

    if r2_storage._get_r2_client() is not None:
        if st.button("🔄 刷新云端图片列表", key="refresh_chart_list"):
            r2_storage.invalidate_key_cache()
            st.session_state.pop("_active_chart_cache", None)
            st.rerun()
            
        all_keys = r2_storage.r2_list_keys()
        if all_keys:
            chart_keys = [k for k in all_keys if "chart_history/" in k and k.endswith(".png")]
            
            if chart_keys:
                # 嵌套字典结构：schemes_dict[scheme][pressure_source][filter_tag] = (filename, key)
                schemes_dict = {}
                for k in chart_keys:
                    parts = k.split("/")
                    if len(parts) >= 4:
                        scheme = parts[2]
                        filename = parts[3]
                        
                        if scheme not in schemes_dict:
                            schemes_dict[scheme] = {}
                        
                        # 解析文件名结构：[数据源列名]_[过滤变量名]_[过滤条件]_[时间戳].png
                        name_no_ext = filename.rsplit(".", 1)[0]
                        name_parts = name_no_ext.split("_")
                        
                        if len(name_parts) >= 3:
                            pressure_source = name_parts[0]
                            tag_sub_parts = name_parts[1:]
                            
                            if len(tag_sub_parts) >= 3 and tag_sub_parts[1].replace('.', '', 1).isdigit() and tag_sub_parts[2].replace('.', '', 1).isdigit():
                                load_tag = f"{tag_sub_parts[0]}_{tag_sub_parts[1]}_{tag_sub_parts[2]}"
                            elif len(tag_sub_parts) >= 3 and tag_sub_parts[1] == "上限":
                                load_tag = f"{tag_sub_parts[0]}_{tag_sub_parts[1]}_{tag_sub_parts[2]}"
                            elif len(tag_sub_parts) >= 2 and tag_sub_parts[1].replace('.', '', 1).isdigit():
                                load_tag = f"{tag_sub_parts[0]}_{tag_sub_parts[1]}"
                            elif len(tag_sub_parts) >= 2 and tag_sub_parts[1] == "全部":
                                load_tag = f"{tag_sub_parts[0]}_全部"
                            else:
                                load_tag = "_".join(tag_sub_parts[:2])
                        else:
                            pressure_source = "未知数据来源"
                            load_tag = name_no_ext

                        if pressure_source not in schemes_dict[scheme]:
                            schemes_dict[scheme][pressure_source] = {}
                        
                        schemes_dict[scheme][pressure_source][load_tag] = (filename, k)
                
                if schemes_dict:
                    # 第一级：选择时间段方案大类
                    selected_scheme = st.selectbox(
                        "📁 选择时间段方案大类", 
                        ["-- 请选择 --"] + list(schemes_dict.keys()), 
                        key="sel_scheme"
                    )
                    
                    # 第二级：选择右纵轴数据来源
                    available_pressures = ["-- 请选择 --"]
                    if selected_scheme and selected_scheme != "-- 请选择 --":
                        available_pressures += sorted(list(schemes_dict[selected_scheme].keys()))
                    
                    selected_pressure = st.selectbox(
                        "📈 选择右纵轴数据来源（压差列名）", 
                        available_pressures, 
                        key="sel_pressure"
                    )
                    
                    # 第三级：选择历史趋势图筛选（文案已固定写死）
                    available_tags = ["-- 请选择 --"]
                    if selected_scheme != "-- 请选择 --" and selected_pressure != "-- 请选择 --":
                        available_tags += sorted(list(schemes_dict[selected_scheme][selected_pressure].keys()))
                    
                    selected_tag = st.selectbox(
                        "🏷️ 选择历史趋势图", 
                        available_tags, 
                        key="sel_tag"
                    )
                    
                    if st.button("🔍 查看选中的图片", type="primary", key="btn_view_chart"):
                        if selected_scheme == "-- 请选择 --" or selected_pressure == "-- 请选择 --" or selected_tag == "-- 请选择 --":
                            st.warning("请完整选择“时间段方案大类”、“右纵轴数据来源”和“选择历史趋势图”。")
                        else:
                            pressure_data = schemes_dict.get(selected_scheme, {}).get(selected_pressure, {})
                            if selected_tag in pressure_data:
                                selected_file_name, target_key = pressure_data[selected_tag]
                                st.session_state["active_chart_key"] = target_key
                                st.session_state["active_chart_name"] = selected_file_name
                                st.session_state["active_chart_scheme"] = selected_scheme
                                st.session_state["active_chart_pressure"] = selected_pressure
                                st.session_state["active_chart_tag"] = selected_tag
                            else:
                                st.session_state.pop("active_chart_key", None)
                                st.info(f"在当前条件下暂未找到对应的历史图片。")

                    if "active_chart_key" in st.session_state:
                        target_key = st.session_state["active_chart_key"]
                        selected_file_name = st.session_state["active_chart_name"]
                        active_scheme = st.session_state.get("active_chart_scheme", "")
                        active_pressure = st.session_state.get("active_chart_pressure", "")
                        active_tag = st.session_state.get("active_chart_tag", "")
                        
                        client = r2_storage._get_r2_client()
                        try:
                            # 图片字节缓存在会话里，避免每次交互都重新从 R2 下载整张图
                            _cache = st.session_state.get("_active_chart_cache")
                            if _cache and _cache[0] == (factory, target_key):
                                img_bytes = _cache[1]
                            else:
                                resp = client.get_object(Bucket=r2_storage._r2_bucket(), Key=target_key)
                                img_bytes = resp["Body"].read()
                                st.session_state["_active_chart_cache"] = ((factory, target_key), img_bytes)
                            
                            st.markdown("---")
                            st.image(img_bytes, caption=f"云端图片：{active_scheme} ➔ {active_pressure} ➔ {active_tag}", use_container_width=True)
                            
                            act_c1, act_c2 = st.columns(2)
                            with act_c1:
                                st.download_button(
                                    label="⬇️ 下载调用的云端图片",
                                    data=img_bytes,
                                    file_name=selected_file_name,
                                    mime="image/png",
                                    key="dl_cloud_img"
                                )
                            with act_c2:
                                if st.button("🗑️ 将此图片移入回收站", key="btn_del_cloud_img"):
                                    trash_composite_name = f"{active_scheme}___{selected_file_name}"
                                    local_trash_path = os.path.join(chart_trash_dir, trash_composite_name)
                                    with open(local_trash_path, "wb") as tf:
                                        tf.write(img_bytes)
                                    
                                    r2_storage.r2_delete_key(target_key)
                                    st.session_state.pop("active_chart_key", None)
                                    st.session_state.pop("_active_chart_cache", None)
                                    st.success("图片已成功移入回收站，并从当前方案目录彻底清除！")
                                    st.rerun()
                        except Exception as e:
                            st.error(f"从云端加载图片失败：{e}")
                else:
                    st.info("未解析到有效的方案大类。")
            else:
                st.info("云端暂无保存的历史图片。")
        else:
            st.info("无法读取云端文件列表或存储桶为空。")

        # 图片回收站管理
        trashed_charts = sorted(
            name for name in os.listdir(chart_trash_dir)
            if name.lower().endswith(".png")
        )
        if trashed_charts:
            with st.expander("🗑️ 图片回收站（管理已删除的历史图片）", expanded=False):
                st.write("以下是被删除的历史图片，您可以选择恢复或彻底删除：")
                for t_img in trashed_charts:
                    if "___" not in t_img:
                        bad_path = os.path.join(chart_trash_dir, t_img)
                        if os.path.exists(bad_path):
                            os.remove(bad_path)
                        continue

                    orig_scheme, orig_filename = t_img.split("___", 1)
                    tc1, tc2, tc3 = st.columns([4, 1, 1])
                    with tc1:
                        st.text(f"🖼️ [{orig_scheme}] {orig_filename}")
                    with tc2:
                        if st.button("♻️ 恢复", key=f"restore_chart_{t_img}", use_container_width=True):
                            src_path = os.path.join(chart_trash_dir, t_img)
                            dest_path = os.path.join(chart_history_dir, orig_filename)
                            
                            if os.path.exists(src_path):
                                shutil.copy(src_path, dest_path)
                                r2_storage.r2_upload_file(dest_path, key=f"chart_history/{orig_scheme}/{orig_filename}")
                                os.remove(src_path)
                                if os.path.exists(dest_path):
                                    os.remove(dest_path)
                                    
                                st.success(f"已成功将图片恢复至原方案：“{orig_scheme}”！")
                                st.rerun()
                    with tc3:
                        if st.button("🔥 彻底删除", key=f"perma_del_chart_{t_img}", use_container_width=True):
                            src_path = os.path.join(chart_trash_dir, t_img)
                            if os.path.exists(src_path):
                                os.remove(src_path)
                            st.success(f"已彻底删除图片：{orig_filename}")
                            st.rerun()
    else:
        st.info("请先配置并连接 Cloudflare R2 存储桶以使用云端图片检索功能。")
