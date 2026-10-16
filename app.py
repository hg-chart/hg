# -*- coding: utf-8 -*-
"""Cloudflare R2 专职一键迁移工具"""
import streamlit as st
import r2_storage

st.set_page_config(page_title="R2 数据一键迁移工具", layout="centered")

st.title("📦 R2 存储桶数据一键迁移工具")
st.markdown("---")
st.write("点击下方按钮，系统将自动把根目录 `device-monitor/` 下的旧文件（如 `uploaded_vault/`、`chart_history/`）完整迁移到新爹文件夹 **`shanxihg`** 下。")

if st.button("🚀 开始执行一键迁移", type="primary"):
    client = r2_storage._get_r2_client()
    if client is None:
        st.error("❌ Cloudflare R2 尚未连接成功，请检查 secrets.toml 配置。")
    else:
        bucket = r2_storage._r2_bucket()
        old_base = "device-monitor/"
        new_base = "device-monitor/shanxihg/"
        
        with st.spinner("正在扫描并迁移文件，请稍候..."):
            try:
                # 1. 获取所有对象
                paginator = client.get_paginator("list_objects_v2")
                moved_count = 0
                
                for page in paginator.paginate(Bucket=bucket, Prefix=old_base):
                    for obj in page.get("Contents", []):
                        old_key = obj["Key"]
                        
                        # 如果已经是新爹文件夹下的文件，或者本身是目录，则跳过
                        if old_key.startswith(new_base) or old_key == old_base:
                            continue
                        
                        # 计算相对路径
                        relative_path = old_key[len(old_base):]
                        if not relative_path:
                            continue
                            
                        new_key = f"{new_base}{relative_path}"
                        
                        # 2. 复制到新路径
                        client.copy_object(
                            Bucket=bucket,
                            CopySource={"Bucket": bucket, "Key": old_key},
                            Key=new_key
                        )
                        # 3. 删除旧路径的原文件
                        client.delete_object(Bucket=bucket, Key=old_key)
                        moved_count += 1
                
                st.success(f"🎉 迁移成功！共计成功搬移了 {moved_count} 个文件到 `device-monitor/shanxihg/` 目录下！")
                st.balloons()
                st.info("现在你可以去 Cloudflare R2 后台刷新查看效果，确认无误后，即可将你备份的业务 `app.py` 替换回来。")
                
            except Exception as exc:
                st.error(f"❌ 迁移过程中发生错误：{exc}")

st.markdown("---")
st.caption("提示：迁移完成后请及时替换回原有的业务系统代码。")
