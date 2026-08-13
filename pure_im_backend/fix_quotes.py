#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复Python文件中的中文引号"""

with open('app/routes/chat.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换所有中文引号为英文引号
content = content.replace('“', '"')  # "
content = content.replace('”', '"')  # "
content = content.replace('‘', "'")  # '
content = content.replace('’', "'")  # '

with open('app/routes/chat.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('已替换所有中文引号')