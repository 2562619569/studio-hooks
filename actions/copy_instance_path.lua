-- copy_instance_path: Explorer 右键 → 复制选中实例的完整路径到系统剪贴板。
-- Luau 沙箱没有剪贴板 API：这里只计算 FullName（多选时每行一个），
-- 由 launcher 把返回文本写入 Windows 剪贴板。
local sel = game:GetService("Selection"):Get()
if #sel == 0 then
    return "(no selection)"
end
local lines = {}
for _, inst in ipairs(sel) do
    table.insert(lines, inst:GetFullName())
end
return table.concat(lines, "\n")
