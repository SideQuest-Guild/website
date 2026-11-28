"""The guild market report: what to gather and what to craft for gold on the guild's auction house.

A price feed (``POST /api/market/feed``, its own ``X-Market-Key``) replaces one house's item numbers and recipes.
``report.py`` turns them into a daily or weekly report (``GET /api/market/report`` for members, and the bot's
``/api/guilds/{guild_id}/market-report`` for its daily post). ``gathering.py`` says which profession gathers each
material, at what skill, and where.
"""
