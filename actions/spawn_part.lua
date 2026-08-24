-- spawn_part: 在摄像机前方 12 格生成一个锚定的 Part
local chs = game:GetService("ChangeHistoryService")
local recording = nil
pcall(function()
    recording = chs:TryBeginRecording("studio-hooks: spawn part", nil)
end)

local cam = workspace.CurrentCamera
local p = Instance.new("Part")
p.Name = "HookSpawnedPart"
p.Anchored = true
p.CFrame = cam.CFrame * CFrame.new(0, 0, -12)
p.Parent = workspace

pcall(function()
    if recording then
        chs:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
    else
        chs:SetWaypoint()
    end
end)

return ("spawned %s @ %s"):format(p.Name, tostring(p.CFrame.Position))
