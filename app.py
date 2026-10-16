# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import inspect
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

# 使用标准的 60 位 bcrypt 哈希（对应密码均为：123456）
VALID_PASSWORD_HASH = (
    "$2b$12$VvxV2xQ8z5vV8z5vV8z5vuW8z5vV8z5vV8z5vV8z5vV8z5vV8z5vK"
)
# 如果上方占位哈希验证不通过，你可以用下面这个通过标准库生成的真实 123456 哈希
# '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW'
REAL_PASSWORD_HASH = (
    "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
)

USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": REAL_PASSWORD_HASH,
                "role": "admin",
                "allowed_factories": "ALL",  # 上帝视角，可以下拉切换所有工厂
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": REAL_PASSWORD_HASH,
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

# ============================================================
# 2. 动态兼容不同版本的 authenticator.login() 签名
# ============================================================
login_parameters = inspect.signature(authenticator.login).parameters

if "form_name" in login_parameters:
  login_result = authenticator.login("请登录设备运行数据分析系统", "main")
elif "location" in login_parameters:
  login_result = authenticator.login(location="main")
else:
  login_result = authenticator.login()

# 兼容返回三元组或通过 session_state 获取结果的不同版本
if isinstance(login_result, (tuple, list)) and len(login_result) == 3:
  name, authentication_status, username = login_result
else:
  name = st.session_state.get("name")
  authentication_status = st.session_state.get("authentication_status")
  username = st.session_state.get("username")

if authentication_status is False:
  st.error("❌ 用户名或密码错误")
  st.stop()
elif authentication_status is None:
  st.info("👉 请输入您的登录凭据以访问系统")
  st.stop()
elif (
    authentication_status is not True
    or username not in USER_CREDENTIALS["credentials"]["usernames"]
):
  st.error("登录状态异常，请刷新页面后重新登录。")
  st.stop()

# ============================================================
# 3. 侧边栏：极简工厂选择与隔离
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
  selected_factory = st.sidebar.selectbox("选择目标工厂", ALL_FACTORIES)
else:
  selected_factory = st.sidebar.selectbox("选择当前工厂", allowed_factories)

st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")
st.sidebar.markdown("---")

# ============================================================
# 4. 动态设置 R2 路径并同步，随后唤醒业务主脚本
# ============================================================
r2_prefix = f"device-monitor/{selected_factory}/"
r2_storage.BASE_PREFIX = r2_prefix

vault_dir = "uploaded_vault"
file_trash_dir = "file_trash"
chart_history_dir = "chart_history"

os.makedirs(vault_dir, exist_ok=True)
os.makedirs(file_trash_dir, exist_ok=True)
os.makedirs(chart_history_dir, exist_ok=True)

if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在加载 [{selected_factory}] 的云端数据..."):
      r2_storage.sync_local_storage_with_r2(
          vault_dir, file_trash_dir, chart_history_dir
      )
    st.session_state[sync_key] = True

import main_dashboard
