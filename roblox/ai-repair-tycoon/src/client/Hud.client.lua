local Players = game:GetService("Players")
local player = Players.LocalPlayer

local gui = Instance.new("ScreenGui")
gui.Name = "AIRepairHUD"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(370, 112)
panel.Position = UDim2.fromOffset(24, 24)
panel.BackgroundColor3 = Color3.fromRGB(8, 22, 17)
panel.BackgroundTransparency = 0.08
panel.Parent = gui
Instance.new("UICorner", panel).CornerRadius = UDim.new(0, 14)

local title = Instance.new("TextLabel")
title.Size = UDim2.new(1, -28, 0, 42)
title.Position = UDim2.fromOffset(14, 10)
title.BackgroundTransparency = 1
title.Text = "CAPI2 · AI REPAIR TYCOON"
title.TextColor3 = Color3.fromRGB(189, 244, 91)
title.TextXAlignment = Enum.TextXAlignment.Left
title.Font = Enum.Font.GothamBold
title.TextSize = 20
title.Parent = panel

local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, -28, 0, 48)
status.Position = UDim2.fromOffset(14, 52)
status.BackgroundTransparency = 1
status.TextColor3 = Color3.fromRGB(232, 242, 237)
status.TextXAlignment = Enum.TextXAlignment.Left
status.Font = Enum.Font.Gotham
status.TextSize = 16
status.Parent = panel

local stats = player:WaitForChild("leaderstats")
local function refresh()
    status.Text = string.format("Credits: %d   Repairs: %d   Efficiency: x%d", stats.Credits.Value, stats.Repairs.Value, stats.Upgrade.Value + 1)
end
for _, stat in stats:GetChildren() do stat.Changed:Connect(refresh) end
stats.ChildAdded:Connect(function(stat) stat.Changed:Connect(refresh); refresh() end)
refresh()
