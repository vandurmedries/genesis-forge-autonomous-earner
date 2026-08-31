local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local MarketplaceService = game:GetService("MarketplaceService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local store = DataStoreService:GetDataStore(Config.DataStoreName)

local function key(player)
    return "player_" .. player.UserId
end

local function loadPlayer(player)
    local data = {credits = 0, upgrade = 0, repairs = 0}
    local ok, saved = pcall(function() return store:GetAsync(key(player)) end)
    if ok and type(saved) == "table" then
        data.credits = tonumber(saved.credits) or 0
        data.upgrade = math.clamp(tonumber(saved.upgrade) or 0, 0, Config.MaxUpgrade)
        data.repairs = tonumber(saved.repairs) or 0
    end

    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"
    stats.Parent = player
    for name, value in pairs({Credits = data.credits, Repairs = data.repairs, Upgrade = data.upgrade}) do
        local stat = Instance.new("IntValue")
        stat.Name = name
        stat.Value = value
        stat.Parent = stats
    end
end

local function savePlayer(player)
    local stats = player:FindFirstChild("leaderstats")
    if not stats then return end
    pcall(function()
        store:UpdateAsync(key(player), function()
            return {credits = stats.Credits.Value, repairs = stats.Repairs.Value, upgrade = stats.Upgrade.Value}
        end)
    end)
end

Players.PlayerAdded:Connect(loadPlayer)
Players.PlayerRemoving:Connect(savePlayer)
game:BindToClose(function()
    for _, player in Players:GetPlayers() do savePlayer(player) end
end)

local world = Instance.new("Folder")
world.Name = "RepairWorld"
world.Parent = workspace

local floor = Instance.new("Part")
floor.Name = "FactoryFloor"
floor.Size = Vector3.new(90, 1, 90)
floor.Position = Vector3.new(0, -0.5, 0)
floor.Anchored = true
floor.Color = Color3.fromRGB(16, 31, 25)
floor.Parent = world

local function createStation(index, position)
    local bot = Instance.new("Part")
    bot.Name = "BrokenBot_" .. index
    bot.Size = Vector3.new(5, 5, 5)
    bot.Position = position
    bot.Anchored = true
    bot.Material = Enum.Material.Metal
    bot.Color = Color3.fromRGB(232, 88, 72)
    bot.Parent = world

    local prompt = Instance.new("ProximityPrompt")
    prompt.ActionText = "Repair bot"
    prompt.ObjectText = "Faulty AI unit"
    prompt.HoldDuration = Config.RepairSeconds
    prompt.MaxActivationDistance = 12
    prompt.Parent = bot

    local busy = false
    prompt.Triggered:Connect(function(player)
        if busy then return end
        local stats = player:FindFirstChild("leaderstats")
        if not stats then return end
        busy = true
        prompt.Enabled = false
        bot.Color = Color3.fromRGB(84, 224, 143)
        local reward = Config.BaseReward * (1 + stats.Upgrade.Value)
        stats.Credits.Value += reward
        stats.Repairs.Value += 1
        task.delay(4, function()
            bot.Color = Color3.fromRGB(232, 88, 72)
            prompt.Enabled = true
            busy = false
        end)
    end)
end

for i = 1, 8 do
    local angle = (i / 8) * math.pi * 2
    createStation(i, Vector3.new(math.cos(angle) * 28, 2.5, math.sin(angle) * 28))
end

local upgrade = Instance.new("Part")
upgrade.Name = "UpgradeTerminal"
upgrade.Size = Vector3.new(8, 4, 8)
upgrade.Position = Vector3.new(0, 2, 0)
upgrade.Anchored = true
upgrade.Color = Color3.fromRGB(189, 244, 91)
upgrade.Parent = world
local upgradePrompt = Instance.new("ProximityPrompt")
upgradePrompt.ActionText = "Buy efficiency upgrade"
upgradePrompt.ObjectText = "Central terminal"
upgradePrompt.Parent = upgrade
upgradePrompt.Triggered:Connect(function(player)
    local stats = player:FindFirstChild("leaderstats")
    if not stats or stats.Upgrade.Value >= Config.MaxUpgrade then return end
    local cost = Config.UpgradeBaseCost * (stats.Upgrade.Value + 1)
    if stats.Credits.Value >= cost then
        stats.Credits.Value -= cost
        stats.Upgrade.Value += 1
    end
end)

local productRewards = {}
for productName, productId in pairs(Config.DeveloperProducts) do
    if productId > 0 then productRewards[productId] = Config.ProductRewards[productName] end
end

MarketplaceService.ProcessReceipt = function(receipt)
    local player = Players:GetPlayerByUserId(receipt.PlayerId)
    local reward = productRewards[receipt.ProductId]
    if not player or not reward then return Enum.ProductPurchaseDecision.NotProcessedYet end
    local stats = player:FindFirstChild("leaderstats")
    if not stats then return Enum.ProductPurchaseDecision.NotProcessedYet end
    stats.Credits.Value += reward
    savePlayer(player)
    return Enum.ProductPurchaseDecision.PurchaseGranted
end
