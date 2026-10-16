# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 多租户安全网关与隔离入口"""

import os
import r2_storage
import streamlit as st
import streamlit_authenticator as stauth

# 导入已经改名的原业务主代码模块
import main_dashboard

# ============================================================
# 0. 全局页面配置与外观净化
# ============================================================
st.set_page_config(page_title="设备运行数据分析系统", layout="wide")

# 隐藏右上角 Streamlit 部署与菜单按钮，净化 UI
st.markdown(
    """
    <style>
    div[data-testid="stToolbar"] {
        visibility: hidden;
        display: none !important;
    }
    footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 1. 组织架构与多租户权限字典定义
# ============================================================
# 现有历史数据对应已经搬家完成的 'shanxihg'
ALL_FACTORIES_DEF = {
    "红光集团": ["shanxihg", "太原分厂"],
    "华东区域": ["华东一厂", "华东二厂"],
}

# 用户账号权限表
USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": (
                    "$2b$12$eImiTXuWVxfM37uY4JANjQ=="
                ),  # 默认密码: 123456
                "role": "admin",
                "allowed_factories": "ALL",  # 超级管理员拥有上帝视角，可自由切换所有工厂
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": (
                    "$2b$12$eImiTXuWVxfM37uY4JANjQ=="
                ),  # 默认密码: 123456
                "role": "user",
                "allowed_factories": [
                    "shanxihg"
                ],  # 只能看到 shanxihg，对其他工厂一无所知
            },
        }
    },
    "cookie": {
        "expiry_days": 30,
        "key": "factory_gateway_secure_key",
        "name": "factory_gateway_cookie",
    },
}

# 初始化登录组件
authenticator = stauth.Authenticate(
    USER_CREDENTIALS["credentials"],
    USER_CREDENTIALS["cookie"]["name"],
    USER_CREDENTIALS["cookie"]["key"],
    USER_CREDENTIALS["cookie"]["expiry_days"],
    auto_hash=False,
)

name, authentication_status, username = authenticator.login(
    "请登录设备运行数据分析系统", "main"
)

if authentication_status == False:
  st.error("❌ 用户名或密码错误")
  st.stop()
elif authentication_status == None:
  st.info("👉 请输入您的登录凭据以访问系统")
  st.stop()

# ============================================================
# 2. 侧边栏：绝对隔离的动态工厂切换路由
# ============================================================
current_user = USER_CREDENTIALS["credentials"]["usernames"][username]
user_role = current_user.get("role", "user")
allowed_factories = current_user.get("allowed_factories", [])

st.sidebar.title("🔐 会话信息")
st.sidebar.write(f"当前用户：**{name}**")
authenticator.logout("退出登录", "sidebar")
st.sidebar.markdown("---")

st.sidebar.title("🏭 工作区选择")

if user_role == "admin" or allowed_factories == "ALL":
  # 管理员：自由选择集团和所有子工厂
  selected_group = st.sidebar.selectbox(
      "选择集团/区域", list(ALL_FACTORIES_DEF.keys())
  )
  available_factories = ALL_FACTORIES_DEF[selected_group]
  selected_factory = st.sidebar.selectbox("选择目标工厂", available_factories)
else:
  # 普通用户：绝对隔离，侧边栏只能看到被授权的工厂名称，隐匿其余所有工厂
  selected_factory = st.sidebar.selectbox("选择当前工作区", allowed_factories)

  # 自动推导该工厂归属的集团组名
  selected_group = "Authorized_Group"
  for g_name, f_list in ALL_FACTORIES_DEF.items():
    if selected_factory in f_list:
      selected_group = g_name
      break

# 将当前隔离上下文缓存进 session_state
st.session_state["selected_factory"] = selected_factory
st.session_state["selected_group"] = selected_group

st.sidebar.success(f"已安全连接工作区：\n**{selected_factory}**")
st.sidebar.markdown("---")

# ============================================================
# 3. 动态 R2 前缀锁定与本地目录隔离同步
# ============================================================
# 关键：当 selected_factory 为 'shanxihg' 时，自动无缝读取刚刚迁移成功的数据！
r2_storage.BASE_PREFIX = f"device-monitor/{selected_factory}/"

VAULT_DIR = f"uploaded_vault_{selected_factory}"
FILE_TRASH_DIR = f"file_trash_{selected_factory}"
CHART_HISTORY_DIR = f"chart_history_{selected_factory}"

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(FILE_TRASH_DIR, exist_ok=True)
os.makedirs(CHART_HISTORY_DIR, exist_ok=True)

if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在安全同步 [{selected_factory}] 云端文件..."):
      r2_storage.sync_local_storage_with_r2(
          VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR
      )
    st.session_state[sync_key] = True

# ============================================================
# 4. 安全唤醒与运行主业务模块
# ============================================================
# 如果你的 main_dashboard.py 里写了 render_dashboard 函数，则直接调用它；
# 如果没有定义函数，直接 import 运行也完全支持。
if hasattr(main_dashboard, "render_dashboard"):
  main_dashboard.render_dashboard(selected_factory, selected_group)
