local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local AnalyticsService = game:GetService("AnalyticsService")
local HttpService = game:GetService("HttpService")
local BASE_REWARD, UPGRADE_BASE_COST, MAX_UPGRADE = 10, 100, 20
local funnelSessions = {}
local feedback = ReplicatedStorage:FindFirstChild("GameFeedback") or Instance.new("RemoteEvent")
feedback.Name, feedback.Parent = "GameFeedback", ReplicatedStorage
local function setup(player)
	if player:FindFirstChild("leaderstats") then return end
	local folder=Instance.new("Folder"); folder.Name,folder.Parent="leaderstats",player
	for _,name in ipairs({"Credits","Repairs","Upgrade"}) do local value=Instance.new("IntValue"); value.Name,value.Parent=name,folder end
	local sessionId = HttpService:GenerateGUID(false)
	funnelSessions[player] = sessionId
	pcall(function() AnalyticsService:LogFunnelStepEvent(player,"FirstSession",sessionId,1,"Joined") end)
end
Players.PlayerAdded:Connect(setup); for _,player in ipairs(Players:GetPlayers()) do setup(player) end
Players.PlayerRemoving:Connect(function(player) funnelSessions[player]=nil end)

local function logStep(player,step,name)
	local sessionId=funnelSessions[player]
	if not sessionId then return end
	pcall(function() AnalyticsService:LogFunnelStepEvent(player,"FirstSession",sessionId,step,name) end)
end
local function milestone(repairs)
	if repairs==5 then return 50,"FIRST SHIFT COMPLETE" end
	if repairs==10 then return 150,"FACTORY ONLINE" end
	if repairs>10 and repairs%10==0 then return 200,"PRODUCTION MILESTONE" end
	return 0
end
local world=workspace:WaitForChild("RepairWorld")
for _,object in ipairs(world:GetChildren()) do
	local prompt=object:FindFirstChildOfClass("ProximityPrompt")
	if prompt and string.find(object.Name,"BrokenBot_",1,true) then
		local busy=false
		prompt.Triggered:Connect(function(player)
			if busy then return end
			local stats=player:FindFirstChild("leaderstats"); if not stats then return end
			busy,prompt.Enabled,object.Color=true,false,Color3.fromRGB(84,224,143)
			local reward=BASE_REWARD*(stats.Upgrade.Value+1)
			stats.Credits.Value+=reward; stats.Repairs.Value+=1
			feedback:FireClient(player,{kind="repair",amount=reward,text="UNIT REPAIRED"})
			if stats.Repairs.Value==1 then logStep(player,2,"First Repair") end
			if stats.Repairs.Value==5 then logStep(player,3,"Five Repairs") end
			local bonus,message=milestone(stats.Repairs.Value)
			if bonus>0 then stats.Credits.Value+=bonus; feedback:FireClient(player,{kind="milestone",amount=bonus,text=message}) end
			task.delay(4,function() object.Color,prompt.Enabled,busy=Color3.fromRGB(232,88,72),true,false end)
		end)
	elseif prompt and object.Name=="UpgradeTerminal" then
		prompt.Triggered:Connect(function(player)
			local stats=player:FindFirstChild("leaderstats"); if not stats or stats.Upgrade.Value>=MAX_UPGRADE then return end
			local cost=UPGRADE_BASE_COST*(stats.Upgrade.Value+1)
			if stats.Credits.Value>=cost then
				stats.Credits.Value-=cost; stats.Upgrade.Value+=1
				if stats.Upgrade.Value==1 then logStep(player,4,"First Upgrade") end
				feedback:FireClient(player,{kind="upgrade",text="EFFICIENCY UPGRADED"})
			else feedback:FireClient(player,{kind="warning",text=string.format("NEED %d CREDITS",cost)}) end
		end)
	end
end
