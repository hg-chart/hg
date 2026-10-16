# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口（支持工厂增删与密码修改）"""

import inspect
import os
import runpy
import shutil
import streamlit as st
import streamlit_authenticator as stauth

import r2_storage

# ============================================================
# 0. 页面外观与基础配置
# ============================================================
st.set_page_config(
    page_title="设备运行数据分析系统",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* 隐藏右上角工具栏与页脚 */
    div[data-testid="stToolbar"] { visibility: hidden !important; display: none !important; }
    footer { visibility: hidden !important; }

    /* 视觉强锁：保障左侧栏固定显示 */
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        transform: none !important;
        width: 320px !important;
        min-width: 320px !important;
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        height: 100vh !important;
        z-index: 999999 !important;
    }

    .main .block-container {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 350px !important;
        padding-right: 2rem !important;
        padding-top: 1.5rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 1. 初始化工厂动态列表（支持动态增删）
# ============================================================
if "all_factories" not in st.session_state:
  st.session_state["all_factories"] = [
      "shanxihg",
      "太原分厂",
      "华东一厂",
      "华东二厂",
  ]

# ============================================================
# 2. 用户凭据与认证配置
# ============================================================
USER_CREDENTIALS = {
    "credentials": {
        "usernames": {
            "admin": {
                "name": "超级管理员",
                "password": "123456",  # 默认初始密码
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
# 3. 动态兼容不同版本的 authenticator.login() 签名
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
# 4. 侧边栏：会话信息、修改密码、工厂隔离与增删管理
# ============================================================
current_user = USER_CREDENTIALS["credentials"]["usernames"][username]
user_role = current_user.get("role", "user")
allowed_factories = current_user.get("allowed_factories", [])

st.sidebar.title("🔐 会话信息")
st.sidebar.write(f"当前用户：**{name}** (`{user_role}`)")

# 【功能二：修改密码】
with st.sidebar.expander("🔑 修改密码"):
  try:
    if authenticator.reset_password(username, "修改密码"):
      st.success("✅ 密码修改成功！")
  except Exception as e:
    # 兼容低版本 authenticator 手动修改
    new_password = st.text_input("新密码", type="password", key="reset_pwd_input")
    if st.button("确认重置"):
      if new_password:
        USER_CREDENTIALS["credentials"]["usernames"][username]["password"] = (
            new_password
        )
        st.success("✅ 密码重置成功，请妥善保管！")
      else:
        st.warning("密码不能为空")

authenticator.logout("退出登录", "sidebar")
st.sidebar.markdown("---")

st.sidebar.title("🏭 工厂工作区")

# 工厂选择下拉框
if user_role == "admin" or allowed_factories == "ALL":
  selected_factory = st.sidebar.selectbox(
      "选择目标工厂",
      st.session_state["all_factories"],
      key="factory_select_main_admin",
  )
else:
  # 普通用户过滤允许的工厂列表
  user_fac_list = [
      f for f in st.session_state["all_factories"] if f in allowed_factories
  ]
  if not user_fac_list:
    user_fac_list = allowed_factories
  selected_factory = st.sidebar.selectbox(
      "选择当前工厂", user_fac_list, key="factory_select_main_user"
  )

st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")

# 【功能一：管理员增加/删除工厂】
if user_role == "admin":
  st.sidebar.markdown("---")
  with st.sidebar.expander("⚙️ 管理员工具：工厂管理"):
    st.subheader("➕ 增加新工厂")
    new_fac_name = st.text_input(
        "新工厂名称", placeholder="例如：华南分厂", key="add_fac_input"
    )
    if st.button("确认添加工厂", key="btn_add_fac"):
      new_fac_name = new_fac_name.strip()
      if not new_fac_name:
        st.error("工厂名称不能为空！")
      elif new_fac_name in st.session_state["all_factories"]:
        st.warning("该工厂已存在！")
      else:
        st.session_state["all_factories"].append(new_fac_name)
        st.success(f"已成功添加工厂：{new_fac_name}")
        st.rerun()

    st.markdown("---")
    st.subheader("🗑️ 删除已有工厂")
    del_fac_name = st.selectbox(
        "选择要删除的工厂",
        st.session_state["all_factories"],
        key="del_fac_select",
    )
    if st.button("确认删除工厂", key="btn_del_fac"):
      if len(st.session_state["all_factories"]) <= 1:
        st.error("至少需要保留一个工厂！")
      else:
        st.session_state["all_factories"].remove(del_fac_name)
        st.success(f"已成功删除工厂：{del_fac_name}")
        st.rerun()

st.sidebar.markdown("---")

# ============================================================
# 5. 动态设置 R2 路径与数据隔离桥接
# ============================================================
r2_prefix = f"device-monitor/{selected_factory}/"
r2_storage.BASE_PREFIX = r2_prefix

factory_vault = f"uploaded_vault_{selected_factory}"
factory_trash = f"file_trash_{selected_factory}"
factory_chart = f"chart_history_{selected_factory}"

os.makedirs(factory_vault, exist_ok=True)
os.makedirs(factory_trash, exist_ok=True)
os.makedirs(factory_chart, exist_ok=True)

if r2_storage._get_r2_client() is not None:
  sync_key = f"_r2_synced_{selected_factory}"
  if not st.session_state.get(sync_key, False):
    with st.spinner(f"正在加载 [{selected_factory}] 的云端数据..."):
      r2_storage.sync_local_storage_with_r2(
          factory_vault, factory_trash, factory_chart
      )
    st.session_state[sync_key] = True

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

# ============================================================
# 6. 安全运行主仪表盘脚本
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
