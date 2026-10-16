# -*- coding: utf-8 -*-
"""设备运行数据分析系统 - 工厂安全隔离路由网关入口（支持工厂增删、回收站、用户账号/姓名/密码修改）"""

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
# 1. 初始化工厂列表与用户凭据 Session State
# ============================================================
if "all_factories" not in st.session_state:
  st.session_state["all_factories"] = [
      "shanxihg",
      "太原分厂",
      "华东一厂",
      "华东二厂",
  ]

if "factory_trash" not in st.session_state:
  st.session_state["factory_trash"] = []

if "user_db" not in st.session_state:
  st.session_state["user_db"] = {
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

# ============================================================
# 2. 动态创建认证器
# ============================================================
authenticator = stauth.Authenticate(
    st.session_state["user_db"]["credentials"],
    st.session_state["user_db"]["cookie"]["name"],
    st.session_state["user_db"]["cookie"]["key"],
    st.session_state["user_db"]["cookie"]["expiry_days"],
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
    or username
    not in st.session_state["user_db"]["credentials"]["usernames"]
):
  st.error("登录状态异常，请刷新页面后重新登录。")
  st.stop()


# ============================================================
# 辅助函数：高容错 R2 云端数据彻底删除逻辑
# ============================================================
def purge_factory_r2_data(target_factory):
  """在回收站彻底删除工厂时，清除 Cloudflare R2 上该工厂前缀的所有数据"""
  try:
    r2_client = r2_storage._get_r2_client()
    bucket_name = getattr(r2_storage, "R2_BUCKET_NAME", None)

    if r2_client is not None and bucket_name:
      target_prefix = f"device-monitor/{target_factory}/"
      paginator = r2_client.get_paginator("list_objects_v2")
      pages = paginator.paginate(Bucket=bucket_name, Prefix=target_prefix)

      objects_to_delete = []
      for page in pages:
        if "Contents" in page:
          for obj in page["Contents"]:
            objects_to_delete.append({"Key": obj["Key"]})

      if objects_to_delete:
        for i in range(0, len(objects_to_delete), 1000):
          r2_client.delete_objects(
              Bucket=bucket_name,
              Delete={"Objects": objects_to_delete[i : i + 1000]},
          )
  except Exception as e:
    print(f"清理 R2 云端数据提示: {e}")


# ============================================================
# 定义弹窗组件：工厂彻底删除二次验证对话框
# ============================================================
@st.dialog("⚠️ 彻底删除工厂高危操作确认")
def confirm_permanent_delete_dialog(target_factory):
  st.warning(
      f"您正在彻底删除工厂：**【{target_factory}】**！\n\n此操作将**不可逆地永久删除**该工厂在"
      " Cloudflare R2 云端及本地的所有隔离数据。"
  )
  st.write("为了防止误操作，请输入要删除的工厂完整名称进行确认：")

  typed_name = st.text_input(
      f"请精准输入：{target_factory}", key="dialog_confirm_input"
  )

  col1, col2 = st.columns(2)
  with col1:
    if st.button("❌ 取消操作", use_container_width=True, key="dlg_btn_cancel"):
      st.rerun()

  with col2:
    if (
        st.button(
            "🔥 确认彻底删除",
            type="primary",
            use_container_width=True,
            key="dlg_btn_confirm",
        )
    ):
      if typed_name.strip() == target_factory:
        # 1. 彻底清除 R2 云端数据
        purge_factory_r2_data(target_factory)

        # 2. 从回收站移除
        if target_factory in st.session_state["factory_trash"]:
          st.session_state["factory_trash"].remove(target_factory)

        # 3. 清除本地缓存文件夹
        for folder_suffix in ["uploaded_vault", "file_trash", "chart_history"]:
          local_dir = f"{folder_suffix}_{target_factory}"
          if os.path.exists(local_dir):
            shutil.rmtree(local_dir, ignore_errors=True)

        st.success(f"工厂【{target_factory}】及其 R2 云端数据已彻底永久销毁！")
        st.rerun()
      else:
        st.error(
            f"输入的工厂名称不匹配！要求输入：{target_error}，实际输入：{typed_name}"
        )


# ============================================================
# 4. 侧边栏：会话信息、修改密码、工厂隔离与全能管理员工具
# ============================================================
current_user = st.session_state["user_db"]["credentials"]["usernames"][
    username
]
user_role = current_user.get("role", "user")
user_disp_name = current_user.get("name", username)
allowed_factories = current_user.get("allowed_factories", [])

st.sidebar.title("🔐 会话信息")
st.sidebar.write(f"当前用户：**{user_disp_name}** (`{username}`)")

# 修改个人密码
with st.sidebar.expander("🔑 修改我的密码"):
  new_self_pwd = st.text_input(
      "新密码", type="password", key="reset_self_pwd_input"
  )
  if st.button("确认重置", key="btn_reset_self_pwd"):
    if new_self_pwd:
      st.session_state["user_db"]["credentials"]["usernames"][username][
          "password"
      ] = new_self_pwd
      st.success("✅ 个人密码重置成功，下次登录生效！")
    else:
      st.warning("密码不能为空")

authenticator.logout("退出登录", "sidebar")
st.sidebar.markdown("---")

st.sidebar.title("🏭 工厂工作区")

# 如果当前选中的工厂刚好被移入回收站，自动重置选中项
if st.session_state.get("selected_factory_val") not in st.session_state[
    "all_factories"
]:
  if st.session_state["all_factories"]:
    st.session_state["selected_factory_val"] = st.session_state[
        "all_factories"
    ][0]

# 工厂选择下拉框
if user_role == "admin" or allowed_factories == "ALL":
  selected_factory = st.sidebar.selectbox(
      "选择目标工厂",
      st.session_state["all_factories"],
      key="factory_select_main_admin",
  )
else:
  user_fac_list = [
      f for f in st.session_state["all_factories"] if f in allowed_factories
  ]
  if not user_fac_list:
    user_fac_list = (
        allowed_factories
        if isinstance(allowed_factories, list)
        else [allowed_factories]
    )
  selected_factory = st.sidebar.selectbox(
      "选择当前工厂", user_fac_list, key="factory_select_main_user"
  )

st.session_state["selected_factory_val"] = selected_factory
st.sidebar.success(f"已连接工作区：\n**{selected_factory}**")

# 【超级管理员工具箱：工厂管理 + 用户账号/显示名/密码统一编辑】
if user_role == "admin":
  st.sidebar.markdown("---")

  # 1. 用户账号与资料全面编辑板块
  with st.sidebar.expander("👥 用户账号与资料管理"):
    st.markdown("#### ✏️ 编辑现有用户资料")
    all_users = list(
        st.session_state["user_db"]["credentials"]["usernames"].keys()
    )
    target_u = st.selectbox(
        "选择要修改的用户", all_users, key="select_u_to_edit_full"
    )
    
    u_info = st.session_state["user_db"]["credentials"]["usernames"][target_u]

    # 编辑登录账号名
    edit_uname = st.text_input(
        "登录账号 (Username)", value=target_u, key=f"edit_uname_{target_u}"
    )
    # 编辑显示姓名
    edit_disp_name = st.text_input(
        "人员姓名/显示名 (Name)", value=u_info.get("name", ""), key=f"edit_disp_{target_u}"
    )
    # 编辑密码（留空表示不修改密码）
    edit_pwd = st.text_input(
        "重置密码 (留空则保持原密码)", type="password", key=f"edit_pwd_{target_u}"
    )
    
    # 编辑允许访问的工厂
    current_allowed = u_info.get("allowed_factories", [])
    if current_allowed == "ALL":
      default_selected_facs = st.session_state["all_factories"]
    else:
      default_selected_facs = [f for f in current_allowed if f in st.session_state["all_factories"]]

    edit_facs = st.multiselect(
        "允许访问的工厂",
        st.session_state["all_factories"],
        default=default_selected_facs,
        key=f"edit_facs_{target_u}"
    )

    if st.button("保存修改", key="btn_save_u_edit", use_container_width=True):
      new_u = edit_uname.strip()
      if not new_u:
        st.error("登录账号不能为空！")
      elif new_u != target_u and new_u in st.session_state["user_db"]["credentials"]["usernames"]:
        st.error(f"登录账号【{new_u}】已被占用，请换一个！")
      else:
        # 构建更新后的用户配置
        updated_user_config = {
            "name": edit_disp_name.strip() if edit_disp_name.strip() else new_u,
            "password": edit_pwd if edit_pwd else u_info.get("password"),
            "role": u_info.get("role", "user"),
            "allowed_factories": edit_facs if u_info.get("role") != "admin" else "ALL"
        }

        # 如果修改了账号 key（Username），转移数据并删除旧 key
        if new_u != target_u:
          del st.session_state["user_db"]["credentials"]["usernames"][target_u]
        
        st.session_state["user_db"]["credentials"]["usernames"][new_u] = updated_user_config
        st.success(f"用户【{new_u}】资料已更新成功！")
        st.rerun()

    st.markdown("---")
    st.markdown("#### ➕ 创建新账号")
    new_uname = st.text_input(
        "新账号 (Username)", placeholder="例: taiyuan_user", key="new_u_name"
    )
    new_disp_name = st.text_input(
        "显示名 (Name)", placeholder="例: 太原厂长", key="new_u_disp"
    )
    new_u_pwd = st.text_input(
        "初始密码", type="password", key="new_u_pwd_input"
    )

    assigned_facs = st.multiselect(
        "授权工厂",
        st.session_state["all_factories"],
        key="select_user_allowed_facs",
    )

    if st.button("确认创建用户", key="btn_create_new_user", use_container_width=True):
      new_uname = new_uname.strip()
      if not new_uname or not new_u_pwd:
        st.error("账号和密码为必填项！")
      elif (
          new_uname
          in st.session_state["user_db"]["credentials"]["usernames"]
      ):
        st.error("该账号已存在！")
      else:
        st.session_state["user_db"]["credentials"]["usernames"][new_uname] = {
            "name": new_disp_name.strip() if new_disp_name.strip() else new_uname,
            "password": new_u_pwd,
            "role": "user",
            "allowed_factories": assigned_facs
            if assigned_facs
            else st.session_state["all_factories"],
        }
        st.success(f"用户账号【{new_uname}】创建成功！")
        st.rerun()

    st.markdown("---")
    st.markdown("#### 🗑️ 删除用户账号")
    user_to_del = st.selectbox(
        "选择要删除的账号",
        [u for u in all_users if u != "admin"],
        key="select_u_del",
    )
    if st.button("确认删除账号", key="btn_del_user_acc", use_container_width=True):
      if user_to_del:
        del st.session_state["user_db"]["credentials"]["usernames"][
            user_to_del
        ]
        st.success(f"账号【{user_to_del}】已成功删除！")
        st.rerun()

  # 2. 工厂与回收站管理板块
  with st.sidebar.expander("⚙️ 工厂管理与回收站"):
    # 增加工厂
    st.markdown("#### ➕ 增加新工厂")
    new_fac_name = st.text_input(
        "新工厂名称", placeholder="例如：华南分厂", key="add_fac_input"
    )
    if st.button("确认添加工厂", key="btn_add_fac", use_container_width=True):
      new_fac_name = new_fac_name.strip()
      if not new_fac_name:
        st.error("工厂名称不能为空！")
      elif (
          new_fac_name in st.session_state["all_factories"]
          or new_fac_name in st.session_state["factory_trash"]
      ):
        st.warning("该工厂已存在或已在回收站中！")
      else:
        st.session_state["all_factories"].append(new_fac_name)
        st.success(f"已成功添加工厂：{new_fac_name}")
        st.rerun()

    st.markdown("---")
    # 软删除：移入回收站
    st.markdown("#### 🗑️ 软删除（移入回收站）")
    st.caption("提示：移入回收站时不会删除 R2 云端数据，可在下方还原。")
    del_fac_name = st.selectbox(
        "选择移入回收站的工厂",
        st.session_state["all_factories"],
        key="del_fac_select",
    )
    if st.button(
        "📥 移入回收站", key="btn_move_trash", use_container_width=True
    ):
      if len(st.session_state["all_factories"]) <= 1:
        st.error("至少需要保留一个活跃工厂！")
      else:
        st.session_state["all_factories"].remove(del_fac_name)
        st.session_state["factory_trash"].append(del_fac_name)
        st.success(f"工厂【{del_fac_name}】已移入回收站（R2 云端数据完整保留）")
        st.rerun()

    st.markdown("---")
    # 工厂回收站管理
    st.markdown("#### ♻️ 工厂回收站")
    if not st.session_state["factory_trash"]:
      st.info("回收站为空")
    else:
      trash_fac_selected = st.selectbox(
          "回收站中的工厂",
          st.session_state["factory_trash"],
          key="trash_fac_select",
      )

      c_res, c_purge = st.columns(2)
      with c_res:
        if st.button(
            "↩️ 还原工厂", key="btn_restore_fac", use_container_width=True
        ):
          st.session_state["factory_trash"].remove(trash_fac_selected)
          st.session_state["all_factories"].append(trash_fac_selected)
          st.success(f"工厂【{trash_fac_selected}】已恢复！")
          st.rerun()

      with c_purge:
        if st.button(
            "🔥 彻底删除", key="btn_trigger_dialog", use_container_width=True
        ):
          confirm_permanent_delete_dialog(trash_fac_selected)

st.sidebar.markdown("---")

# ============================================================
# 5. 动态设置 R2 路径与高容错防崩溃数据桥接
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

try:
  if os.path.lexists(standard_vault):
    if os.path.islink(standard_vault) or os.path.isfile(standard_vault):
      os.unlink(standard_vault)
    else:
      shutil.rmtree(standard_vault, ignore_errors=True)
except Exception:
  pass

try:
  if not os.path.exists(standard_vault):
    os.symlink(factory_vault, standard_vault, target_is_directory=True)
except Exception:
  pass

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
