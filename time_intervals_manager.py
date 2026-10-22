# -*- coding: utf-8 -*-
"""模块四：运行时间段方案管理（每个工厂独立存储、互不串用）

隔离方式：
  - 当前工厂取自 st.session_state["selected_factory"]（由 app.py 在每次运行时设置），
    不再依赖全局的 "uploaded_vault" 软链接（它是整个服务器共用的，切换工厂时会串）。
  - R2 中的存放位置：device-monitor/<工厂>/templates_vault.json 与 trash_vault.json，
    使用完整 Key 读写，与 r2_storage.BASE_PREFIX 这个全局变量无关。
  - 切换工厂时，页面里的方案、已选时段、回收站、图表缓存全部清空并按新工厂重新加载。
  - 新工厂没有任何方案时显示为空，不带入任何预设时段。
"""
import os
import json
import logging
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import factory_registry as freg
import data_processor

TEMPLATES_FILE_NAME = "templates_vault.json"
TRASH_FILE_NAME = "trash_vault.json"


def default_templates():
    # 新工厂默认返回空方案，不再写死测试数据，防止新工厂带入旧测试时段
    return {}


def _scope(vault_dir):
    """返回 (当前工厂名或None, 该工厂的本地目录)。"""
    factory = st.session_state.get("selected_factory")
    if factory:
        local_dir = f"uploaded_vault_{factory}"
    else:
        # 兜底：没有工厂信息时，解析软链接得到真实目录，至少让目录变化可被识别
        local_dir = os.path.realpath(vault_dir)
        factory = None
    os.makedirs(local_dir, exist_ok=True)
    return factory, local_dir


def _scope_id(vault_dir):
    factory, local_dir = _scope(vault_dir)
    return factory or local_dir


def _read_json(vault_dir, file_name):
    """读取方案文件：优先 R2（本工厂目录），其次本工厂本地文件。读不到返回 None。"""
    factory, local_dir = _scope(vault_dir)
    if factory:
        prefix = freg.factory_prefix(factory)
        candidates = [
            f"{prefix}{file_name}",
            # 兼容旧版本曾经使用过的存放位置（仍然在本工厂目录之内）
            f"{prefix}uploaded_vault_{factory}/{file_name}",
            f"{prefix}uploaded_vault/{file_name}",
        ]
        for key in candidates:
            status, text = freg.get_text(key)
            if status == "ok":
                try:
                    data = json.loads(text)
                except Exception:
                    logging.exception("R2 中的 %s 内容损坏", key)
                    continue
                if key != candidates[0]:
                    # 旧版本把它存在了别的位置：补一份到统一位置（旧文件原样保留，不删除）
                    freg.put_text(candidates[0], text)
                return data
            elif status in ("error", "offline"):
                break
    path = os.path.join(local_dir, file_name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            logging.exception("读取本地 %s 失败", path)
    return None


def _write_json(vault_dir, file_name, data):
    """写本工厂本地文件，并用完整 Key 同步到 R2。返回是否完全成功。"""
    factory, local_dir = _scope(vault_dir)
    text = json.dumps(data, ensure_ascii=False, indent=4)
    try:
        with open(os.path.join(local_dir, file_name), "w", encoding="utf-8") as file:
            file.write(text)
    except Exception as exc:
        st.error(f"保存到本地失败：{exc}")
        return False
    if factory:
        ok, err = freg.put_text(f"{freg.factory_prefix(factory)}{file_name}", text)
        if not ok:
            st.warning(f"已保存到本地，但同步到 R2 失败：{err}")
            return False
    return True


def load_persistent_templates(vault_dir):
    data = _read_json(vault_dir, TEMPLATES_FILE_NAME)
    if isinstance(data, dict):
        normalized_data = {}
        idx = 1
        for k, v in data.items():
            key_name = k if k.startswith("监测数据时间段") else f"监测数据时间段{idx}"
            normalized_data[key_name] = v
            idx += 1
        return normalized_data
    return default_templates()


def save_persistent_templates(templates, vault_dir):
    ok = _write_json(vault_dir, TEMPLATES_FILE_NAME, templates)
    if not ok:
        st.error("保存时段方案未能完全成功，请查看上方提示。")
    return ok


def load_trash_bin(vault_dir):
    data = _read_json(vault_dir, TRASH_FILE_NAME)
    return data if isinstance(data, dict) else {}


def save_trash_bin(trash, vault_dir):
    return _write_json(vault_dir, TRASH_FILE_NAME, trash)


_DT_UNITS = [("年", 4), ("月", 2), ("日", 2), ("时", 2), ("分", 2), ("秒", 2)]

_DT_ROW_CSS = """
<style>
/* 一行紧凑输入：年 月 日 时 分 秒，手机上也不换行 */
.st-key-dt_inputs_box [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.2rem !important; align-items: center; }
.st-key-dt_inputs_box [data-testid="stColumn"], .st-key-dt_inputs_box [data-testid="column"] { min-width: 0 !important; }
.st-key-dt_inputs_box input { padding: 0.35rem 0.15rem !important; text-align: center; }
.st-key-dt_inputs_box [data-testid="stMarkdownContainer"] p { margin: 0; text-align: center; white-space: nowrap; }
</style>
"""

# 输入满位数后自动跳到下一格（只是锦上添花；脚本失败时不影响使用，按 Tab 键同样可以切换）
_DT_AUTOJUMP_JS = """
<script>
(function () {
  try {
    const doc = window.parent.document;
    function setup() {
      const box = doc.querySelector('.st-key-dt_inputs_box');
      if (!box) return;
      const inputs = Array.from(box.querySelectorAll('input[type="text"]'));
      inputs.forEach(function (el, i) {
        if (el.dataset.autojump) return;
        el.dataset.autojump = '1';
        el.addEventListener('focus', function () { el.select(); });
        el.addEventListener('input', function () {
          const max = parseInt(el.getAttribute('maxlength') || '0', 10);
          if (max && el.value.length >= max && inputs[i + 1]) { inputs[i + 1].focus(); }
        });
      });
    }
    setup();
    new MutationObserver(setup).observe(doc.body, { childList: true, subtree: true });
  } catch (e) {}
})();
</script>
"""


def _dt_row(label, default_dt, key_prefix):
    """渲染一行：开始/结束：[2026]年[08]月[01]日[01]时[01]分[00]秒；返回六个格子里的文字。"""
    widths = [1.0] + [1.7, 0.5] + [1.0, 0.5] * 5
    cols = st.columns(widths)
    cols[0].markdown(f"**{label}：**")
    values = []
    parts = [default_dt.year, default_dt.month, default_dt.day,
             default_dt.hour, default_dt.minute, default_dt.second]
    for i, ((unit, max_chars), part) in enumerate(zip(_DT_UNITS, parts)):
        with cols[1 + 2 * i]:
            values.append(st.text_input(
                unit, value=f"{part:0{max_chars}d}", max_chars=max_chars,
                key=f"{key_prefix}_{unit}", label_visibility="collapsed",
            ))
        cols[2 + 2 * i].markdown(unit)
    return values


def _fields_to_datetime(values, name):
    """把六个格子的文字变成 datetime；时/分/秒留空按 0 处理。"""
    year, month, day, hour, minute, second = [str(v).strip() for v in values]
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        raise ValueError(f"{name}的年、月、日必须填写数字")
    for unit, text in (("时", hour), ("分", minute), ("秒", second)):
        if text and not text.isdigit():
            raise ValueError(f"{name}的{unit}必须是数字")
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        raise ValueError(f"{name}不是有效的日期时间（请检查：月 1-12、该月是否有这一天、时 0-23、分和秒 0-59）")


def render_time_intervals_manager(vault_dir, df_raw, time_col):
    """渲染时间段方案选择、编辑、回收站及新增时段的完整交互逻辑"""
    
    # 切换工厂时：清空上一个工厂留在页面里的一切，再按新工厂重新加载
    scope_id = _scope_id(vault_dir)
    if st.session_state.get("_intervals_scope") != scope_id:
        st.session_state["_intervals_scope"] = scope_id
        st.session_state.saved_templates = load_persistent_templates(vault_dir)
        st.session_state.trash_bin = load_trash_bin(vault_dir)
        st.session_state.intervals = []
        for stale_key in (
            "current_scheme_name", "plotted_fig_bytes", "intervals_editor",
            "s_date", "s_h", "s_m", "s_s", "e_date", "e_h", "e_m", "e_s",
        ):
            st.session_state.pop(stale_key, None)

    if "saved_templates" not in st.session_state:
        st.session_state.saved_templates = load_persistent_templates(vault_dir)
    if "trash_bin" not in st.session_state:
        st.session_state.trash_bin = load_trash_bin(vault_dir)
    if "intervals" not in st.session_state:
        st.session_state.intervals = []

    st.markdown("### 4. 机组运行数据时间段选择 <span style='color:red; font-size:18px;'>（必选）</span>", unsafe_allow_html=True)
    _cur_factory = st.session_state.get("selected_factory")
    if _cur_factory:
        st.caption(f"当前工厂：{_cur_factory}（以下时间段方案只属于该工厂，与其他工厂互不影响）")

    template_options = {}
    for name, intervals_list in st.session_state.saved_templates.items():
        if intervals_list and isinstance(intervals_list, list):
            try:
                first_start_date = str(intervals_list[0].get("start", "")).split()[0]
                last_end_date = str(intervals_list[-1].get("end", "")).split()[0]
                label = f"{name} ({first_start_date} ~ {last_end_date})"
            except Exception:
                label = f"{name} (时段解析异常)"
        else:
            label = f"{name} (无有效时段)"
        template_options[label] = name

    if template_options:
        options_list = list(template_options.keys())
        for opt_label in options_list:
            actual_key = template_options[opt_label]
            sc1, sc2, sc3 = st.columns([5, 1, 1])
            with sc1:
                st.markdown(f"📌 **{opt_label}**")
            with sc2:
                if st.button("确认选择", key=f"select_{actual_key}", use_container_width=True):
                    st.session_state.intervals = [
                        dict(item) for item in st.session_state.saved_templates[actual_key]
                    ]
                    st.session_state["current_scheme_name"] = opt_label
                    st.success(f"已成功加载：{actual_key}")
                    st.rerun()
            with sc3:
                if st.button("删除", key=f"delete_{actual_key}", use_container_width=True):
                    st.session_state.trash_bin[actual_key] = st.session_state.saved_templates[actual_key]
                    save_trash_bin(st.session_state.trash_bin, vault_dir)
                    del st.session_state.saved_templates[actual_key]
                    save_persistent_templates(st.session_state.saved_templates, vault_dir)
                    st.success(f"已将 {actual_key} 移入回收站。")
                    st.rerun()
    else:
        st.info("当前工厂暂无保存的时间段方案，请在下方直接添加。")

    if st.session_state.trash_bin:
        with st.expander("🗑️ 回收站（防止误删除）", expanded=False):
            st.write("以下是被删除的时间段方案，您可以选择恢复或彻底删除：")
            trash_options = list(st.session_state.trash_bin.keys())
            for trash_name in trash_options:
                trash_intervals = st.session_state.trash_bin[trash_name]
                first_s = trash_intervals[0].get("start", "") if trash_intervals else ""
                last_e = trash_intervals[-1].get("end", "") if trash_intervals else ""
                
                tc1, tc2, tc3 = st.columns([4, 1, 1])
                with tc1:
                    st.text(f"{trash_name} ({first_s} ~ {last_e})")
                with tc2:
                    if st.button("♻️ 恢复", key=f"restore_{trash_name}", use_container_width=True):
                        st.session_state.saved_templates[trash_name] = trash_intervals
                        save_persistent_templates(st.session_state.saved_templates, vault_dir)
                        del st.session_state.trash_bin[trash_name]
                        save_trash_bin(st.session_state.trash_bin, vault_dir)
                        st.success(f"已恢复方案：{trash_name}")
                        st.rerun()
                with tc3:
                    if st.button("🔥 彻底删除", key=f"perma_del_{trash_name}", use_container_width=True):
                        del st.session_state.trash_bin[trash_name]
                        save_trash_bin(st.session_state.trash_bin, vault_dir)
                        st.success(f"已彻底删除方案：{trash_name}")
                        st.rerun()

    st.markdown("---")

    if st.session_state.intervals:
        st.write("当前已选择的时间段（双击数值可以直接修改）。勾选“选择”后，可上移/下移或删除：")
        table_data = []
        for idx, item in enumerate(st.session_state.intervals):
            table_data.append({
                "选择": False,
                "序号": idx + 1,
                "开始时间": item["start"],
                "结束时间": item["end"],
                "多频集速运行(s)": item.get("run_sec", "0"),
                "多频集速停止(s)": item.get("stop_sec", "-"),
                "备注": item.get("remark", ""),
            })

        df_intervals = pd.DataFrame(table_data)
        edited_df = st.data_editor(
            df_intervals,
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", required=True),
                "序号": st.column_config.NumberColumn("序号", disabled=True),
            },
            disabled=["序号"],
            hide_index=True,
            use_container_width=True,
            key="intervals_editor"
        )

        bcol1, bcol2, bcol3, bcol4, bcol5, bcol6 = st.columns(6)

        with bcol1:
            if st.button("💾 保存修改", use_container_width=True):
                try:
                    new_intervals = []
                    for _, row in edited_df.iterrows():
                        s_str = str(row["开始时间"]).strip()
                        e_str = str(row["结束时间"]).strip()
                        pd.to_datetime(s_str)
                        pd.to_datetime(e_str)
                        new_intervals.append({
                            "start": s_str,
                            "end": e_str,
                            "run_sec": str(row["多频集速运行(s)"]).strip() or "0",
                            "stop_sec": str(row["多频集速停止(s)"]).strip() or "-",
                            "remark": str(row.get("备注", "")).strip(),
                        })
                    st.session_state.intervals = new_intervals
                    st.success("修改已成功保存！")
                    st.rerun()
                except Exception as ex:
                    st.error(f"保存失败，请检查时间格式是否正确: {ex}")

        with bcol2:
            if st.button("💾 另存为新方案", use_container_width=True):
                if not st.session_state.intervals:
                    st.warning("当前没有时段，无法保存。")
                else:
                    existing_nums = []
                    for k in st.session_state.saved_templates.keys():
                        if k.startswith("监测数据时间段"):
                            try:
                                num = int(k.replace("监测数据时间段", ""))
                                existing_nums.append(num)
                            except ValueError:
                                pass
                    next_num = max(existing_nums) + 1 if existing_nums else 1
                    new_name = f"监测数据时间段{next_num}"
                    
                    st.session_state.saved_templates[new_name] = [
                        dict(item) for item in st.session_state.intervals
                    ]
                    
                    f_date = st.session_state.intervals[0].get("start", "").split()[0]
                    l_date = st.session_state.intervals[-1].get("end", "").split()[0]
                    st.session_state["current_scheme_name"] = f"{new_name} ({f_date} ~ {l_date})"
                    
                    if save_persistent_templates(st.session_state.saved_templates, vault_dir):
                        st.success(f"已成功保存为“{new_name}”！")
                        st.rerun()

        with bcol3:
            if st.button("⬆️ 上移", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要上移的时段！")
                elif len(selected_indices) > 1:
                    st.warning("每次只能上移一个时段！")
                else:
                    idx = selected_indices[0]
                    if idx == 0:
                        st.info("已经是第一个时段，无法上移。")
                    else:
                        st.session_state.intervals[idx], st.session_state.intervals[idx - 1] = (
                            st.session_state.intervals[idx - 1],
                            st.session_state.intervals[idx],
                        )
                        st.rerun()

        with bcol4:
            if st.button("⬇️ 下移", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要下移的时段！")
                elif len(selected_indices) > 1:
                    st.warning("每次只能下移一个时段！")
                else:
                    idx = selected_indices[0]
                    if idx == len(st.session_state.intervals) - 1:
                        st.info("已经是最后一个时段，无法下移。")
                    else:
                        st.session_state.intervals[idx], st.session_state.intervals[idx + 1] = (
                            st.session_state.intervals[idx + 1],
                            st.session_state.intervals[idx],
                        )
                        st.rerun()

        with bcol5:
            if st.button("❌ 删除", use_container_width=True):
                selected_indices = edited_df.index[edited_df["选择"] == True].tolist()
                if not selected_indices:
                    st.warning("请先勾选要删除的时段！")
                else:
                    for idx in sorted(selected_indices, reverse=True):
                        st.session_state.intervals.pop(idx)
                    if not st.session_state.intervals:
                        st.session_state.pop("plotted_fig_bytes", None)
                    st.success("已删除选中时段！")
                    st.rerun()

        with bcol6:
            if st.button("🗑️ 清空", use_container_width=True):
                st.session_state.intervals = []
                st.session_state.pop("plotted_fig_bytes", None)
                st.success("已清空所有时段！")
                st.rerun()

        st.markdown("---")

    default_start = datetime.now()
    if st.session_state.intervals:
        try:
            default_start = pd.to_datetime(st.session_state.intervals[-1]["end"]).to_pydatetime()
        except Exception:
            pass
    else:
        try:
            parsed = data_processor.parse_datetime_series(df_raw[time_col])
            earliest = parsed.min()
            if pd.notna(earliest):
                default_start = earliest.to_pydatetime()
        except Exception:
            pass

    default_end = default_start + timedelta(minutes=50)

    # 运行/停止秒数的默认值：沿用本工厂上一个时段的设置，没有则留空（不再写死）
    _last = st.session_state.intervals[-1] if st.session_state.intervals else {}
    _default_run = "" if _last.get("run_sec") in (None, "0") else str(_last.get("run_sec", ""))
    _default_stop = "" if _last.get("stop_sec") in (None, "-") else str(_last.get("stop_sec", ""))

    with st.container(border=True):
        st.markdown("➕ **添加新时段**（自动智能衔接，支持秒级精准配置）")
        _n_iv = len(st.session_state.intervals)
        _sid = _scope_id(vault_dir)
        st.markdown(_DT_ROW_CSS, unsafe_allow_html=True)
        with st.form("interval_form"):
            try:
                _dt_box = st.container(key="dt_inputs_box")
            except TypeError:  # 旧版 Streamlit 不支持 key：功能照常，只是不应用紧凑样式
                _dt_box = st.container()
            with _dt_box:
                start_fields = _dt_row("开始", default_start, f"s_{_sid}_{_n_iv}")
                end_fields = _dt_row("结束", default_end, f"e_{_sid}_{_n_iv}")

            run_col, stop_col, remark_col, btn_col = st.columns([1.8, 1.8, 2.2, 1.2])
            with run_col:
                run_seconds = st.text_input("多频集速运行秒数（填 0 表示多频集速没有运行）", value=_default_run, key=f"run_sec_in_{_sid}_{_n_iv}")
            with stop_col:
                stop_seconds = st.text_input("停止秒数（运行秒数若为0，此项不用填）", value=_default_stop, key=f"stop_sec_in_{_sid}_{_n_iv}")
            with remark_col:
                remark_input = st.text_input("备注（可选，例如：喷吹0.3秒，间隔2分钟）", value="", key=f"remark_in_{_sid}_{_n_iv}")
            with btn_col:
                st.write("")
                add_interval = st.form_submit_button("添加时段", use_container_width=True)

            if add_interval:
                try:
                    start_dt = _fields_to_datetime(start_fields, "开始时间")
                    end_dt = _fields_to_datetime(end_fields, "结束时间")

                    if start_dt >= end_dt:
                        st.error("开始时间必须早于结束时间！")
                    else:
                        start_string = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                        end_string = end_dt.strftime("%Y-%m-%d %H:%M:%S")
                        run_text = run_seconds.strip() or "0"
                        stop_text = "-" if run_text in ("0", "0.0") else (stop_seconds.strip() or "-")
                        remark_text = remark_input.strip()
                        st.session_state.intervals.append({
                            "start": start_string,
                            "end": end_string,
                            "run_sec": run_text,
                            "stop_sec": stop_text,
                            "remark": remark_text,
                        })
                        st.success("时段添加成功！")
                        st.rerun()
                except Exception as exc:
                    st.error(f"时间格式错误：{exc}")
        components.html(_DT_AUTOJUMP_JS, height=0)

    st.markdown("---")
