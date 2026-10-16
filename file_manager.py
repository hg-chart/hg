# -*- coding: utf-8 -*-
"""模块二：表格文件管理与回收站"""
import os
import shutil
from pathlib import Path
import streamlit as st
import r2_storage


def render_file_manager(vault_dir, file_trash_dir):
    """渲染文件上传、选择及回收站管理界面，返回当前选中的文件路径列表"""
    st.subheader("1. 表格文件管理（支持上传和调用历史文件）")

    uploaded_files = st.file_uploader(
        "上传工业数据表格文件（CSV / XLSX / XLS）",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        for uploaded_file in uploaded_files:
            safe_name = Path(uploaded_file.name).name
            target = os.path.join(vault_dir, safe_name)
            with open(target, "wb") as file:
                file.write(uploaded_file.getbuffer())
            if r2_storage._get_r2_client() is not None:
                r2_storage.r2_upload_file(target)
        st.success("文件已成功保存到当前运行环境的文件库并同步至 Cloudflare R2。")

    existing_files = sorted(
        name for name in os.listdir(vault_dir)
        if name.lower().endswith((".csv", ".xlsx", ".xls"))
    )

    active_paths = []
    if existing_files:
        with st.expander("📁 选择需要分析的文件", expanded=True):
            st.write("请在下方勾选本次分析所需的文件：")

            if "file_selections" not in st.session_state:
                st.session_state.file_selections = {}

            for name in existing_files:
                if name not in st.session_state.file_selections:
                    st.session_state.file_selections[name] = True

            selected_files = []
            for name in existing_files:
                fc1, fc2 = st.columns([0.1, 0.9])
                with fc1:
                    is_sel = st.checkbox(
                        "选择", 
                        value=st.session_state.file_selections.get(name, True), 
                        key=f"file_chk_{name}", 
                        label_visibility="collapsed"
                    )
                    st.session_state.file_selections[name] = is_sel
                    if is_sel:
                        selected_files.append(name)
                with fc2:
                    st.text(f"📄 {name}")

            active_paths = [os.path.join(vault_dir, name) for name in selected_files]

        st.success(f"当前已选择 {len(active_paths)} 个文件参与分析。")

    # 文件删除与回收站管理
    with st.expander("🗑️ 文件删除与回收站管理（如需清理历史文件请展开）", expanded=False):
        st.write("勾选不需要的文件进行批量删除，删除后的文件可随时在下方回收站恢复：")
        
        if existing_files:
            if "file_del_selections" not in st.session_state:
                st.session_state.file_del_selections = {}
                
            for name in existing_files:
                if name not in st.session_state.file_del_selections:
                    st.session_state.file_del_selections[name] = False
                    
            for name in existing_files:
                dc1, dc2 = st.columns([0.1, 0.9])
                with dc1:
                    d_sel = st.checkbox(
                        "删除选择", 
                        value=st.session_state.file_del_selections.get(name, False), 
                        key=f"file_del_chk_{name}", 
                        label_visibility="collapsed"
                    )
                    st.session_state.file_del_selections[name] = d_sel
                with dc2:
                    st.text(f"📄 {name}")

            if st.button("🗑️ 批量删除选中的文件"):
                deleted_any = False
                for name, is_sel in list(st.session_state.file_del_selections.items()):
                    if is_sel:
                        src_path = os.path.join(vault_dir, name)
                        dst_path = os.path.join(file_trash_dir, name)
                        if os.path.exists(src_path):
                            shutil.move(src_path, dst_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_upload_file(dst_path)
                                r2_storage.r2_delete_key(src_path.replace("\\", "/"))
                            st.session_state.file_del_selections[name] = False
                            deleted_any = True
                if deleted_any:
                    st.success("已将选中的文件移入回收站！")
                    st.rerun()
                else:
                    st.warning("请先勾选需要删除的文件。")
        else:
            st.info("当前文件库中暂无文件。")

        trashed_files = sorted(
            name for name in os.listdir(file_trash_dir)
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
                    if st.button("♻️ 恢复", key=f"restore_file_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(file_trash_dir, trash_name)
                        dst_v_path = os.path.join(vault_dir, trash_name)
                        if os.path.exists(src_t_path):
                            shutil.move(src_t_path, dst_v_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_upload_file(dst_v_path)
                                r2_storage.r2_delete_key(src_t_path.replace("\\", "/"))
                            st.session_state.file_selections[trash_name] = True
                            st.success(f"已成功恢复文件：{trash_name}")
                            st.rerun()
                with tc3:
                    if st.button("🔥 彻底删除", key=f"perma_del_file_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(file_trash_dir, trash_name)
                        if os.path.exists(src_t_path):
                            os.remove(src_t_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_delete_key(src_t_path.replace("\\", "/"))
                            st.success(f"已彻底删除文件：{trash_name}")
                            st.rerun()

    return active_paths
