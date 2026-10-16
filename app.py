# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import streamlit as st
import inspect
import runpy
import streamlit_authenticator as stauth

# 导入独立模块
import sidebar_manager

# ============================================================
# 0. 页面外观与全局全屏宽屏配置（彻底解决窄屏留白与侧边栏消失）
# ============================================================
st.set_page_config(
    page_title="设备运行数据分析系统", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    /* 1. 隐藏右上角工具栏与页脚 */
    div[data-testid="stToolbar"] {
        visibility: hidden !important;
        display: none !important;
    }
    footer {
        visibility: hidden !important;
    }

    /* 2. 强制全屏铺满（解决两边留白过大、图表太窄、字太小的问题） */
    .main .block-container {
        max-width: 98% !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        padding-top: 1rem !important;
    }

    /* 3. 强制侧边栏常驻铺满屏幕左侧 */
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        min-width: 280px !important;
        max-width: 320px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 1. 多工厂与权限字典配置
# ============================================================
USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": "123456",
                "role": "admin",
                "allowed_factories": "ALL",
            },
            "shanxi_user": {
                "name": "山西红光厂长",
                "password": "123456",
                "role": "user",
                "allowed_factories": ["shanxihg"],
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
    auto_hash=True,
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
# 3. 调用独立模块渲染侧边栏与工厂隔离
# ============================================================
selected_factory = sidebar_manager.render_sidebar(
    authenticator, name, username, USER_CREDENTIALS
)

# ============================================================
# 4. 安全运行主仪表盘脚本（保留全局 wide 布局）
# ============================================================
original_set_page_config = st.set_page_config

def safe_set_page_config(*args, **kwargs):
  # 强制将后续任何 set_page_config 调用的 layout 都改为 wide
  kwargs["layout"] = "wide"
  kwargs["initial_sidebar_state"] = "expanded"
  try:
      original_set_page_config(*args, **kwargs)
  except Exception:
      pass

st.set_page_config = safe_set_page_config

try:
  # 使用 runpy 独立安全地执行原版 main_dashboard.py
  runpy.run_path("main_dashboard.py", run_name="__main__")
finally:
  st.set_page_config = original_set_page_config
