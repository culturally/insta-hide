#!/usr/bin/env python3
"""
insta-hide - hide your Instagram followers & following lists.

    python hide.py

Logs in once (or reuses session.json), shows whether your lists are hidden,
and lets you flip each setting with a simple Y/N prompt.
"""
import getpass
import json
import logging
import re
import sys
from pathlib import Path

try:
    from colorama import Fore, Style, just_fix_windows_console
except ImportError:
    sys.exit("colorama is not installed. Run:  pip install -r requirements.txt")

just_fix_windows_console()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
logging.disable(logging.CRITICAL)  # instagrapi logs can contain request details

SESSION_FILE = Path(__file__).resolve().parent / "session.json"

# Instagram's private boolean-settings GraphQL endpoints (mobile app).
QUERY = {
    "friendly_name": "IGSettingsBooleanQuery",
    "root_field_name": "xdt_api__v1__settings__get_bool",
    "client_doc_id": "3203310381321258553037549573",
}
MUTATION = {
    "friendly_name": "IGSettingsBooleanMutation",
    "root_field_name": "xdt_api__v1__settings__set_bool",
    "client_doc_id": "2669261950526978627082629536",
}

SETTINGS = (
    {
        "id": "hide_followers_following_list",
        "title": "Followers & following lists",
        "ask_hide": "Hide your followers & following lists?",
        "ask_show": "Make your followers & following lists visible again?",
        "beta": False,
    },
    {
        "id": "hide_self_from_others_lists",
        "title": "You on other people's lists",
        "ask_hide": "Hide yourself from other people's follower/following lists?",
        "ask_show": "Show yourself on other people's lists again?",
        "beta": True,
    },
)

# ─── Look & feel ────────────────────────────────────────────────────────────

R, B, DIM = Style.RESET_ALL, Style.BRIGHT, Style.DIM

LOGO = """\
██╗███╗   ██╗███████╗████████╗ █████╗       ██╗  ██╗██╗██████╗ ███████╗
██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗      ██║  ██║██║██╔══██╗██╔════╝
██║██╔██╗ ██║███████╗   ██║   ███████║█████╗███████║██║██║  ██║█████╗
██║██║╚██╗██║╚════██║   ██║   ██╔══██║╚════╝██╔══██║██║██║  ██║██╔══╝
██║██║ ╚████║███████║   ██║   ██║  ██║      ██║  ██║██║██████╔╝███████╗
╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝"""
GRADIENT = (Fore.MAGENTA, Fore.LIGHTMAGENTA_EX, Fore.LIGHTRED_EX,
            Fore.RED, Fore.YELLOW, Fore.LIGHTYELLOW_EX)
LINE = "─" * 58


def banner():
    print("\033[2J\033[H", end="")  # clear screen
    print()
    for color, row in zip(GRADIENT, LOGO.splitlines()):
        print(f"  {color}{B}{row}{R}")
    print(f"\n  {DIM}Hide your followers & following - Instagram's secret setting, via the API{R}\n")


def ok(msg):   print(f"  {Fore.GREEN}{B}✔{R} {msg}")
def info(msg): print(f"  {Fore.CYAN}{B}›{R} {msg}", flush=True)
def warn(msg): print(f"  {Fore.YELLOW}{B}!{R} {msg}")
def fail(msg): print(f"  {Fore.RED}{B}✘{R} {msg}")


def ask(label):
    return input(f"  {Fore.MAGENTA}{B}?{R} {label}: ").strip()


def ask_secret(label):
    print(f"  {Fore.MAGENTA}{B}?{R} {label} {DIM}(hidden){R}: ", end="", flush=True)
    return getpass.getpass("")


def confirm(question, default=False):
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"  {Fore.MAGENTA}{B}?{R} {question} {DIM}[{hint}]{R} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def badge(value):
    if value is True:
        return f"{Fore.GREEN}{B}● HIDDEN{R}"
    if value is False:
        return f"{Fore.YELLOW}{B}○ VISIBLE{R}"
    return f"{Fore.RED}{B}? UNKNOWN{R}"


def word(value):
    return "HIDDEN" if value else "VISIBLE"


def show_status(username, states):
    print(f"  {DIM}───{R} {B}@{username}{R} {DIM}{LINE[:max(3, 52 - len(username))]}{R}")
    for i, s in enumerate(SETTINGS, 1):
        tag = f" {Fore.MAGENTA}BETA{R}" if s["beta"] else ""
        pad = " " * (36 - len(s["title"]) - (5 if s["beta"] else 0))
        print(f"   {Fore.CYAN}{B}{i}{R}  {s['title']}{tag}{pad}{badge(states.get(s['id']))}")
    print(f"  {DIM}{LINE}{R}")
    print(f"   {Fore.CYAN}{B}R{R} refresh   {Fore.CYAN}{B}L{R} log out   {Fore.CYAN}{B}Q{R} quit\n")


# ─── Instagram API ─────────────────────────────────────────────────────────

class ApiError(Exception):
    pass


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_bool(response, root_field):
    """Pull the single boolean `value` out of a settings GraphQL response."""
    if isinstance(response, dict) and isinstance(response.get("stream_rows"), list) \
            and len(response["stream_rows"]) == 1:
        response = response["stream_rows"][0]
    if not isinstance(response, dict) or response.get("errors") or response.get("status") == "fail":
        raise ApiError("Instagram rejected the request.")
    data = response.get("data")
    target = _norm(root_field)
    hits = [v for k, v in data.items() if isinstance(k, str) and target in _norm(k)] \
        if isinstance(data, dict) else []
    if len(hits) != 1 or not isinstance(hits[0], dict):
        raise ApiError("Instagram sent a response insta-hide doesn't recognise.")
    node = hits[0]
    if any(node.get(k) for k in ("error_name_value", "errorNameValue",
                                 "fallback_message", "fallbackMessage")):
        raise ApiError("Instagram refused this setting for your account.")
    if type(node.get("value")) is not bool:
        raise ApiError("Instagram sent a response insta-hide doesn't recognise.")
    return node["value"]


def get_setting(cl, setting_id):
    response = cl.private_graphql_query_request(**QUERY, variables={"setting_id": setting_id})
    return read_bool(response, QUERY["root_field_name"])


def set_setting(cl, setting_id, value):
    """Send the change, then always read it back. Returns (new_value, error)."""
    variables = {"allow_error_codes": True, "callsite": "account_privacy",
                 "setting_id": setting_id, "value": value}
    error = None
    try:
        read_bool(cl.private_graphql_query_request(**MUTATION, variables=variables),
                  MUTATION["root_field_name"])
    except Exception as exc:  # a failed response doesn't prove nothing changed
        error = exc
    try:
        return get_setting(cl, setting_id), error
    except Exception as exc:
        return None, exc


def read_all(cl):
    states, problem = {}, None
    for s in SETTINGS:
        try:
            states[s["id"]] = get_setting(cl, s["id"])
        except Exception as exc:
            if is_auth_error(exc):
                raise
            states[s["id"]], problem = None, describe(exc)
    return states, problem


def _names(exc):
    return {c.__name__ for c in type(exc).__mro__}


def is_auth_error(exc):
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return bool(_names(exc) & {"LoginRequired", "ClientLoginRequired", "ClientUnauthorizedError",
                               "ClientForbiddenError", "ReloginAttemptExceeded"}) or status in (401, 403)


def describe(exc):
    """Human-friendly message. Never prints the raw exception (it may hold tokens)."""
    names = _names(exc)
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, ApiError):
        return str(exc)
    if names & {"BadPassword", "BadCredentials"}:
        return "Wrong username or password."
    if names & {"TwoFactorRequired"}:
        return "Two-factor code was wrong or expired."
    if names & {"ChallengeError", "CheckpointRequired", "FeedbackRequired"}:
        return "Instagram wants you to confirm this login. Approve it in the Instagram app, then try again."
    if is_auth_error(exc):
        return "Your session expired or access was denied."
    if names & {"RateLimitError", "ClientThrottledError", "PleaseWaitFewMinutes"} or status == 429:
        return "Instagram is rate-limiting you. Wait a few minutes and try again."
    if names & {"ClientConnectionError", "ClientRequestTimeout", "ConnectionError", "TimeoutError"}:
        return "Couldn't reach Instagram. Check your internet connection."
    return f"Something went wrong ({type(exc).__name__})."


# ─── Session ───────────────────────────────────────────────────────────────

def load_session():
    try:
        text = SESSION_FILE.read_text(encoding="utf-8")
        if not text.strip():
            return None  # empty file = no saved session
        data = json.loads(text)
        return str(data["username"]), dict(data["settings"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        warn(f"{SESSION_FILE.name} is unreadable - ignoring it.")
        return None


def save_session(username, cl):
    payload = {"username": username, "settings": cl.get_settings()}
    SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def new_client(Client):
    cl = Client()
    cl.challenge_code_handler = lambda _user, _choice: ask("Security code Instagram just sent you")
    return cl


def harden(cl):
    # Never auto-retry or follow redirects on requests that change settings.
    cl.set_retry_config(session_retry_total=0, session_retry_statuses=[])
    cl.private.max_redirects = 0


def _find(data, key):
    """First truthy value of `key` anywhere in a nested login response."""
    if isinstance(data, dict):
        if data.get(key):
            return data[key]
        data = list(data.values())
    if isinstance(data, list):
        for child in data:
            found = _find(child, key)
            if found:
                return found
    return None


def two_factor_hint(cl):
    """Tell the user where their code comes from, based on Instagram's reply."""
    data = getattr(cl, "last_json", None) or {}
    if _find(data, "totp_two_factor_on"):
        return "Open your authenticator app and enter the 6-digit Instagram code."
    if _find(data, "sms_two_factor_on"):
        phone = _find(data, "obfuscated_phone_number")
        where = f"to {B}{phone}{R}" if phone else "to your phone"
        return f"Enter the 6-digit code Instagram texted {where}."
    return "Enter the 6-digit code from your authenticator app or SMS."


TWO_FACTOR_TRIES = 3
FATAL_LOGIN_ERRORS = {"RateLimitError", "PleaseWaitFewMinutes", "ClientThrottledError",
                      "ChallengeError", "ClientConnectionError", "ClientRequestTimeout"}


def two_factor_login(cl, username, password):
    """Only called when Instagram says the account has 2FA on."""
    print()
    print(f"  {Fore.MAGENTA}{B}Two-factor authentication is on for this account{R}")
    info(two_factor_hint(cl))
    info(f"{DIM}An 8-digit backup code works too. If a new SMS arrives, use the newest code.{R}")
    tries = 0
    while True:
        code = re.sub(r"[\s-]", "", ask(f"2FA code {DIM}(Enter to cancel){R}"))
        if not code:
            raise ApiError("Login cancelled.")
        if not re.fullmatch(r"\d{6}|\d{8}", code):
            warn("Codes are 6 digits (or 8 for a backup code).")
            continue
        info("Verifying code...")
        try:
            cl.login(username, password, verification_code=code)
            return
        except Exception as exc:
            tries += 1
            if _names(exc) & FATAL_LOGIN_ERRORS:
                raise
            if tries >= TWO_FACTOR_TRIES:
                raise ApiError(f"The 2FA code didn't work after {TWO_FACTOR_TRIES} tries. "
                               "Wait a minute and log in again.") from None
            left = TWO_FACTOR_TRIES - tries
            fail(f"That code didn't work - {left} {'try' if left == 1 else 'tries'} left.")


def login(Client):
    print(f"  {B}Log in to Instagram{R}  {DIM}(your password is never saved){R}\n")
    while True:
        username = ask("Username").lstrip("@")
        password = ask_secret("Password")
        if username and password:
            break
        warn("Username and password are both required.")
    cl = new_client(Client)
    info("Logging in...")
    try:
        cl.login(username, password)  # no code needed if 2FA is off
    except Exception as exc:
        if "TwoFactorRequired" not in _names(exc):
            raise
        two_factor_login(cl, username, password)
    ok(f"Logged in as {B}@{username}{R}")
    if confirm("Save session so you don't need to log in next time?", default=True):
        save_session(username, cl)
        ok(f"Session saved to {SESSION_FILE.name}")
    harden(cl)
    return username, cl


def connect(Client):
    """Return (username, client, states, problem) or None if the user gives up."""
    saved = load_session()
    if saved:
        username, settings = saved
        info(f"Using saved session for {B}@{username}{R}...")
        cl = new_client(Client)
        cl.set_settings(settings)
        harden(cl)
        try:
            return (username, cl, *read_all(cl))
        except Exception as exc:
            if not is_auth_error(exc):
                raise
            warn("Saved session has expired - please log in again.\n")
            SESSION_FILE.unlink(missing_ok=True)
    while True:
        try:
            username, cl = login(Client)
            info("Checking your privacy settings...")
            return (username, cl, *read_all(cl))
        except Exception as exc:
            fail(describe(exc))
            if not confirm("Try again?", default=True):
                return None
            print()


# ─── App ───────────────────────────────────────────────────────────────────

def change(cl, setting, states):
    """Ask Y/N, apply, verify. Returns a list of (printer, message) notices."""
    current = states.get(setting["id"])
    print()
    if current is None:
        pick = ask(f"{setting['title']} status is unknown. [H]ide, [S]how or Enter to cancel").lower()
        if pick not in ("h", "s"):
            return []
        target = pick == "h"
    else:
        print(f"  {setting['title']} {DIM}currently{R} {badge(current)}")
        if not confirm(setting["ask_show"] if current else setting["ask_hide"]):
            return [(info, "No changes made.")]
        target = not current
    if setting["beta"]:
        warn("Beta: this setting is not confirmed to work on every account.")
    info("Updating...")
    new, error = set_setting(cl, setting["id"], target)
    states[setting["id"]] = new
    if new == target:
        return [(ok, f"{setting['title']} is now {badge(new)}")]
    notices = [(fail, f"Instagram didn't apply the change. {setting['title']}: {badge(new)}")]
    if error is not None:
        notices.append((warn, describe(error)))
    return notices


def run():
    banner()
    info("Loading Instagram client...")
    try:
        from instagrapi import Client
    except ImportError:
        fail("instagrapi is not installed. Run:  pip install -r requirements.txt")
        return 1
    print()

    result = connect(Client)
    if result is None:
        return 1
    username, cl, states, problem = result
    notices = [(warn, problem)] if problem else []

    while True:
        banner()
        show_status(username, states)
        for printer, msg in notices:
            printer(msg)
        if notices:
            print()
        notices = []

        choice = ask("Choose").lower()
        if choice in [str(i) for i in range(1, len(SETTINGS) + 1)]:
            notices = change(cl, SETTINGS[int(choice) - 1], states)
        elif choice == "r":
            info("Refreshing...")
            states, problem = read_all(cl)
            notices = [(warn, problem)] if problem else [(ok, "Up to date.")]
        elif choice == "l":
            if confirm(f"Log out @{username} and delete {SESSION_FILE.name}?"):
                SESSION_FILE.unlink(missing_ok=True)
                ok("Logged out. Session deleted.")
                return 0
        elif choice == "q":
            if SESSION_FILE.exists():
                save_session(username, cl)  # keep refreshed cookies
            print(f"\n  {Fore.MAGENTA}{B}Bye!{R}\n")
            return 0
        else:
            notices = [(warn, "Pick 1, 2, R, L or Q.")]


def main():
    try:
        return run()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {Fore.MAGENTA}{B}Bye!{R}\n")
        return 130
    except Exception as exc:
        print()
        fail(describe(exc))
        if is_auth_error(exc):
            warn(f"Delete {SESSION_FILE.name} or choose L to log in again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
