# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import os
import streamlit as st
import streamlit_authenticator as stauth

# 1. 导入 r2_storage 模块
import r2_storage

# ============================================================
# 0. 页面外观与基础配置
# ============================================================
st.set_page_config(page_title="设备运行数据分析系统", layout="wide")

# 隐藏右上角工具栏与页脚
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
# 1. 多工厂与权限字典配置
# ============================================================
# 平铺所有工厂列表（对应 R2 存储桶 device-monitor/ 下的文件夹名）
ALL_FACTORIES = ["shanxihg", "太原分厂", "华东一厂", "华东二厂"]

USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": (
                    "$2b$12$eImiTXuWVxfM37uY4JANjQ=="
                ),  # 默认密码: 123456
                "role": "admin",
                "allowed_factories": "ALL",  # 上帝视角，可以下拉切换所有工厂
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": (
                    "$2b$12$eImiTXuWVxfM37uY4JANjQ=="
                ),  # 默认密码: 123456
                "role": "user",
                "allowed_factories": [
                    "shanxihg"
                ],  # 只能看到 shanxihg，对其余工厂无感知
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

# 已修复：修正了 authenticate.login 的调用方式
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
# 2. 侧边栏：极简工厂选择与隔离
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
  # 超级管理员：可自由下拉选择所有工厂
  selected_factory = st.sidebar.selectbox("选择目标工厂", ALL_FACTORIES)
else:
  # 普通工厂用户：锁定为其授权的工厂，彻底隔离
  selected_factory = st.sidebar.selectbox("选择当前工厂", allowed_factories)

st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")
st.sidebar.markdown("---")

# ============================================================
# 3. 在导入并加载主业务前，动态设置 R2 的爹文件夹路径
# ============================================================
# 关键点：把 R2 基础前缀直接指向当前选中的工厂，例如 device-monitor/shanxihg/
r2_prefix = f"device-monitor/{selected_factory}/"
r2_storage.BASE_PREFIX = r2_prefix

# 创建本地对应的缓存文件夹，避免冲突
vault_dir = "uploaded_vault"
file_trash_dir = "file_trash"
chart_history_dir = "chart_history"

os.makedirs(vault_dir, exist_ok=True)
os.makedirs(file_trash_dir, exist_ok=True)
os.makedirs(chart_history_dir, exist_ok=True)

# 强制触发一次同步，把 shanxihg 里的文件拉到本地
if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在加载 [{selected_factory}] 的云端数据..."):
      r2_storage.sync_local_storage_with_r2(
          vault_dir, file_trash_dir, chart_history_dir
      )
    st.session_state[sync_key] = True

# ============================================================
# 4. 动态唤醒并运行原版业务主脚本 main_dashboard.py
# ============================================================
# 此时 R2 的路径已经被替换为了 device-monitor/shanxihg/，主脚本运行后就会直接显示出你搬家过去的所有文件！
import main_dashboard
