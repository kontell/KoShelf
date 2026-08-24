"""One-shot migrations from earlier versions and from the old add-on id.

Both the plugin and the service call run_migrations() early, because either
can be the first to start after an upgrade and neither can assume the other
already ran.

Everything here is idempotent and fails quietly: a migration that raises on a
box it was never going to help is worse than one that does nothing.
"""

import json
import os
import shutil
import xml.etree.ElementTree as ElementTree

import xbmc
import xbmcvfs

# The add-on was called Koshelf until 1.0.0. Kodi treats a changed id as a
# different add-on, so none of the user's data comes across on its own.
LEGACY_ADDON_ID = "plugin.audio.koshelf"

# Settings worth carrying over from the old profile. Deliberately a list and
# not "everything in the file": the old profile has ids this build no longer
# has, and setSetting on an unknown id is ignored anyway.
CARRIED_SETTINGS = (
    "server_url",
    "server_name",
    "user_name",
    "access_token",
    "refresh_token",
    "token_expires_at",
    "device_id",
    "logged_in",
    "ssl_verify",
    "speed_step",
    "min_speed",
    "max_speed",
    "book_speed",
    "podcast_speed",
    "per_book_speed",
    "sync_interval",
    "items_per_page",
    "sleep_screen_action",
    "sleep_idle_seconds",
    "sleep_rampdown_seconds",
    "sleep_last_preset",
)

# Data files that are ours rather than Kodi's, and can simply be copied.
CARRIED_FILES = ("speeds.json",)


def run_migrations(addon, profile_dir):
    _migrate_from_legacy_addon(addon, profile_dir)
    _migrate_legacy_token_file(addon, profile_dir)


# ── the rename ──


def _legacy_profile_dir():
    return xbmcvfs.translatePath(
        "special://profile/addon_data/{}/".format(LEGACY_ADDON_ID)
    )


def _migrate_from_legacy_addon(addon, profile_dir):
    """Adopt the Koshelf profile the first time Kotome runs.

    The old settings.xml is read off disk rather than through an Addon object,
    because the old add-on may not be installed any more — and if it is, Kodi
    would hand back its in-memory copy, which is not necessarily what is on
    disk. Values are then written through setSetting so Kodi owns them
    properly, instead of dropping a file into place under it.
    """
    if addon.getSetting("migrated_from_koshelf") == "true":
        return
    legacy = _legacy_profile_dir()
    legacy_settings = os.path.join(legacy, "settings.xml")
    if not os.path.exists(legacy_settings):
        # Nothing to adopt: a fresh install. Record that, so this does not
        # re-check on every invocation forever.
        addon.setSetting("migrated_from_koshelf", "true")
        return

    carried = 0
    try:
        root = ElementTree.parse(legacy_settings).getroot()
    except Exception as error:
        xbmc.log(
            "Kotome: could not read the Koshelf settings to migrate: {}".format(error),
            xbmc.LOGWARNING,
        )
        root = None

    if root is not None:
        for element in root.findall("setting"):
            setting_id = element.get("id")
            value = (element.text or "").strip()
            if setting_id in CARRIED_SETTINGS and value:
                try:
                    addon.setSetting(setting_id, value)
                    carried += 1
                except Exception:
                    pass

    try:
        os.makedirs(profile_dir, exist_ok=True)
        for name in CARRIED_FILES:
            source = os.path.join(legacy, name)
            target = os.path.join(profile_dir, name)
            if os.path.exists(source) and not os.path.exists(target):
                shutil.copy2(source, target)
    except OSError as error:
        xbmc.log(
            "Kotome: could not copy Koshelf data: {}".format(error), xbmc.LOGWARNING
        )

    addon.setSetting("migrated_from_koshelf", "true")
    xbmc.log(
        "Kotome: adopted the Koshelf profile ({} settings carried over). The old "
        "add-on's data is left in place and can be removed by hand.".format(carried),
        xbmc.LOGINFO,
    )


# ── the pre-0.24 credential cache ──


def _migrate_legacy_token_file(addon, profile_dir):
    """Adopt a token.json from before credentials moved into settings.

    The token it holds is AudioBookShelf's deprecated non-expiring one. It
    still works, so it is kept as-is with no expiry recorded — there is no
    refresh token to pair it with, and nothing should try to refresh it.
    """
    token_file = os.path.join(profile_dir, "token.json")
    if addon.getSetting("logged_in") == "true" or not os.path.exists(token_file):
        return
    try:
        with open(token_file, "r") as handle:
            token = json.load(handle).get("token", "")
    except Exception:
        token = ""
    if token and addon.getSetting("server_url"):
        addon.setSetting("access_token", token)
        addon.setSetting("refresh_token", "")
        addon.setSetting("token_expires_at", "0")
        addon.setSetting("logged_in", "true")
        if not addon.getSetting("user_name"):
            addon.setSetting("user_name", addon.getSetting("username"))
        xbmc.log("Kotome: adopted the cached session token", xbmc.LOGINFO)
    # The password was stored in plain text. Clear it whether or not the token
    # was usable — that is the part worth being rid of.
    for stale in ("username", "password"):
        try:
            addon.setSetting(stale, "")
        except Exception:
            pass
    try:
        os.remove(token_file)
    except OSError:
        pass
