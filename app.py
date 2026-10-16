# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 直接按工厂隔离的网关入口"""

import os
import r2_storage
import streamlit as st
import streamlit_authenticator as stauth

import main_dashboard

# ============================================================
# 0. 全局页面配置
# ============================================================
st.set_page_config(page_title="设备运行数据分析系统", layout="wide")

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
# 1. 工厂列表与用户权限定义（直接按工厂平铺）
# ============================================================
# 系统中所有的工厂列表（直接对应 R2 中的文件夹名）
ALL_FACTORIES = ["shanxihg", "太原分厂", "华东一厂", "华东二厂"]

USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": "$2b$12$eImiTXuWVxfM37uY4JANjQ==",  # 默认密码: 123456
                "role": "admin",
                "allowed_factories": "ALL",  # 管理员可以切换所有工厂
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": "$2b$12$eImiTXuWVxfM37uY4JANjQ==",  # 默认密码: 123456
                "role": "user",
                "allowed_factories": [
                    "shanxihg"
                ],  # 只能看 shanxihg，看不到其他任何工厂
            },
        }
    },
    "cookie": {
        "expiry_days": 30,
        "key": "factory_gateway_secure_key",
        "name": "factory_gateway_cookie",
    },
}

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
  st.info("👉 请输入您的登录凭据")
  st.stop()

# ============================================================
# 2. 侧边栏：极简的工厂直接切换
# ============================================================
current_user = USER_CREDENTIALS["credentials"]["usernames"][username]
user_role = current_user.get("role", "user")
allowed_factories = current_user.get("allowed_factories", [])

st.sidebar.title("🔐 会话信息")
st.sidebar.write(f"当前用户：**{name}**")
authenticator.logout("退出登录", "sidebar")
st.sidebar.markdown("---")

st.sidebar.title("🏭 工厂工作区")

if user_role == "admin" or allowed_factories == "ALL":
  # 管理员：直接从所有工厂里选择
  selected_factory = st.sidebar.selectbox("选择目标工厂", ALL_FACTORIES)
else:
  # 普通用户：只展示其被授权的工厂，彻底隔离
  selected_factory = st.sidebar.selectbox("选择当前工厂", allowed_factories)

# 将工厂名存入 session_state（不需要集团概念了，传空或传本身即可）
st.session_state["selected_factory"] = selected_factory
st.session_state["selected_group"] = "default"

st.sidebar.success(f"当前生效工厂：\n**{selected_factory}**")
st.sidebar.markdown("---")

# ============================================================
# 3. 动态 R2 路径隔离与本地同步
# ============================================================
# 完美对接你已经建好的 shanxihg 文件夹
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
    with st.spinner(f"正在同步 [{selected_factory}] 的云端数据..."):
      r2_storage.sync_local_storage_with_r2(
          VAULT_DIR, FILE_TRASH_DIR, CHART_HISTORY_DIR
      )
    st.session_state[sync_key] = True

# ============================================================
# 4. 加载并运行主业务模块
# ============================================================
if hasattr(main_dashboard, "render_dashboard"):
  main_dashboard.render_dashboard(selected_factory, "default")
