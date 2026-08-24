-- selection_info: Explorer 右键 → 打印当前选中对象（演示区域专属动作）
local sel = game:GetService("Selection"):Get()
if #sel == 0 then
    return ("[area=%s] 当前没有选中任何对象"):format(HOOK_AREA)
end
local names = {}
for i, inst in ipairs(sel) do
    if i > 10 then break end
    table.insert(names, inst.ClassName .. " '" .. inst.Name .. "'")
end
return ("[area=%s] 选中 %d 个对象: %s"):format(HOOK_AREA, #sel, table.concat(names, ", "))
