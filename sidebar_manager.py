# -*- coding: utf-8 -*-
"""独立侧边栏与工厂工作区管理模块"""

import os
import shutil
import streamlit as st
import r2_storage

def render_sidebar(authenticator, name, username, user_credentials):
    """强制在绝对左侧渲染并接管侧边栏"""
    
    # 强制激活侧边栏上下文
    with st.sidebar:
        st.title("🔐 会话信息")
        st.write(f"当前用户：**{name}**")
        authenticator.logout("退出登录", "sidebar")
        st.markdown("---")

        st.title("🏭 工厂工作区")

        current_user = user_credentials["credentials"]["usernames"][username]
        user_role = current_user.get("role", "user")
        allowed_factories = current_user.get("allowed_factories", [])
        all_factories = ["shanxihg", "太原分厂X", "华东一厂X", "华东二厂X"]

        if user_role == "admin" or allowed_factories == "ALL":
            selected_factory = st.selectbox("选择目标工厂", all_factories, key="sidebar_factory_select_admin")
        else:
            selected_factory = st.selectbox("选择当前工厂", allowed_factories, key="sidebar_factory_select_user")

        st.success(f"已连接工作区：\n**{selected_factory}**")
        st.markdown("---")

    # 绑定当前工厂的 R2 前缀与本地文件夹隔离
    r2_prefix = f"device-monitor/{selected_factory}/"
    r2_storage.BASE_PREFIX = r2_prefix

    factory_vault = f"uploaded_vault_{selected_factory}"
    factory_trash = f"file_trash_{selected_factory}"
    factory_chart = f"chart_history_{selected_factory}"

    os.makedirs(factory_vault, exist_ok=True)
    os.makedirs(factory_trash, exist_ok=True)
    os.makedirs(factory_chart, exist_ok=True)

    # 自动从云端同步数据
    if r2_storage._get_r2_client() is not None:
        sync_key = f"_r2_synced_{selected_factory}"
        if not st.session_state.get(sync_key, False):
            with st.spinner(f"正在加载 [{selected_factory}] 的云端数据..."):
                r2_storage.sync_local_storage_with_r2(factory_vault, factory_trash, factory_chart)
            st.session_state[sync_key] = True

    # 将当前工厂目录软链接映射给主程序
    standard_vault = "uploaded_vault"
    if os.path.lexists(standard_vault):
        if os.path.islink(standard_vault) or os.path.isfile(standard_vault):
            os.unlink(standard_vault)
        else:
            shutil.rmtree(standard_vault)

    try:
        os.symlink(factory_vault, standard_vault, target_is_directory=True)
    except Exception:
        if os.path.exists(factory_vault):
            shutil.copytree(factory_vault, standard_vault, dirs_exist_ok=True)

    return selected_factory
