#!/bin/bash
echo "🚀 开始更新网站..."

# 1. 添加所有修改
git add .

# 2. 提交修改 (使用当前时间作为备注)
git commit -m "Update site: $(date '+%Y-%m-%d %H:%M:%S')"

# 3. 推送到 GitHub
echo "📦 正在推送到 GitHub..."
git push origin master

echo "✅ 推送完成！Render 会在几分钟内自动更新您的网站。"
