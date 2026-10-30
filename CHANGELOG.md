# Changelog

## v0.1.0 (2026-10-30)

### New

- Initial SideQuest guild platform
- Member hub, Docker image, litestar-vite dev serving
- Link Battle.net accounts and give officers a member list
- Mobile menu, 44px targets, text panel, back-to-top
- Two-way sync between site raids and Discord scheduled events
- Guild events with kinds and repeating schedules; rotating bot status line
- Live voice channel counts and online total in the Discord band
- Discord roles for site sign-in and Battle.net link
- Answer Alex's mentions, once every four hours
- DELETE /api/me erases the member and their event sign-ups
- Guild rules, privacy and terms pages; delete account on /account/
- Gate role for members who haven't signed in on the site
- Officers confirm members on the guild roster to open the member channels
- Class halls follow role holders into their forum post; role menus in guild gold
- Discord interest on event pages and an events forum post per event
- Event forum sign-up comments @-mention the member and quote their comment
- GM console API — members, activity log, moderation cases and an officer audit trail
- Every inner page is a room of the citadel, with a GM console on the officers page
- Drop the channel list from the homepage Discord band, keep the online count
- Events carry attendance EP, preset per kind with an officer override, plus a transmog kind
- One nav on every page, sized like the homepage; the Officers link only for signed-in officers
- Event details and rosters for signed-in members only; addons say whether SideQuest made them
- Discord name, nickname, avatar and role changes reach the site; GM roster shows usernames
- New sign-ups post to officers with Approve and More info; deleting an account erases chat XP
- Voice hearths on the homepage; paintings ship as AVIF with a blur-up, and hashed assets cache for a year
- Deleting a site account strips the member's Discord roles and returns them to the gate
- Links swap the page in place instead of reloading; every page script starts and stops with its page
- New guests get a private welcome DM on sign-in, and a pinned Start here button shows it again
- Discord sign-ups, weekly board, calendar feed, away dates, recruiting, Hall of Heroes with badge roles, raid group builder, attendance report, online-now roster
- Role icons for every rank, class, gate and badge role; the bot keeps badge role icons and shows them on announcements
- A Raiding page (sign-ups, EPGP and soft-reserve loot, alts, attendance, FAQ) linked from the nav; officers console pairs line up and Recruiting uses the full width
- EPGP loot ledger and guild hub synced from the SideQuest addon: raid sessions, boss kills, loot and EP/GP standings; roster, crafters, bank log, news, announcements to Discord, recruits and in-game sign-ups; Ledger and Guild pages, officers' sync console
- Progression loot is SQL (SideQuest Loot), our EPGP plus loot council mix, with the decided rules on the raiding page; guild participation points are now Renown; GitHub link in the footer
- The homepage addons band links to the guild's addon on CurseForge and its source
- Officers can connect Claude Code or omp to the guild through an MCP endpoint
- An API page shows the API reference in the site's own style, linked from the footer
- The nav is a short bar: Events, Raids, Guild and Addons, with Raids and Guild opening one shared quest-log panel that slides between them, a Discord icon and your account chip; phones get a full-height menu
- Guild config gains forever_feed_channel_id, where the bot posts WoW: Forever news

### Fixed

- Keep link-role sync alive when the bot deploys before the API
- Stack member and series row actions on phones
- Keep the /linkroles description under Discord's 100-character limit
- Event titles, notes, raid chart and header fit phones
- An API response in the wrong shape is an APIError, so bot loops survive rolling deploys
- Events already on Discord get their forum post once the forum is set
- The phone homepage hero spans the screen again, and the sign-in plaque fits 320px phones
- Members a Quest Master approves get the New Arrival role; the bot was never told who was approved
- The events page only asks signed-out visitors to sign in; note when Cabotage skips a deploy
- The Hall of Heroes lists the whole roster and badge holders before anyone earns EP; account deletion is a red Danger Zone with an in-page confirmation that says it removes your Discord roles
- The recruiting band lays roles and classes out as even rows of three cards instead of one ragged strip
- Remove a node_modules symlink committed by mistake, which broke the image build; .gitignore now ignores node_modules links too
- The bot's Approve route confirms the notice's member by site id, not the clicking GM
- Long names in the homepage Online now roster no longer run into each other; each person's slot grows to fit, wraps, and shows the full name on hover

### Faster

- Homepage plates as AVIF, API calls start with the HTML, one /api/me per page, prerender on hover
- Pages and live counts cache at Cloudflare's edge, never carry a session cookie, and inline their CSS
- A service worker serves pages, scripts, fonts and paintings from the device and shows public data before refreshing it
