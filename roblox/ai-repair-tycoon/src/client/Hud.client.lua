local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local TweenService=game:GetService("TweenService")
local player=Players.LocalPlayer
local gui=Instance.new("ScreenGui"); gui.Name,gui.ResetOnSpawn,gui.Parent="AIRepairHUD",false,player:WaitForChild("PlayerGui")
local function corner(parent,radius) local c=Instance.new("UICorner"); c.CornerRadius=UDim.new(0,radius); c.Parent=parent end
local function label(parent,pos,size,text,color,font,textSize) local x=Instance.new("TextLabel"); x.Position,x.Size,x.BackgroundTransparency,x.Text,x.TextColor3,x.TextXAlignment,x.Font,x.TextSize,x.Parent=pos,size,1,text,color,Enum.TextXAlignment.Left,font,textSize,parent; return x end
local panel=Instance.new("Frame"); panel.Size,panel.Position,panel.BackgroundColor3,panel.BackgroundTransparency,panel.Parent=UDim2.new(0,430,0,184),UDim2.fromOffset(22,22),Color3.fromRGB(7,20,15),.04,gui; corner(panel,16)
local stroke=Instance.new("UIStroke"); stroke.Color,stroke.Transparency,stroke.Parent=Color3.fromRGB(61,92,76),.25,panel
label(panel,UDim2.fromOffset(14,10),UDim2.new(1,-28,0,34),"CAPI2  /  AI REPAIR TYCOON",Color3.fromRGB(189,244,91),Enum.Font.GothamBold,19)
local objective=label(panel,UDim2.fromOffset(14,45),UDim2.new(1,-28,0,26),"",Color3.fromRGB(170,190,180),Enum.Font.GothamMedium,13)
local back=Instance.new("Frame"); back.Size,back.Position,back.BackgroundColor3,back.Parent=UDim2.new(1,-28,0,8),UDim2.fromOffset(14,76),Color3.fromRGB(31,50,41),panel; corner(back,4)
local progress=Instance.new("Frame"); progress.Size,progress.BackgroundColor3,progress.Parent=UDim2.fromScale(0,1),Color3.fromRGB(189,244,91),back; corner(progress,4)
local status=label(panel,UDim2.fromOffset(14,94),UDim2.new(1,-28,0,42),"",Color3.fromRGB(235,245,240),Enum.Font.GothamBold,16)
local nextUpgrade=label(panel,UDim2.fromOffset(14,143),UDim2.new(1,-28,0,25),"",Color3.fromRGB(125,205,169),Enum.Font.GothamMedium,13)
local hint=label(gui,UDim2.new(.5,0,1,-18),UDim2.new(0,500,0,42),"1  REPAIR RED UNIT     2  EARN CREDITS     3  UPGRADE AT GREEN TERMINAL",Color3.fromRGB(220,235,227),Enum.Font.GothamMedium,13)
hint.AnchorPoint,hint.BackgroundColor3,hint.BackgroundTransparency,hint.TextXAlignment=Vector2.new(.5,1),Color3.fromRGB(7,20,15),.12,Enum.TextXAlignment.Center; corner(hint,12)
local toast=label(gui,UDim2.fromScale(.5,.36),UDim2.fromOffset(330,64),"",Color3.fromRGB(7,20,15),Enum.Font.GothamBlack,18)
toast.AnchorPoint,toast.BackgroundColor3,toast.BackgroundTransparency,toast.TextTransparency,toast.TextXAlignment=Vector2.new(.5,.5),Color3.fromRGB(189,244,91),1,1,Enum.TextXAlignment.Center; corner(toast,14)
local stats=player:WaitForChild("leaderstats")
local function refresh()
	local c,r,u=stats.Credits.Value,stats.Repairs.Value,stats.Upgrade.Value
	status.Text=string.format("%d credits     %d repairs     efficiency x%d",c,r,u+1)
	objective.Text=r<10 and string.format("FACTORY STARTUP  ·  %d / 10 units repaired",r) or "FACTORY ONLINE  ·  Next milestone every 10 repairs"
	nextUpgrade.Text=u<20 and string.format("NEXT UPGRADE  ·  %d credits",100*(u+1)) or "MAXIMUM EFFICIENCY REACHED"
	TweenService:Create(progress,TweenInfo.new(.25),{Size=UDim2.fromScale(math.clamp(r/10,0,1),1)}):Play()
end
for _,stat in stats:GetChildren() do stat.Changed:Connect(refresh) end; stats.ChildAdded:Connect(function(stat) stat.Changed:Connect(refresh); refresh() end); refresh()
local version=0
ReplicatedStorage:WaitForChild("GameFeedback").OnClientEvent:Connect(function(data)
	version+=1; local current=version; local amount=data.amount and data.amount>0 and string.format("  +%d",data.amount) or ""
	toast.Text=tostring(data.text or "UPDATE")..amount; toast.BackgroundColor3=data.kind=="warning" and Color3.fromRGB(255,181,71) or Color3.fromRGB(189,244,91)
	TweenService:Create(toast,TweenInfo.new(.18),{BackgroundTransparency=.05,TextTransparency=0,Position=UDim2.fromScale(.5,.33)}):Play()
	task.delay(1.5,function() if current~=version then return end; TweenService:Create(toast,TweenInfo.new(.3),{BackgroundTransparency=1,TextTransparency=1,Position=UDim2.fromScale(.5,.29)}):Play() end)
end)
local camera=workspace.CurrentCamera
local function responsive() local narrow=camera and camera.ViewportSize.X<700; panel.Size=narrow and UDim2.new(1,-24,0,184) or UDim2.new(0,430,0,184); panel.Position=narrow and UDim2.fromOffset(12,12) or UDim2.fromOffset(22,22); hint.Size=narrow and UDim2.new(1,-24,0,42) or UDim2.new(0,500,0,42) end
if camera then camera:GetPropertyChangedSignal("ViewportSize"):Connect(responsive) end; responsive()
