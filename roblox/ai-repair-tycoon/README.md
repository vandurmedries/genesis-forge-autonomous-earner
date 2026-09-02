# AI Repair Tycoon

A small Roblox MVP: repair broken AI units, earn credits, and buy efficiency upgrades during a play session.

## Commercial model

- Free entry to reduce acquisition friction.
- Two optional repeat purchases are live: 500 credits for 19 Robux (product `3711031876`) and 2,500 credits for 79 Robux (product `3711031899`).
- Future additions should be cosmetic or convenience-based; core play stays functional without payment.
- Never count test purchases as revenue.

## Published configuration

- Experience: `CAPI2 AI Repair Tycoon` (`10764646033`)
- Start place: `96074779850189`
- Access: public; current Roblox audience reach is limited to ages 16+ and trusted friends until the owner completes Roblox ID verification.
- `MarketplaceService.ProcessReceipt` grants the configured credits only after Roblox confirms a matching purchase.
- Credit balances currently last for the active server session; the product descriptions state this explicitly.

The purchase UI and receipt handler are enabled. No real purchase has been made by the project automation, so paid receipt delivery still needs one authorized live-purchase check. Never count that check as organic revenue.

## Private-test analytics

The `FirstSession` funnel records four successful milestones: `Joined`, `First Repair`, `Five Repairs`, and `First Upgrade`. Roblox funnel charts can take about 24 hours to populate; recent events can be inspected sooner with **View Events** in Creator Dashboard → Analytics → Funnels.
