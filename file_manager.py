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

    # —— 工厂隔离：文件库目录必须就是“当前工厂”自己的目录 ——
    factory = st.session_state.get("selected_factory")
    if not factory:
        st.error("尚未选择工厂，已停止加载文件库（防止不同工厂的数据混用）。")
        st.stop()
    if os.path.basename(os.path.normpath(vault_dir)) != f"uploaded_vault_{factory}":
        st.error(f"文件库目录（{vault_dir}）与当前工厂【{factory}】不一致，已停止，防止数据串厂。")
        st.stop()
    os.makedirs(vault_dir, exist_ok=True)
    os.makedirs(file_trash_dir, exist_ok=True)

    # 切换工厂时，清空上一个工厂留下的勾选状态
    if st.session_state.get("_fm_scope") != factory:
        st.session_state["_fm_scope"] = factory
        for _k in ("file_selections", "file_del_selections", "trash_del_selections"):
            st.session_state[_k] = {}

    uploaded_files = st.file_uploader(
        "上传工业数据表格文件（CSV / XLSX / XLS）",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        upload_failed = []
        for uploaded_file in uploaded_files:
            safe_name = Path(uploaded_file.name).name
            target = os.path.join(vault_dir, safe_name)
            with open(target, "wb") as file:
                file.write(uploaded_file.getbuffer())
            if r2_storage._get_r2_client() is not None:
                if not r2_storage.r2_upload_file(target, key=r2_storage.vault_key(safe_name)):
                    upload_failed.append(safe_name)
        if upload_failed:
            st.warning("以下文件已保存到本地，但同步到 Cloudflare R2 失败：" + "、".join(upload_failed))
        else:
            st.success(f"文件已成功保存到工厂【{factory}】的文件库并同步至 Cloudflare R2。")

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
                        key=f"file_chk_{factory}_{name}", 
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
                        key=f"file_del_chk_{factory}_{name}", 
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
                                r2_storage.r2_upload_file(dst_path, key=r2_storage.trash_key(name))
                                r2_storage.r2_delete_files_by_name(name, trash=False)
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

            if "trash_del_selections" not in st.session_state:
                st.session_state.trash_del_selections = {}

            for trash_name in trashed_files:
                if trash_name not in st.session_state.trash_del_selections:
                    st.session_state.trash_del_selections[trash_name] = False

            # 渲染回收站文件列表及复选框
            for trash_name in trashed_files:
                tc1, tc2, tc3, tc4 = st.columns([0.1, 3.8, 1, 1])
                with tc1:
                    t_sel = st.checkbox(
                        "回收站选择",
                        value=st.session_state.trash_del_selections.get(trash_name, False),
                        key=f"trash_chk_{factory}_{trash_name}",
                        label_visibility="collapsed"
                    )
                    st.session_state.trash_del_selections[trash_name] = t_sel
                with tc2:
                    st.text(f"📄 {trash_name}")
                with tc3:
                    if st.button("♻️ 恢复", key=f"restore_file_{factory}_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(file_trash_dir, trash_name)
                        dst_v_path = os.path.join(vault_dir, trash_name)
                        if os.path.exists(src_t_path):
                            shutil.move(src_t_path, dst_v_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_upload_file(dst_v_path, key=r2_storage.vault_key(trash_name))
                                r2_storage.r2_delete_files_by_name(trash_name, trash=True)
                            if trash_name in st.session_state.file_selections:
                                st.session_state.file_selections[trash_name] = True
                            st.success(f"已成功恢复文件：{trash_name}")
                            st.rerun()
                with tc4:
                    if st.button("🔥 彻底删除", key=f"perma_del_file_{factory}_{trash_name}", use_container_width=True):
                        src_t_path = os.path.join(file_trash_dir, trash_name)
                        if os.path.exists(src_t_path):
                            os.remove(src_t_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_delete_files_by_name(os.path.basename(src_t_path), trash=True)
                            st.success(f"已彻底删除文件：{trash_name}")
                            st.rerun()

            # 批量操作按钮
            st.markdown("")
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("🔥 批量彻底删除选中项", use_container_width=True):
                    perma_any = False
                    for trash_name, is_sel in list(st.session_state.trash_del_selections.items()):
                        if is_sel:
                            src_t_path = os.path.join(file_trash_dir, trash_name)
                            if os.path.exists(src_t_path):
                                os.remove(src_t_path)
                                if r2_storage._get_r2_client() is not None:
                                    r2_storage.r2_delete_files_by_name(os.path.basename(src_t_path), trash=True)
                                st.session_state.trash_del_selections[trash_name] = False
                                perma_any = True
                    if perma_any:
                        st.success("已彻底删除选中的回收站文件！")
                        st.rerun()
                    else:
                        st.warning("请先勾选需要彻底删除的回收站文件。")
            with bc2:
                if st.button("⚠️ 清空回收站", use_container_width=True):
                    for trash_name in trashed_files:
                        src_t_path = os.path.join(file_trash_dir, trash_name)
                        if os.path.exists(src_t_path):
                            os.remove(src_t_path)
                            if r2_storage._get_r2_client() is not None:
                                r2_storage.r2_delete_files_by_name(os.path.basename(src_t_path), trash=True)
                    st.session_state.trash_del_selections = {}
                    st.success("已清空回收站！")
                    st.rerun()

    return active_paths
