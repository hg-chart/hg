# -*- coding: utf-8 -*-
"""用户账号与权限管理模块（用户库以 Cloudflare R2 为准，密码加密保存）

存储位置（R2，私有桶）：
  device-monitor/_system/users_db.json          用户库（密码为 bcrypt 加密串，不存明文）
  device-monitor/_system/users_db.backup.json   每次修改前的上一版备份

可靠性设计：
  - 新增 / 修改 / 删除用户时：先读取云端最新用户库 -> 修改 -> 写回 R2 成功后页面才更新。
  - 只有 R2 明确回答“用户库不存在”（首次使用）时才会初始化；
    读取失败（网络、权限等）时绝不会用默认账号覆盖云端数据，而是报错停止。
  - 首次初始化时，如果服务器本地还留有旧的 users_db.json，会优先迁移它（保住已有用户）。
  - 旧版本留下的明文密码，会在读取时自动加密并写回。
"""

import copy
import json
import os
import secrets

import streamlit as st

import factory_registry as freg

USER_DB_FILE = "users_db.json"  # 本地副本：R2 不可用时的后备，也用于首次迁移
USER_DB_KEY = f"{freg.ROOT_PREFIX}{freg.SYSTEM_DIR}/users_db.json"
USER_DB_BACKUP_KEY = f"{freg.ROOT_PREFIX}{freg.SYSTEM_DIR}/users_db.backup.json"

LEGACY_DEFAULT_PASSWORD = "123456"
MIN_PASSWORD_LEN = 6


class UserDBUnavailable(Exception):
  """云端用户库暂时读不到（不是“不存在”）。调用方应报错停止，而不是初始化默认账号。"""


# ------------------------------------------------------------
# 密码加密（bcrypt，与 streamlit_authenticator 的校验方式兼容）
# ------------------------------------------------------------
def _is_hash(value):
  return (
      isinstance(value, str)
      and len(value) == 60
      and value.startswith(("$2a$", "$2b$", "$2y$"))
  )


def hash_password(plain):
  import bcrypt

  return bcrypt.hashpw(str(plain).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(plain, hashed):
  try:
    import bcrypt

    return bcrypt.checkpw(str(plain).encode("utf-8"), str(hashed).encode("utf-8"))
  except Exception:  # noqa: BLE001
    return False


def validate_password(plain):
  plain = plain or ""
  if len(plain) < MIN_PASSWORD_LEN:
    return False, f"密码至少 {MIN_PASSWORD_LEN} 位！"
  if len(plain.encode("utf-8")) > 72:
    return False, "密码过长（最多 72 字节，约 72 个英文字符或 24 个汉字）！"
  return True, ""


# ------------------------------------------------------------
# 用户库结构整理 / 初始化
# ------------------------------------------------------------
def _normalize_db(db):
  """补全结构，并把遗留的明文密码加密。返回 (db, 是否有改动)。"""
  changed = False
  if not isinstance(db, dict):
    db = {}
    changed = True
  creds = db.setdefault("credentials", {})
  users = creds.setdefault("usernames", {})
  for uname, info in list(users.items()):
    if not isinstance(info, dict):
      del users[uname]
      changed = True
      continue
    pw = info.get("password", "")
    if pw and not _is_hash(pw):
      info["password"] = hash_password(pw)
      changed = True
    info.setdefault("name", uname)
    info.setdefault("role", "user")
    info.setdefault("allowed_factories", [])
  cookie = db.setdefault("cookie", {})
  if not cookie.get("key") or cookie.get("key") == "factory_gateway_secure_key":
    cookie["key"] = secrets.token_hex(32)
    changed = True
  cookie.setdefault("expiry_days", 30)
  cookie.setdefault("name", "factory_gateway_cookie")
  return db, changed


def _load_local():
  if os.path.exists(USER_DB_FILE):
    try:
      with open(USER_DB_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
      if data.get("credentials", {}).get("usernames"):
        return data
    except Exception:  # noqa: BLE001
      pass
  return None


def _save_local(db):
  try:
    with open(USER_DB_FILE, "w", encoding="utf-8") as f:
      json.dump(db, f, ensure_ascii=False, indent=2)
  except Exception:  # noqa: BLE001
    pass


def _bootstrap_db():
  """首次使用时的初始用户库：优先迁移本地旧文件，否则只建一个初始管理员。"""
  legacy = _load_local()
  if legacy:
    return legacy
  admin_user, admin_pw = "admin", LEGACY_DEFAULT_PASSWORD
  try:  # 推荐在 Streamlit Secrets 里设置，避免使用默认密码
    admin_user = str(st.secrets.get("INITIAL_ADMIN_USERNAME", admin_user)).strip() or admin_user
    admin_pw = str(st.secrets.get("INITIAL_ADMIN_PASSWORD", admin_pw)) or admin_pw
  except Exception:  # noqa: BLE001
    pass
  return {
      "credentials": {
          "usernames": {
              admin_user: {
                  "name": "超级管理员",
                  "password": admin_pw,
                  "role": "admin",
                  "allowed_factories": "ALL",
              }
          }
      },
      "cookie": {
          "expiry_days": 30,
          "key": secrets.token_hex(32),
          "name": "factory_gateway_cookie",
      },
  }


# ------------------------------------------------------------
# 读写（R2 为准）
# ------------------------------------------------------------
def _persist(db, previous_text=None):
  """写本地副本 + R2（先备份上一版）。返回 (ok, err)；R2 未连接时 (True, "offline")。"""
  _save_local(db)
  if previous_text:
    freg.put_text(USER_DB_BACKUP_KEY, previous_text)  # 备份失败不影响主流程
  return freg.put_text(USER_DB_KEY, json.dumps(db, ensure_ascii=False, indent=2))


def load_user_db():
  """读取用户库。读不到（非“不存在”）时抛出 UserDBUnavailable，绝不覆盖云端数据。"""
  status, text = freg.get_text(USER_DB_KEY)

  if status == "ok":
    try:
      db = json.loads(text)
    except Exception as exc:  # noqa: BLE001
      # 主文件损坏：尝试用上一版备份，且不覆盖损坏文件（留给人工检查）
      bstatus, btext = freg.get_text(USER_DB_BACKUP_KEY)
      if bstatus == "ok":
        try:
          db, _ = _normalize_db(json.loads(btext))
          st.session_state["_user_db_notice"] = "云端用户库文件损坏，已临时使用上一版备份登录。"
          return db
        except Exception:  # noqa: BLE001
          pass
      raise UserDBUnavailable(f"云端用户库内容损坏：{exc}") from exc
    db, changed = _normalize_db(db)
    if changed:  # 一次性把旧明文密码加密并写回
      ok, err = _persist(db, previous_text=text)
      if not ok:
        raise UserDBUnavailable(f"升级用户库时写入失败：{err}")
    else:
      _save_local(db)
    return db

  if status == "missing":
    db, _ = _normalize_db(_bootstrap_db())
    ok, err = _persist(db)
    if not ok:
      raise UserDBUnavailable(f"初始化云端用户库失败：{err}")
    return db

  if status == "offline":  # 本地开发：没有配置 R2
    db = _load_local()
    db, changed = _normalize_db(db if db else _bootstrap_db())
    _save_local(db)
    return db

  raise UserDBUnavailable(text or "读取云端用户库失败")


def save_user_db(db_data=None):
  """兼容旧调用：把给定（或当前会话中的）用户库写入 R2。返回 (ok, err)。"""
  if db_data is None:
    db_data = st.session_state["user_db"]
  return _persist(db_data)


def _mutate_user_db(op):
  """读云端最新 -> 修改 -> 写回 R2 成功后更新会话。返回 (ok, 提示文字)。"""
  status, text = freg.get_text(USER_DB_KEY)
  if status == "ok":
    try:
      db, _ = _normalize_db(json.loads(text))
    except Exception as exc:  # noqa: BLE001
      return False, f"云端用户库内容损坏，已停止修改：{exc}"
  elif status == "offline":
    db = copy.deepcopy(st.session_state["user_db"])
    text = None
  else:
    return False, f"无法读取云端用户库，已停止修改：{text or status}"

  ok, msg = op(db)
  if not ok:
    return False, msg
  sok, serr = _persist(db, previous_text=text)
  if not sok:
    return False, f"写入云端用户库失败，修改未生效：{serr}"
  st.session_state["user_db"] = db
  if serr == "offline":
    msg += "（R2 未连接，仅保存在本地，重启后会丢失）"
  return True, msg


# ------------------------------------------------------------
# 具体操作
# ------------------------------------------------------------
def change_own_password(username, new_pwd):
  ok, msg = validate_password(new_pwd)
  if not ok:
    return False, msg

  def op(db):
    users = db["credentials"]["usernames"]
    if username not in users:
      return False, "当前账号不存在。"
    users[username]["password"] = hash_password(new_pwd)
    return True, "✅ 个人密码重置成功，下次登录生效！"

  return _mutate_user_db(op)


def update_user(target_u, new_u, disp_name, new_pwd, facs, current_username):
  new_u = (new_u or "").strip()
  if not new_u:
    return False, "登录账号不能为空！"
  if new_pwd:
    ok, msg = validate_password(new_pwd)
    if not ok:
      return False, msg
  if new_u != target_u and target_u == current_username:
    return False, "不能修改当前登录账号自己的登录名，请换其他管理员账号操作。"

  def op(db):
    users = db["credentials"]["usernames"]
    if target_u not in users:
      return False, f"用户【{target_u}】已不存在（可能已被其他管理员删除），请刷新用户库。"
    if new_u != target_u and new_u in users:
      return False, f"登录账号【{new_u}】已被占用！"
    old = users[target_u]
    updated = {
        "name": (disp_name or "").strip() or new_u,
        "password": hash_password(new_pwd) if new_pwd else old.get("password"),
        "role": old.get("role", "user"),
        "allowed_factories": "ALL" if old.get("role") == "admin" else list(facs),
    }
    if new_u != target_u:
      del users[target_u]
    users[new_u] = updated
    return True, f"用户【{new_u}】资料已成功更新并已永久保存！"

  return _mutate_user_db(op)


def create_user(new_uname, disp_name, new_pwd, facs):
  new_uname = (new_uname or "").strip()
  if not new_uname or not new_pwd:
    return False, "账号和密码为必填项！"
  ok, msg = validate_password(new_pwd)
  if not ok:
    return False, msg

  def op(db):
    users = db["credentials"]["usernames"]
    if new_uname in users:
      return False, "该账号已存在！"
    users[new_uname] = {
        "name": (disp_name or "").strip() or new_uname,
        "password": hash_password(new_pwd),
        "role": "user",
        "allowed_factories": list(facs),
    }
    return True, f"用户账号【{new_uname}】创建成功并已永久保存！"

  return _mutate_user_db(op)


def delete_user(user_to_del, current_username):
  if user_to_del == current_username:
    return False, "不能删除当前登录的账号。"

  def op(db):
    users = db["credentials"]["usernames"]
    if user_to_del not in users:
      return False, f"账号【{user_to_del}】已不存在。"
    if users[user_to_del].get("role") == "admin":
      admins = [u for u, i in users.items() if i.get("role") == "admin"]
      if len(admins) <= 1:
        return False, "至少需要保留一个管理员账号！"
    del users[user_to_del]
    return True, f"账号【{user_to_del}】已成功删除！"

  return _mutate_user_db(op)


# ------------------------------------------------------------
# 侧边栏界面
# ------------------------------------------------------------
def _flash(kind, message):
  st.session_state["_user_flash"] = (kind, message)


def _show_flash():
  item = st.session_state.pop("_user_flash", None)
  if item:
    kind, message = item
    getattr(st.sidebar, kind, st.sidebar.info)(message)


def _using_default_password(username, info):
  """当前账号是否仍在使用默认密码（结果按密码串缓存，避免每次刷新都做 bcrypt 校验）。"""
  hashed = info.get("password", "")
  cache = st.session_state.get("_defpw_cache")
  if cache and cache[0] == (username, hashed):
    return cache[1]
  result = check_password(LEGACY_DEFAULT_PASSWORD, hashed)
  st.session_state["_defpw_cache"] = ((username, hashed), result)
  return result


def render_user_management(username, user_role, authenticator):
  """渲染侧边栏用户相关界面（个人密码修改 + 超级管理员用户管理）"""
  current_user = st.session_state["user_db"]["credentials"]["usernames"].get(
      username, {}
  )
  user_disp_name = current_user.get("name", username)

  st.sidebar.title("🔐 会话信息")
  st.sidebar.write(f"当前用户：**{user_disp_name}** (`{username}`)")
  _show_flash()

  notice = st.session_state.get("_user_db_notice")
  if notice:
    st.sidebar.warning(notice)
  if _using_default_password(username, current_user):
    st.sidebar.warning("⚠️ 您的密码仍是默认密码，请立即在下方「修改我的密码」中修改。")

  # 1. 个人密码修改
  with st.sidebar.expander("🔑 修改我的密码"):
    new_self_pwd = st.text_input(
        "新密码", type="password", key="reset_self_pwd_input"
    )
    if st.button("确认重置", key="btn_reset_self_pwd"):
      if new_self_pwd:
        ok, msg = change_own_password(username, new_self_pwd)
        if ok:
          st.success(msg)
        else:
          st.error(msg)
      else:
        st.warning("密码不能为空")

  authenticator.logout("退出登录", "sidebar")
  st.sidebar.markdown("---")

  # 2. 超级管理员：统一用户账号与资料编辑模块
  if user_role == "admin":
    with st.sidebar.expander("👥 用户账号与资料管理"):
      if st.button("🔄 从云端刷新用户库", key="btn_refresh_users", use_container_width=True):
        try:
          st.session_state["user_db"] = load_user_db()
        except UserDBUnavailable as exc:
          st.error(f"刷新失败：{exc}")
        else:
          st.rerun()

      all_factories = st.session_state.get("all_factories", [])

      st.markdown("#### ✏️ 编辑现有用户资料")
      all_users = list(
          st.session_state["user_db"]["credentials"]["usernames"].keys()
      )
      if st.session_state.get("select_u_to_edit_full") not in all_users:
        st.session_state.pop("select_u_to_edit_full", None)
      target_u = st.selectbox(
          "选择要修改的用户", all_users, key="select_u_to_edit_full"
      )
      u_info = st.session_state["user_db"]["credentials"]["usernames"][target_u]

      edit_uname = st.text_input(
          "登录账号 (Username)", value=target_u, key=f"edit_uname_{target_u}"
      )
      edit_disp_name = st.text_input(
          "人员姓名/显示名 (Name)",
          value=u_info.get("name", ""),
          key=f"edit_disp_{target_u}",
      )
      edit_pwd = st.text_input(
          "重置密码 (留空保持原样)",
          type="password",
          key=f"edit_pwd_{target_u}",
      )

      current_allowed = u_info.get("allowed_factories", [])
      if current_allowed == "ALL":
        default_selected_facs = list(all_factories)
      else:
        default_selected_facs = [f for f in current_allowed if f in all_factories]

      edit_facs = st.multiselect(
          "允许访问的工厂",
          all_factories,
          default=default_selected_facs,
          key=f"edit_facs_{target_u}",
      )

      if st.button("保存修改", key="btn_save_u_edit", use_container_width=True):
        ok, msg = update_user(
            target_u, edit_uname, edit_disp_name, edit_pwd, edit_facs, username
        )
        if ok:
          _flash("success", msg)
          st.rerun()
        else:
          st.error(msg)

      st.markdown("---")
      st.markdown("#### ➕ 创建新账号")
      new_uname = st.text_input(
          "新账号 (Username)",
          placeholder="例: taiyuan_user",
          key="new_u_name",
      )
      new_disp_name = st.text_input(
          "显示名 (Name)", placeholder="例: 太原厂长", key="new_u_disp"
      )
      new_u_pwd = st.text_input(
          "初始密码", type="password", key="new_u_pwd_input"
      )
      assigned_facs = st.multiselect(
          "授权工厂",
          all_factories,
          key="select_user_allowed_facs",
      )

      if st.button(
          "确认创建用户", key="btn_create_new_user", use_container_width=True
      ):
        ok, msg = create_user(
            new_uname,
            new_disp_name,
            new_u_pwd,
            assigned_facs if assigned_facs else list(all_factories),
        )
        if ok:
          _flash("success", msg)
          st.rerun()
        else:
          st.error(msg)

      st.markdown("---")
      st.markdown("#### 🗑️ 删除用户账号")
      _del_options = [u for u in all_users if u != username]
      if st.session_state.get("select_u_del") not in _del_options:
        st.session_state.pop("select_u_del", None)
      user_to_del = st.selectbox(
          "选择要删除的账号",
          _del_options,
          key="select_u_del",
      )
      if st.button(
          "确认删除账号", key="btn_del_user_acc", use_container_width=True
      ):
        if user_to_del:
          ok, msg = delete_user(user_to_del, username)
          if ok:
            _flash("success", msg)
            st.rerun()
          else:
            st.error(msg)
