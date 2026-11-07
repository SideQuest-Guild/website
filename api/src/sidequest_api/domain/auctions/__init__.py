"""Auction house prices synced from Battle.net: public prices, member price-watch alerts, and the bot's sync feed.

``local://auctions-contract.md`` is the source of truth. SideQuest prices items from every house of its own
faction (``AuctionsService._guild_ruleset_and_faction`` resolves the ruleset and faction from Battle.net's
``sidequest`` guild, cached, falling back to ruleset 2 / Alliance). ``AuctionsService.sync`` fetches each faction
house sequentially to bound memory, replaces that house's current prices in one transaction, rolls up today's daily
history, and queues watch alerts.
"""
