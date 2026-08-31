# AI Repair Tycoon

A small Roblox MVP: repair broken AI units, earn credits, buy efficiency upgrades, and return to progress further.

## Commercial model

- Free entry to reduce acquisition friction.
- Two optional repeat purchases: 500 and 2,500 credits.
- Future additions should be cosmetic or convenience-based; core play stays functional without payment.
- Never count test purchases as revenue.

## Publish

1. Install Roblox Studio and Rojo.
2. Create a new Roblox experience owned by the intended user or studio group.
3. Create two Developer Products in Creator Dashboard.
4. Put their numeric IDs in `src/shared/Config.lua`.
5. Run `rojo serve` in this folder and connect through the Studio Rojo plugin.
6. Enable Studio access to API services only in a test universe, test receipts, then publish.

The purchase handler uses `MarketplaceService.ProcessReceipt`; product IDs remain disabled (`0`) until explicitly configured.
