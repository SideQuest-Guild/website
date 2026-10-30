/** Permanent Discord invite for the SideQuest server (lands in #general). Every join link reads from here. */
export const DISCORD_INVITE = "https://discord.gg/nwncP7H9Hh";

/** Discord's own app deep link into the SideQuest server, for signed-in members (skips the public invite page). */
export const DISCORD_GUILD_URL = "https://discord.com/channels/1564671275316543508";

/** The SideQuest GitHub organization: the site, the bot and the addon live here. */
export const GITHUB_URL = "https://github.com/sidequest-guild";

/** The SideQuest addon on CurseForge: the roster, crafters, raid sign-ups and loot points, opened with /sq. */
export const CURSEFORGE_URL = "https://www.curseforge.com/wow/addons/sidequest";

/** Source for the guild's own addon (the one listed on CurseForge), separate from GITHUB_URL's org page. */
export const ADDON_SOURCE_URL = "https://github.com/SideQuest-Guild/addon";

/** The guild's documentation site: setup guides and references for members, officers and developers. */
export const DOCS_URL = "https://docs.sidequest-guild.com";

/** Source for SideQuest Companion, the tray app that syncs the addon with this site. */
export const COMPANION_SOURCE_URL = "https://github.com/SideQuest-Guild/companion";

/** Companion's GitHub releases, the fallback for every download button and the page shown without JavaScript. */
export const COMPANION_RELEASES_URL = "https://github.com/SideQuest-Guild/companion/releases/latest";

/** GitHub API endpoint Companion's download page reads for the latest release's version and asset URLs. */
export const COMPANION_RELEASES_API = "https://api.github.com/repos/SideQuest-Guild/companion/releases/latest";

/** Launch day of World of Warcraft: Forever (local calendar date; the launch hour is not announced). */
export const LAUNCH = { year: 2026, month: 11, day: 4 };
