# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口"""

import streamlit as st
import inspect
import runpy
import streamlit_authenticator as stauth

import sidebar_manager

# ============================================================
# 0. 页面外观与绝对全屏宽屏配置
# ============================================================
st.set_page_config(
    page_title="设备运行数据分析系统", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    /* 1. 隐藏多余元素 */
    div[data-testid="stToolbar"] { visibility: hidden !important; display: none !important; }
    footer { visibility: hidden !important; }

    /* 2. 彻底打破两边留白，强制图表和容器 100% 铺满全屏 */
    .main .block-container {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
        padding-top: 1rem !important;
    }

    /* 3. 强制侧边栏固定显示在左侧且不被压缩 */
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        width: 300px !important;
        min-width: 300px !important;
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
# 4. 安全运行主仪表盘脚本
# ============================================================
original_set_page_config = st.set_page_config

def safe_set_page_config(*args, **kwargs):
  kwargs["layout"] = "wide"
  kwargs["initial_sidebar_state"] = "expanded"
  try:
      original_set_page_config(*args, **kwargs)
  except Exception:
      pass

st.set_page_config = safe_set_page_config

try:
  runpy.run_path("main_dashboard.py", run_name="__main__")
finally:
  st.set_page_config = original_set_page_config
