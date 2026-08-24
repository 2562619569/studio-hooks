-- camera_info: 3D 视口右键 → 打印摄像机状态（演示区域专属动作）
local cam = workspace.CurrentCamera
return ("[area=%s] camera pos=%s look=%s fov=%.1f focus=%s"):format(
    HOOK_AREA,
    tostring(cam.CFrame.Position),
    tostring(cam.CFrame.LookVector),
    cam.FieldOfView,
    tostring(cam.Focus.Position)
)
