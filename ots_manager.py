#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import qrcode
import requests

OTS_URL = os.getenv("OTS_URL", "http://localhost:5000").rstrip("/")
API_USERNAME = os.getenv("OTS_USER", "admin")
API_PASSWORD = os.getenv("OTS_PASS", "admin_password")
# Items per page when paginating /api/groups, /api/users, and /api/missions.
# The server's default is 10; a higher value reduces the number of requests
# needed to walk large lists. No known upper limit is enforced by the API.
OTS_PAGE_SIZE = int(os.getenv("OTS_PAGE_SIZE", "100"))

session = requests.Session()
# Global headers required to satisfy Flask-Security/WTF validations
session.headers.update({
    "Content-Type": "application/json",
    "Referer": f"{OTS_URL}/",
    "Origin": OTS_URL,
})


def get_csrf_token():
  """Retrieves the CSRF token stored in the Flask session cookies."""
  return (
      session.cookies.get("csrf_token")
      or session.cookies.get("csrf_access_token")
      or session.cookies.get("XSRF-TOKEN")
  )


def login():
  """Authenticates with OpenTAKServer and captures the session's CSRF token."""
  login_url = f"{OTS_URL}/api/login"
  payload = {"username": API_USERNAME, "password": API_PASSWORD}

  try:
    response = session.post(login_url, json=payload, timeout=10)

    if response.status_code in [200, 201]:
      print("[+] Successfully authenticated with OpenTAKServer.")

      csrf = get_csrf_token()
      if not csrf:
        try:
          res_data = response.json()
          csrf = res_data.get("csrf_token") or res_data.get(
              "response", {}
          ).get("csrf_token")
        except Exception:
          csrf = None

      if csrf:
        session.headers.update({
            "X-CSRFToken": csrf,
            "X-CSRF-TOKEN": csrf,
        })
      return True
    else:
      print(
          f"[-] Authentication failed: {response.status_code} - {response.text}"
      )
      return False
  except Exception as e:
    print(f"[-] Error connecting to the server: {e}")
    return False


def create_group(group_name):
  """Creates a group on OpenTAKServer (POST /api/groups)."""
  url = f"{OTS_URL}/api/groups"
  payload = {"name": group_name}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] Group '{group_name}' created successfully.")
    return True
  elif response.status_code == 400 and "exists" in response.text.lower():
    print(f"[!] Group '{group_name}' already exists.")
    return True
  else:
    print(
        f"[-] Error creating group '{group_name}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def delete_group(group_name):
  """Removes a group from OpenTAKServer (DELETE /api/groups?group_name=...)."""
  url = f"{OTS_URL}/api/groups"

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.delete(url, params={"group_name": group_name}, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] Group '{group_name}' removed successfully.")
    return True
  elif response.status_code == 404:
    print(f"[!] Group '{group_name}' was not found.")
    return True
  else:
    print(
        f"[-] Error removing group '{group_name}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def _paginate_all(url, per_page=None):
  """Walks every page of a paginated OTS endpoint.

  OpenTAKServer paginates /api/groups, /api/users, and /api/missions with the
  format {"current_page", "per_page", "results", "total", "total_pages"} and
  per_page=10 by default. Fetching only page 1 (the previous behavior) made
  lists larger than per_page show up incomplete, with no indication that
  there were more items.

  'per_page' controls how many items are requested per call (default:
  OTS_PAGE_SIZE, configurable via environment variable); every page is
  always walked to the end regardless, so this value only affects the number
  of HTTP requests made, not the completeness of the result.

  Returns the tuple (full_item_list, total_reported_by_the_api_or_None).
  """
  if per_page is None:
    per_page = OTS_PAGE_SIZE
  items = []
  page = 1
  reported_total = None

  while True:
    try:
      response = session.get(url, params={"page": page, "per_page": per_page}, timeout=10)
    except Exception as e:
      print(f"[-] Error connecting to {url}: {e}")
      return items, reported_total

    if response.status_code != 200:
      print(f"[-] Error querying {url}: {response.status_code} - {response.text}")
      return items, reported_total

    try:
      data = response.json()
    except Exception:
      return items, reported_total

    if isinstance(data, list):
      return data, len(data)

    if not isinstance(data, dict):
      return items, reported_total

    page_results = data.get("results")
    if not isinstance(page_results, list):
      return items, reported_total

    items.extend(page_results)
    reported_total = data.get("total", reported_total)
    total_pages = data.get("total_pages") or 1
    current_page = data.get("current_page") or page

    if not page_results or current_page >= total_pages:
      return items, reported_total

    page += 1


def list_groups():
  """Returns the list of group names existing on OpenTAKServer (all pages)."""
  items, total = _paginate_all(f"{OTS_URL}/api/groups")

  names = []
  for g in items:
    if isinstance(g, str):
      names.append(g)
    elif isinstance(g, dict):
      name = g.get("name") or g.get("group") or g.get("groupname")
      if name:
        names.append(name)

  if total is not None and len(names) != total:
    print(
        f"[!] Warning: the API reported {total} group(s) in total, but"
        f" {len(names)} were returned."
    )

  return names


def get_groups_with_ids():
  """Returns every group (id and name) by walking all pages.

  Used to resolve group names into numeric IDs when creating missions.
  """
  items, _ = _paginate_all(f"{OTS_URL}/api/groups")
  groups = []
  for g in items:
    if isinstance(g, dict) and g.get("id") is not None and g.get("name"):
      groups.append({"id": g.get("id"), "name": g.get("name")})
  return groups


def resolve_group_ids(group_names):
  """Converts group names into numeric IDs (required by /api/missions).

  Returns the tuple (resolved_ids, names_not_found).
  """
  by_name = {g["name"]: g["id"] for g in get_groups_with_ids()}
  ids = []
  missing = []
  for name in group_names:
    if name in by_name:
      ids.append(by_name[name])
    else:
      missing.append(name)
  return ids, missing


def _normalize_admin_flag(value):
  """Converts different administrator representations into a boolean."""
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    return bool(value)
  if isinstance(value, str):
    normalized = value.strip().lower()
    if normalized in ["1", "true", "yes", "admin", "administrator"]:
      return True
    if normalized in ["0", "false", "no"]:
      return False
  return False


def _normalize_last_login(value):
  """Converts dates/epoch values into a readable ISO string for display."""
  if value is None or value == "" or str(value).lower() in ["none", "null"]:
    return None

  if isinstance(value, (int, float)):
    try:
      return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
      return str(value)

  if isinstance(value, str):
    text = value.strip()
    if not text:
      return None
    if text.isdigit() or text.replace(".", "", 1).isdigit():
      try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc).isoformat()
      except Exception:
        pass
    if text.endswith("Z"):
      text = text[:-1] + "+00:00"
    try:
      return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()
    except Exception:
      return text

  return str(value)


def _normalize_user_entry(entry):
  """Converts a raw API user entry into {username, admin, last_login}."""
  username = (
      entry.get("username")
      or entry.get("user")
      or entry.get("login")
      or entry.get("name")
  )
  if not username:
    return None

  # First attempt: direct flags
  admin_field = (
      entry.get("administrator")
      or entry.get("admin")
      or entry.get("is_admin")
      or entry.get("isAdministrator")
      or entry.get("role")
  )
  admin = _normalize_admin_flag(admin_field)

  # If a roles list exists, inspect its name and permissions
  roles_list = entry.get("roles") or entry.get("role_list") or entry.get("roles_list")
  if isinstance(roles_list, list):
    for r in roles_list:
      if isinstance(r, dict):
        rname = str(r.get("name") or "").strip().lower()
        if rname and ("administrator" in rname or rname == "admin" or "organ" in rname):
          admin = True
          break
        perms = r.get("permissions") or []
        if isinstance(perms, list):
          for p in perms:
            if "administrator" in str(p).lower() or "admin" in str(p).lower():
              admin = True
              break
          if admin:
            break

  last_login = _normalize_last_login(
      entry.get("last_login")
      or entry.get("lastLogin")
      or entry.get("last_login_at")
      or entry.get("last_login_time")
      or entry.get("last_seen")
      or entry.get("logged_in_at")
  )

  return {"username": username, "admin": admin, "last_login": last_login}


def list_users():
  """Lists users (all pages) and tries to extract admin status and last login."""
  items, total = _paginate_all(f"{OTS_URL}/api/users")

  users = []
  for entry in items:
    if not isinstance(entry, dict):
      continue
    user = _normalize_user_entry(entry)
    if user:
      users.append(user)

  if total is not None and len(users) != total:
    print(
        f"[!] Warning: the API reported {total} user(s) in total, but"
        f" {len(users)} were returned."
    )

  return users


def get_creator_uid_for_username(username):
  """Looks up the UID of a user's first linked device (EUD).

  Required because /api/missions expects a creator_uid from an already
  registered EUD, not just the username.
  """
  items, _ = _paginate_all(f"{OTS_URL}/api/users")
  for entry in items:
    if not isinstance(entry, dict):
      continue
    entry_username = entry.get("username") or entry.get("user") or entry.get("login")
    if entry_username != username:
      continue
    euds = entry.get("euds")
    if isinstance(euds, list):
      for eud in euds:
        if isinstance(eud, dict) and eud.get("uid"):
          return eud.get("uid")
    return None
  return None


def create_user(username, password, email="", is_admin=False):
  """Creates a user on OpenTAKServer (POST /api/user/add).

  The endpoint expects a 'roles' list, not an 'administrator' boolean; an
  unrecognized 'administrator' field is silently ignored by the server,
  which then defaults every new user to the 'user' role. OpenTAKServer
  treats 'administrator' and 'user' as mutually exclusive single roles
  (every admin account on the server carries only 'administrator', never
  both — see set_user_admin()), so exactly one role is sent here too.
  """
  url = f"{OTS_URL}/api/user/add"
  payload = {
      "username": username,
      "password": password,
      "confirm_password": password,
      "email": email,
      "roles": ["administrator"] if is_admin else ["user"],
  }

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] User '{username}' created successfully.")
    return True
  elif response.status_code == 400 and "exists" in response.text.lower():
    print(f"[!] User '{username}' already exists.")
    return True
  else:
    print(
        f"[-] Error creating user '{username}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def delete_user(username):
  """Removes a user from OpenTAKServer (POST /api/user/delete)."""
  url = f"{OTS_URL}/api/user/delete"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] User '{username}' removed successfully.")
    return True
  elif response.status_code == 404:
    print(f"[!] User '{username}' was not found.")
    return True
  else:
    print(
        f"[-] Error removing user '{username}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def deactivate_user(username):
  """Deactivates a user on OpenTAKServer (POST /api/user/deactivate)."""
  url = f"{OTS_URL}/api/user/deactivate"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] User '{username}' deactivated successfully.")
    return True
  elif response.status_code == 404:
    print(f"[!] User '{username}' was not found.")
    return True
  else:
    print(
        f"[-] Error deactivating user '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def activate_user(username):
  """Activates a user on OpenTAKServer (POST /api/user/activate)."""
  url = f"{OTS_URL}/api/user/activate"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] User '{username}' activated successfully.")
    return True
  elif response.status_code == 404:
    print(f"[!] User '{username}' was not found.")
    return True
  else:
    print(
        f"[-] Error activating user '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def add_user_to_group(username, group_name, direction="BOTH"):
  """Associates a user with a group on OpenTAKServer (IN, OUT, or BOTH)."""
  url = f"{OTS_URL}/api/users/groups"
  direction = str(direction).upper()
  if direction not in ["IN", "OUT", "BOTH"]:
    direction = "BOTH"

  directions_to_process = ["IN", "OUT"] if direction == "BOTH" else [direction]
  success = True

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  for dir_type in directions_to_process:
    payload = {
        "username": username,
        "groups": [group_name],
        "direction": dir_type,
    }
    response = session.put(url, json=payload, headers=headers)
    if response.status_code in [200, 204]:
      print(
          f"[+] User '{username}' added to group '{group_name}'"
          f" ({dir_type})."
      )
    else:
      print(
          f"[-] Error adding '{username}' to group '{group_name}'"
          f" ({dir_type}): {response.status_code}"
      )
      success = False
  return success


def remove_user_from_group(username, group_name, direction):
  """Removes a user from a group in a specific direction.

  Calls DELETE /api/groups/members?username=...&group_name=...&direction=...
  Unlike add_user_to_group(), 'direction' here must be IN or OUT (BOTH isn't
  supported by this individual call).
  """
  url = f"{OTS_URL}/api/groups/members"
  direction = str(direction).upper()

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.delete(
      url,
      params={"username": username, "group_name": group_name, "direction": direction},
      headers=headers,
  )
  if response.status_code in [200, 201, 204]:
    print(
        f"[+] User '{username}' removed from group '{group_name}'"
        f" ({direction})."
    )
    return True
  elif response.status_code == 404:
    print(
        f"[!] User '{username}' was already not a member of group"
        f" '{group_name}' ({direction})."
    )
    return True
  else:
    print(
        f"[-] Error removing '{username}' from group '{group_name}'"
        f" ({direction}): {response.status_code} - {response.text}"
    )
    return False


def get_user_group_memberships(username):
  """Returns a user's current group memberships.

  Calls GET /api/users/groups?username=... and returns a list of
  {"group_name", "direction", "active"}.
  """
  url = f"{OTS_URL}/api/users/groups"
  try:
    response = session.get(url, params={"username": username}, timeout=10)
  except Exception as e:
    print(f"[-] Error querying groups for '{username}': {e}")
    return []

  if response.status_code != 200:
    print(
        f"[-] Error querying groups for '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return []

  try:
    data = response.json()
  except Exception:
    return []

  results = data.get("results") if isinstance(data, dict) else None
  return results if isinstance(results, list) else []


def sync_user_groups(username, desired_groups):
  """Syncs a user's group memberships to match 'desired_groups'.

  'desired_groups' accepts the same format as -g/--groups in create-user
  (strings 'GROUP', 'GROUP:IN', 'GROUP:OUT', 'GROUP:BOTH', dicts with
  name/direction, or the special value 'ALL'). The given set is treated as
  the final desired state: current memberships absent from the list are
  removed, and any missing ones are added. An empty list removes every
  current membership for the user.
  """
  desired_pairs = set()
  for entry in desired_groups:
    g_name, g_dir = parse_group_entry(entry)
    if not g_name:
      continue
    if str(g_name).upper() == "ALL":
      for existing_name in list_groups():
        desired_pairs.add((existing_name, "IN"))
        desired_pairs.add((existing_name, "OUT"))
      continue
    directions = ["IN", "OUT"] if g_dir == "BOTH" else [g_dir]
    for d in directions:
      desired_pairs.add((g_name, d))

  current_pairs = {
      (m.get("group_name"), str(m.get("direction")).upper())
      for m in get_user_group_memberships(username)
      if m.get("group_name") and m.get("direction")
  }

  success = True
  for group_name, direction in sorted(desired_pairs - current_pairs):
    if not add_user_to_group(username, group_name, direction=direction):
      success = False
  for group_name, direction in sorted(current_pairs - desired_pairs):
    if not remove_user_from_group(username, group_name, direction):
      success = False
  return success


def reset_user_password(username, new_password):
  """Resets an existing user's password (POST /api/user/password/reset)."""
  url = f"{OTS_URL}/api/user/password/reset"
  payload = {"username": username, "new_password": new_password}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] Password for user '{username}' reset successfully.")
    return True
  else:
    print(
        f"[-] Error resetting password for '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def set_user_admin(username, is_admin):
  """Sets whether a user is an administrator (POST /api/user/role).

  The endpoint replaces the user's full role list. OpenTAKServer treats
  'administrator' and 'user' as mutually exclusive single roles (every
  admin account on the server carries only 'administrator', never both),
  so this sends exactly one role rather than combining the two — sending
  both leaves the server-side role list in a state the OTS web panel
  doesn't recognize as administrator.
  """
  url = f"{OTS_URL}/api/user/role"
  roles = ["administrator"] if is_admin else ["user"]
  payload = {"username": username, "roles": roles}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    status = "administrator" if is_admin else "regular user"
    print(f"[+] Role for '{username}' updated to {status}.")
    return True
  else:
    print(
        f"[-] Error updating role for '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def update_user(username, password=None, groups=None, is_admin=None):
  """Updates an existing user: password, administrator role, and/or groups.

  Each parameter is optional (None = don't change). 'groups', when given, is
  treated as the full desired set of groups (see sync_user_groups()) — it
  adds whatever is missing and removes whatever is left over.
  """
  success = True

  if password is not None:
    if not reset_user_password(username, password):
      success = False

  if is_admin is not None:
    if not set_user_admin(username, is_admin):
      success = False

  if groups is not None:
    if not sync_user_groups(username, groups):
      success = False

  return success


def process_batch_update(data_list, output_summary_file=None):
  """Processes batch user updates.

  Accepts the same JSON file used by create-user -f (e.g. users_sample.json).
  For each record, only the fields present are applied: 'password' (resets
  the password), 'administrator' (sets the role), and 'groups' (syncs
  memberships, see sync_user_groups()). The remaining creation fields
  (email, app, expiration, max_uses) don't apply to an update and are
  ignored.
  """
  results = []

  print("\n--- Processing User Updates ---")
  for item in data_list:
    if isinstance(item, str):
      username = item
      password = None
      groups = None
      is_admin = None
    elif isinstance(item, dict):
      username = item.get("username")
      password = item.get("password")
      groups = item.get("groups")
      is_admin = item.get("administrator")
    else:
      username = None

    if not username:
      print(f"[-] Record skipped (missing username): {item}")
      continue

    success = update_user(username, password=password, groups=groups, is_admin=is_admin)
    results.append({"username": username, "updated": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Consolidated report exported to: {output_summary_file}")

  return results


def create_mission(
    name,
    creator_uid,
    description=None,
    groups=None,
    tool=None,
    classification=None,
    default_role=None,
    password=None,
    keywords=None,
    chat_room=None,
    base_layer=None,
    bbox=None,
    path=None,
    invite_only=None,
    expiration=None,
):
  """Creates a mission (Data Sync) on OpenTAKServer (POST /api/missions).

  'groups' accepts a list of group names (including the special value
  'ALL', which expands to every existing group) and is resolved into the
  numeric IDs required by the API before sending.
  """
  url = f"{OTS_URL}/api/missions"
  payload = {"name": name, "creator_uid": creator_uid}

  optional_fields = {
      "description": description,
      "tool": tool,
      "classification": classification,
      "default_role": default_role,
      "password": password,
      "keywords": keywords,
      "chat_room": chat_room,
      "base_layer": base_layer,
      "bbox": bbox,
      "path": path,
      "invite_only": invite_only,
      "expiration": expiration,
  }
  for field, value in optional_fields.items():
    if value is not None:
      payload[field] = value

  if groups:
    group_names = list(groups)
    if any(str(g).upper() == "ALL" for g in group_names):
      group_names = list_groups()

    group_ids, missing = resolve_group_ids(group_names)
    if missing:
      print(
          "[-] Mission not created, nonexistent group(s):"
          f" {', '.join(missing)}"
      )
      return False
    payload["groups"] = group_ids

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] Mission '{name}' created successfully.")
    return True
  else:
    print(
        f"[-] Error creating mission '{name}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def delete_mission(name):
  """Removes a mission from OpenTAKServer (DELETE /api/missions?name=...)."""
  url = f"{OTS_URL}/api/missions"

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.delete(url, params={"name": name}, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] Mission '{name}' removed successfully.")
    return True
  elif response.status_code == 404:
    print(f"[!] Mission '{name}' was not found.")
    return True
  else:
    print(
        f"[-] Error removing mission '{name}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def list_missions():
  """Returns the list of mission names existing on OpenTAKServer (all pages)."""
  items, total = _paginate_all(f"{OTS_URL}/api/missions")

  names = []
  for m in items:
    if isinstance(m, str):
      names.append(m)
    elif isinstance(m, dict):
      name = m.get("name")
      if name:
        names.append(name)

  if total is not None and len(names) != total:
    print(
        f"[!] Warning: the API reported {total} mission(s) in total, but"
        f" {len(names)} were returned."
    )

  return names


def parse_expiration(exp_val):
  """Converts an expiration value into a Unix Epoch timestamp, if provided."""
  if exp_val is None:
    return None
  try:
    exp_str = str(exp_val).strip()
    if not exp_str or exp_str.lower() in ["none", "null", "eterno", "infinito"]:
      return None
    if exp_str.isdigit():
      return int(
          datetime.now(timezone.utc).timestamp() + (int(exp_str) * 86400)
      )
    dt = datetime.strptime(exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
  except Exception as e:
    print(f"[-] Invalid date format ({exp_val}): {e}")
    return None


def get_qr_string(
    username, app_type="android", exp_timestamp=None, max_uses=None
):
  """Gets the QR code string for Android or iPhone with Referer and CSRF."""
  app_type = app_type.lower()

  if app_type == "android":
    url = f"{OTS_URL}/api/atak_qr_string"
    payload = {"username": username}

    if max_uses is not None:
      payload["max"] = int(max_uses)
    if exp_timestamp is not None:
      payload["exp"] = int(exp_timestamp)
      payload["nbf"] = int(datetime.now(timezone.utc).timestamp())

    csrf = get_csrf_token()
    headers = {
        "Referer": f"{OTS_URL}/",
        "Origin": OTS_URL,
    }
    if csrf:
      headers["X-CSRFToken"] = csrf
      headers["X-CSRF-TOKEN"] = csrf

    response = session.post(url, json=payload, headers=headers)
    if response.status_code in [200, 201]:
      try:
        res_data = response.json()
        return (
            res_data.get("qr_string")
            or res_data.get("token")
            or response.text.strip('"')
        )
      except Exception:
        return response.text.strip('"')
    else:
      print(
          f"[-] Error generating Android QR for '{username}':"
          f" {response.status_code} - {response.text}"
      )
      return None

  elif app_type == "iphone":
    url = f"{OTS_URL}/api/itak_qr_string"
    response = session.get(url)
    if response.status_code == 200:
      try:
        res_data = response.json()
        return (
            res_data.get("qr_string")
            or res_data.get("itak_qr_string")
            or response.text.strip('"')
        )
      except Exception:
        return response.text.strip('"')
    else:
      print(
          f"[-] Error retrieving iPhone QR: {response.status_code} -"
          f" {response.text}"
      )
      return None
  else:
    print(
        f"[-] Invalid app option: '{app_type}'. Choose between"
        " 'android' or 'iphone'."
    )
    return None


def save_qr_code_image(qr_data, output_path):
  """Generates a PNG image from the QR Code string."""
  output_dir = os.path.dirname(output_path)
  if output_dir:
    os.makedirs(output_dir, exist_ok=True)

  qr = qrcode.QRCode(
      version=1,
      error_correction=qrcode.constants.ERROR_CORRECT_M,
      box_size=10,
      border=4,
  )
  qr.add_data(qr_data)
  qr.make(fit=True)
  img = qr.make_image(fill_color="black", back_color="white")
  img.save(output_path)
  print(f"[+] QR Code saved to: {output_path}")


def parse_group_entry(item):
  """Normalizes group entries coming from CLI strings ('CSAR:IN' or 'CSAR')

  or JSON objects ({"name": "CSAR", "direction": "IN"}).
  Returns the tuple: (group_name, direction).
  """
  if isinstance(item, dict):
    name = item.get("name") or item.get("group")
    direction = item.get("direction") or item.get("directions") or "BOTH"
    return (name, direction.upper())
  elif isinstance(item, str):
    if ":" in item:
      parts = item.split(":", 1)
      dir_candidate = parts[1].upper()
      if dir_candidate in ["IN", "OUT", "BOTH"]:
        return (parts[0], dir_candidate)
      return (item, "BOTH")
    return (item, "BOTH")
  return (None, "BOTH")


def process_batch_list(
    data_list, output_summary_file="resultado_qr_codes.json"
):
  """Processes a batch of users/groups with support for individual directions."""
  os.makedirs("qrcodes", exist_ok=True)
  summary_results = []

  # 1. Collect unique groups for upfront creation
  groups_to_create = set()
  for item in data_list:
    raw_groups = item.get("groups", [])
    for g in raw_groups:
      g_name, _ = parse_group_entry(g)
      if g_name:
        if str(g_name).upper() == "ALL":
          existing = list_groups()
          for ex in existing:
            groups_to_create.add(ex)
        else:
          groups_to_create.add(g_name)

  print("\n--- Processing Groups ---")
  for group_name in groups_to_create:
    create_group(group_name)

  # 2. User creation and group links
  print("\n--- Processing Users and Generating QR Codes ---")
  for user_info in data_list:
    username = user_info.get("username")
    password = user_info.get("password")
    email = user_info.get("email", "")
    is_admin = user_info.get("administrator", False)
    raw_groups = user_info.get("groups", [])
    app_type = user_info.get("app", "android").lower()
    max_uses = user_info.get("max_uses")
    expiration = user_info.get("expiration")

    if not username or not password:
      print(f"[-] Record skipped (missing data): {user_info}")
      continue

    created = create_user(username, password, email, is_admin)
    if created:
      for g in raw_groups:
        g_name, g_dir = parse_group_entry(g)
        if g_name:
          if str(g_name).upper() == "ALL":
            existing = list_groups()
            for ex in existing:
              add_user_to_group(username, ex, direction=g_dir)
          else:
            add_user_to_group(username, g_name, direction=g_dir)

      exp_ts = parse_expiration(expiration)
      qr_string = get_qr_string(
          username=username,
          app_type=app_type,
          exp_timestamp=exp_ts,
          max_uses=max_uses,
      )

      record = {
          "username": username,
          "app": app_type,
          "max_uses": (
              max_uses if max_uses is not None else "server default"
          ),
          "expiration": (
              expiration if expiration is not None else "server default"
          ),
          "qr_string": qr_string,
          "qr_image": None,
      }

      if qr_string:
        img_filename = f"qrcodes/{username}_{app_type}.png"
        save_qr_code_image(qr_string, img_filename)
        record["qr_image"] = img_filename

      summary_results.append(record)

  with open(output_summary_file, "w", encoding="utf-8") as f:
    json.dump(summary_results, f, indent=2, ensure_ascii=False)
  print(f"\n[+] Consolidated report exported to: {output_summary_file}")


def extract_usernames(data_list):
  """Extracts only the usernames from a batch.

  Accepts either a list of strings or the same original JSON file used for
  creation (a list of objects with the 'username' key), ignoring the
  remaining fields (password, groups, etc.).
  """
  usernames = []
  for item in data_list:
    if isinstance(item, str):
      username = item
    elif isinstance(item, dict):
      username = item.get("username")
    else:
      username = None

    if username:
      usernames.append(username)
    else:
      print(f"[-] Record skipped (missing username): {item}")
  return usernames


def process_batch_delete(data_list, output_summary_file=None):
  """Processes batch user deletion (accepts the original creation JSON)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processing User Deletion ---")
  for username in usernames:
    success = delete_user(username)
    results.append({"username": username, "deleted": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Consolidated report exported to: {output_summary_file}")

  return results


def process_batch_deactivate(data_list, output_summary_file=None):
  """Processes batch user deactivation (accepts the original creation JSON)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processing User Deactivation ---")
  for username in usernames:
    success = deactivate_user(username)
    results.append({"username": username, "deactivated": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Consolidated report exported to: {output_summary_file}")

  return results


def process_batch_activate(data_list, output_summary_file=None):
  """Processes batch user activation (accepts the original creation JSON)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processing User Activation ---")
  for username in usernames:
    success = activate_user(username)
    results.append({"username": username, "activated": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Consolidated report exported to: {output_summary_file}")

  return results


def main():
  parser = argparse.ArgumentParser(
      description=(
          "OpenTAKServer User, Group, and QR Code Manager"
      )
  )
  subparsers = parser.add_subparsers(
      dest="command", help="Available commands"
  )

  # Command: create-user
  cmd_user = subparsers.add_parser(
      "create-user",
      help="Creates user(s) and generates a QR Code (single or batch)",
  )
  create_target = cmd_user.add_mutually_exclusive_group(required=True)
  create_target.add_argument(
      "-u", "--username", help="Username (single creation)"
  )
  create_target.add_argument(
      "-f",
      "--file",
      help=(
          "Batch JSON file. Accepts the same format as"
          " 'users_sample.json', creating groups, users, group links, and"
          " QR Codes for each record."
      ),
  )
  cmd_user.add_argument(
      "-p",
      "--password",
      default=None,
      help="Password (required for single creation, i.e. with -u)",
  )
  cmd_user.add_argument("-e", "--email", default="", help="Email")
  cmd_user.add_argument(
      "-g",
      "--groups",
      nargs="*",
      default=[],
      help=(
          "List of groups. Supports individual direction: 'GROUP:IN',"
          " 'GROUP:OUT', or 'GROUP:BOTH' (default: BOTH)"
      ),
  )
  cmd_user.add_argument(
      "--admin", action="store_true", help="Administrator profile"
  )
  cmd_user.add_argument(
      "--app",
      choices=["android", "iphone"],
      default="android",
      help="Target app (default: android)",
  )
  cmd_user.add_argument(
      "--exp",
      default=None,
      help="Expiration date (YYYY-MM-DD or days). If omitted, it isn't sent.",
  )
  cmd_user.add_argument(
      "--max",
      type=int,
      default=None,
      help="Maximum activations. If omitted, it isn't sent.",
  )
  cmd_user.add_argument("--save-qr", help="Output PNG file path")
  cmd_user.add_argument(
      "-o",
      "--output",
      default="resultado_qr_codes.json",
      help="Output JSON file with the results (batch only)",
  )

  # Command: qr
  cmd_qr = subparsers.add_parser(
      "qr", help="Generates a QR Code for an existing user"
  )
  cmd_qr.add_argument("-u", "--username", required=True, help="Username")
  cmd_qr.add_argument(
      "--app",
      choices=["android", "iphone"],
      default="android",
      help="Target app (default: android)",
  )
  cmd_qr.add_argument(
      "--exp",
      default=None,
      help="Expiration (YYYY-MM-DD or days). If omitted, it isn't sent.",
  )
  cmd_qr.add_argument(
      "--max",
      type=int,
      default=None,
      help="Maximum activations. If omitted, it isn't sent.",
  )
  cmd_qr.add_argument("--save-qr", help="Output PNG file path")

  # Command: create-group
  cmd_group = subparsers.add_parser(
      "create-group", help="Creates a group via CLI"
  )
  cmd_group.add_argument("-n", "--name", required=True, help="Group name")

  # Command: delete-group
  cmd_delete_group = subparsers.add_parser(
      "delete-group", help="Removes an existing group"
  )
  cmd_delete_group.add_argument(
      "-n", "--name", required=True, help="Name of the group to remove"
  )

  # Command: list-groups
  subparsers.add_parser(
      "list-groups", help="Lists groups existing on OpenTAKServer"
  )

  # Command: list-users
  subparsers.add_parser(
      "list-users", help="Lists existing users with admin status and last login"
  )

  # Command: create-mission
  cmd_mission = subparsers.add_parser(
      "create-mission", help="Creates a mission (Data Sync) on OpenTAKServer"
  )
  cmd_mission.add_argument("-n", "--name", required=True, help="Mission name")
  mission_creator = cmd_mission.add_mutually_exclusive_group(required=True)
  mission_creator.add_argument(
      "--creator-uid",
      help="UID of the device (EUD) that will be registered as the mission's creator",
  )
  mission_creator.add_argument(
      "--creator-username",
      help=(
          "User whose first registered device (EUD) will be used as the"
          " mission's creator"
      ),
  )
  cmd_mission.add_argument(
      "-g",
      "--groups",
      nargs="*",
      default=[],
      help=(
          "Names of the groups to link to the mission. Accepts the special"
          " value 'ALL' to link every existing group."
      ),
  )
  cmd_mission.add_argument("--description", default=None, help="Mission description")
  cmd_mission.add_argument(
      "--classification", default=None, help="Mission classification"
  )
  cmd_mission.add_argument(
      "--tool", default=None, help="Associated tool (e.g. public)"
  )
  cmd_mission.add_argument(
      "--default-role", default=None, help="Default role for invitees"
  )
  cmd_mission.add_argument(
      "--password", default=None, help="Mission access password (makes it password-protected)"
  )
  cmd_mission.add_argument(
      "--keywords", nargs="*", default=None, help="Mission keywords"
  )
  cmd_mission.add_argument(
      "--chat-room", default=None, help="Name of the linked chat room"
  )
  cmd_mission.add_argument("--base-layer", default=None, help="Map base layer")
  cmd_mission.add_argument("--bbox", default=None, help="Mission bounding box")
  cmd_mission.add_argument("--path", default=None, help="Mission path/folder")
  cmd_mission.add_argument(
      "--invite-only",
      action="store_true",
      help="Makes the mission accessible by invitation only",
  )
  cmd_mission.add_argument(
      "--exp",
      default=None,
      help=(
          "Mission expiration (YYYY-MM-DD or days from now). If omitted, it"
          " isn't sent and the server uses its default (no expiration)."
      ),
  )

  # Command: delete-mission
  cmd_delete_mission = subparsers.add_parser(
      "delete-mission", help="Removes an existing mission"
  )
  cmd_delete_mission.add_argument(
      "-n", "--name", required=True, help="Name of the mission to remove"
  )

  # Command: list-missions
  subparsers.add_parser(
      "list-missions", help="Lists missions existing on OpenTAKServer"
  )

  # Command: link
  cmd_link = subparsers.add_parser("link", help="Associates a user with a group")
  cmd_link.add_argument(
      "-u", "--username", required=True, help="Username"
  )
  cmd_link.add_argument("-g", "--group", required=True, help="Group name")
  cmd_link.add_argument(
      "-d",
      "--direction",
      choices=["IN", "OUT", "BOTH"],
      default="BOTH",
      help="Association direction (default: BOTH)",
  )

  # Command: update-user
  cmd_update = subparsers.add_parser(
      "update-user",
      help=(
          "Updates an existing user: password, groups, and/or administrator"
          " role (single or batch)"
      ),
  )
  update_target = cmd_update.add_mutually_exclusive_group(required=True)
  update_target.add_argument(
      "-u", "--username", help="Name of the user to update"
  )
  update_target.add_argument(
      "-f",
      "--file",
      help=(
          "Batch JSON file. Accepts the same format as"
          " 'users_sample.json' used by create-user -f; for each record,"
          " only the fields present ('password', 'groups',"
          " 'administrator') are applied. The remaining creation fields"
          " (email, app, expiration, max_uses) don't apply and are ignored."
      ),
  )
  cmd_update.add_argument(
      "-p", "--password", default=None, help="New password (single mode)"
  )
  cmd_update.add_argument(
      "-g",
      "--groups",
      nargs="*",
      default=None,
      help=(
          "Full set of groups the user should end up with (single mode)."
          " Supports 'GROUP:IN'/'GROUP:OUT'/'GROUP:BOTH' and the special"
          " value 'ALL'. Current groups absent from this list are removed,"
          " and any missing ones are added. If omitted, group memberships"
          " aren't changed; use '-g' with no values to remove every current"
          " membership."
      ),
  )
  admin_toggle = cmd_update.add_mutually_exclusive_group()
  admin_toggle.add_argument(
      "--admin",
      action="store_true",
      help="Makes the user an administrator (single mode)",
  )
  admin_toggle.add_argument(
      "--no-admin",
      action="store_true",
      help="Removes the user's administrator role (single mode)",
  )
  cmd_update.add_argument(
      "-o",
      "--output",
      default=None,
      help="Output JSON file with the results (batch only)",
  )

  # Command: delete-user
  cmd_delete = subparsers.add_parser(
      "delete-user", help="Removes a user (single or batch)"
  )
  delete_target = cmd_delete.add_mutually_exclusive_group(required=True)
  delete_target.add_argument(
      "-u", "--username", help="Username to remove"
  )
  delete_target.add_argument(
      "-f",
      "--file",
      help=(
          "Batch JSON file. Accepts the same file used for batch creation,"
          " extracting only the 'username' field from each record."
      ),
  )
  cmd_delete.add_argument(
      "-o",
      "--output",
      default=None,
      help="Output JSON file with the results (batch only)",
  )

  # Command: deactivate-user
  cmd_deactivate = subparsers.add_parser(
      "deactivate-user", help="Deactivates a user (single or batch)"
  )
  deactivate_target = cmd_deactivate.add_mutually_exclusive_group(
      required=True
  )
  deactivate_target.add_argument(
      "-u", "--username", help="Username to deactivate"
  )
  deactivate_target.add_argument(
      "-f",
      "--file",
      help=(
          "Batch JSON file. Accepts the same file used for batch creation,"
          " extracting only the 'username' field from each record."
      ),
  )
  cmd_deactivate.add_argument(
      "-o",
      "--output",
      default=None,
      help="Output JSON file with the results (batch only)",
  )

  # Command: activate-user
  cmd_activate = subparsers.add_parser(
      "activate-user", help="Activates a user (single or batch)"
  )
  activate_target = cmd_activate.add_mutually_exclusive_group(required=True)
  activate_target.add_argument(
      "-u", "--username", help="Username to activate"
  )
  activate_target.add_argument(
      "-f",
      "--file",
      help=(
          "Batch JSON file. Accepts the same file used for batch creation,"
          " extracting only the 'username' field from each record."
      ),
  )
  cmd_activate.add_argument(
      "-o",
      "--output",
      default=None,
      help="Output JSON file with the results (batch only)",
  )

  args = parser.parse_args()

  if not args.command:
    parser.print_help()
    sys.exit(1)

  if not login():
    sys.exit(1)

  if args.command == "create-user":
    if args.file:
      ignored_flags = []
      if args.password is not None:
        ignored_flags.append("-p/--password")
      if args.email:
        ignored_flags.append("-e/--email")
      if args.groups:
        ignored_flags.append("-g/--groups")
      if args.admin:
        ignored_flags.append("--admin")
      if args.app != "android":
        ignored_flags.append("--app")
      if args.exp is not None:
        ignored_flags.append("--exp")
      if args.max is not None:
        ignored_flags.append("--max")
      if args.save_qr is not None:
        ignored_flags.append("--save-qr")

      if ignored_flags:
        print(
            "[!] Batch mode (-f/--file) active: the parameters"
            f" {', '.join(ignored_flags)} will be ignored. Set those"
            " values per record inside the JSON file."
        )

      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_list(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Error processing batch file: {e}")
    else:
      if not args.password:
        print(
            "[-] The -p/--password parameter is required for single user"
            " creation (used with -u/--username)."
        )
        sys.exit(1)

      parsed_groups = [parse_group_entry(g) for g in args.groups]

      # Create the groups first (skip ALL, which will be expanded)
      for g_name, _ in parsed_groups:
        if g_name and str(g_name).upper() != "ALL":
          create_group(g_name)

      # Create the user and link it in the specified directions
      if create_user(args.username, args.password, args.email, args.admin):
        for g_name, g_dir in parsed_groups:
          if g_name:
            if str(g_name).upper() == "ALL":
              existing = list_groups()
              for ex in existing:
                add_user_to_group(args.username, ex, direction=g_dir)
            else:
              add_user_to_group(args.username, g_name, direction=g_dir)

        exp_ts = parse_expiration(args.exp)
        qr_string = get_qr_string(
            username=args.username,
            app_type=args.app,
            exp_timestamp=exp_ts,
            max_uses=args.max,
        )
        if qr_string:
          print(f"[+] QR String generated: {qr_string}")
          output_file = args.save_qr or f"qrcodes/{args.username}_{args.app}.png"
          save_qr_code_image(qr_string, output_file)

  elif args.command == "qr":
    exp_ts = parse_expiration(args.exp)
    qr_string = get_qr_string(
        username=args.username,
        app_type=args.app,
        exp_timestamp=exp_ts,
        max_uses=args.max,
    )
    if qr_string:
      print(f"[+] QR String generated: {qr_string}")
      output_file = args.save_qr or f"qrcodes/{args.username}_{args.app}.png"
      save_qr_code_image(qr_string, output_file)

  elif args.command == "create-group":
    create_group(args.name)

  elif args.command == "delete-group":
    delete_group(args.name)

  elif args.command == "list-groups":
    groups = list_groups()
    if groups:
      print(f"[+] Existing groups ({len(groups)} total):")
      for g in groups:
        print(f" - {g}")
    else:
      print("[!] No groups found or an error occurred while listing.")

  elif args.command == "list-users":
    users = list_users()
    if users:
      print(f"[+] Existing users ({len(users)} total):")
      for user in users:
        admin_flag = "YES" if user.get("admin") else "NO"
        last_login = user.get("last_login") or "N/A"
        print(
            f" - {user.get('username')} | admin={admin_flag} | "
            f"last_login={last_login}"
        )
    else:
      print("[!] No users found, or the API doesn't expose this data.")

  elif args.command == "create-mission":
    creator_uid = args.creator_uid
    if not creator_uid:
      creator_uid = get_creator_uid_for_username(args.creator_username)
      if not creator_uid:
        print(
            "[-] No device (EUD) found for user"
            f" '{args.creator_username}'. Provide --creator-uid directly."
        )
        sys.exit(1)

    exp_ts = parse_expiration(args.exp)

    create_mission(
        args.name,
        creator_uid,
        description=args.description,
        groups=args.groups,
        tool=args.tool,
        classification=args.classification,
        default_role=args.default_role,
        password=args.password,
        keywords=args.keywords,
        chat_room=args.chat_room,
        base_layer=args.base_layer,
        bbox=args.bbox,
        path=args.path,
        invite_only=args.invite_only,
        expiration=exp_ts,
    )

  elif args.command == "delete-mission":
    delete_mission(args.name)

  elif args.command == "list-missions":
    missions = list_missions()
    if missions:
      print(f"[+] Existing missions ({len(missions)} total):")
      for m in missions:
        print(f" - {m}")
    else:
      print("[!] No missions found or an error occurred while listing.")

  elif args.command == "link":
    if str(args.group).upper() == "ALL":
      existing = list_groups()
      for ex in existing:
        add_user_to_group(args.username, ex, direction=args.direction)
    else:
      add_user_to_group(args.username, args.group, direction=args.direction)

  elif args.command == "update-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_update(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Error processing batch update file: {e}")
    else:
      is_admin = None
      if args.admin:
        is_admin = True
      elif args.no_admin:
        is_admin = False

      update_user(
          args.username,
          password=args.password,
          groups=args.groups,
          is_admin=is_admin,
      )

  elif args.command == "delete-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_delete(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Error processing batch deletion file: {e}")
    else:
      delete_user(args.username)

  elif args.command == "deactivate-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_deactivate(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Error processing batch deactivation file: {e}")
    else:
      deactivate_user(args.username)

  elif args.command == "activate-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_activate(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Error processing batch activation file: {e}")
    else:
      activate_user(args.username)


if __name__ == "__main__":
  main()
