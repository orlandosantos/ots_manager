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

session = requests.Session()
# Headers globais necessários para contornar validações do Flask-Security/WTF
session.headers.update({
    "Content-Type": "application/json",
    "Referer": f"{OTS_URL}/",
    "Origin": OTS_URL,
})


def get_csrf_token():
  """Recupera o token CSRF armazenado nos cookies da sessão Flask."""
  return (
      session.cookies.get("csrf_token")
      or session.cookies.get("csrf_access_token")
      or session.cookies.get("XSRF-TOKEN")
  )


def login():
  """Realiza autenticação no OpenTAKServer e captura o token CSRF da sessão."""
  login_url = f"{OTS_URL}/api/login"
  payload = {"username": API_USERNAME, "password": API_PASSWORD}

  try:
    response = session.post(login_url, json=payload, timeout=10)

    if response.status_code in [200, 201]:
      print("[+] Autenticado com sucesso no OpenTAKServer.")

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
          f"[-] Falha na autenticação: {response.status_code} - {response.text}"
      )
      return False
  except Exception as e:
    print(f"[-] Erro ao conectar ao servidor: {e}")
    return False


def create_group(group_name):
  """Cria um grupo no OpenTAKServer (POST /api/groups)."""
  url = f"{OTS_URL}/api/groups"
  payload = {"name": group_name}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] Grupo '{group_name}' criado com sucesso.")
    return True
  elif response.status_code == 400 and "exists" in response.text.lower():
    print(f"[!] O grupo '{group_name}' já existe.")
    return True
  else:
    print(
        f"[-] Erro ao criar grupo '{group_name}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def list_groups():
  """Retorna lista de nomes de grupos existentes no OpenTAKServer."""
  url = f"{OTS_URL}/api/groups"
  try:
    response = session.get(url, timeout=10)
    if response.status_code == 200:
      try:
        data = response.json()
      except Exception:
        data = None

      groups = []
      if isinstance(data, dict):
        # tenta localizar chaves comuns
        if "groups" in data and isinstance(data["groups"], list):
          groups = data["groups"]
        elif "results" in data and isinstance(data["results"], list):
          groups = data["results"]
        else:
          for v in data.values():
            if isinstance(v, list):
              groups = v
              break
      elif isinstance(data, list):
        groups = data

      names = []
      for g in groups:
        if isinstance(g, str):
          names.append(g)
        elif isinstance(g, dict):
          name = g.get("name") or g.get("group") or g.get("groupname")
          if name:
            names.append(name)
      return names
    else:
      print(f"[-] Erro ao listar grupos: {response.status_code} - {response.text}")
      return []
  except Exception as e:
    print(f"[-] Erro ao conectar para listar grupos: {e}")
    return []


def _normalize_admin_flag(value):
  """Converte diferentes representações de administrador para booleano."""
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
  """Converte datas/epoch em ISO string legível para exibição."""
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


def list_users():
  """Lista usuários e tenta extrair admin e último login quando disponíveis."""
  endpoints = [
      f"{OTS_URL}/api/users",
      f"{OTS_URL}/api/user",
      f"{OTS_URL}/api/user/list",
  ]

  for endpoint in endpoints:
    try:
      response = session.get(endpoint, timeout=10)
      if response.status_code != 200:
        continue

      try:
        payload = response.json()
      except Exception:
        payload = None

      item_list = []
      if isinstance(payload, list):
        item_list = payload
      elif isinstance(payload, dict):
        for key in ["users", "results", "data", "items", "records"]:
          value = payload.get(key)
          if isinstance(value, list):
            item_list = value
            break
        if not item_list and isinstance(payload.get("user"), dict):
          item_list = [payload.get("user")]

      users = []
      for entry in item_list:
        if not isinstance(entry, dict):
          continue

        username = (
            entry.get("username")
            or entry.get("user")
            or entry.get("login")
            or entry.get("name")
        )
        if not username:
          continue

        # Tentativa primeira: flags diretas
        admin_field = (
            entry.get("administrator")
            or entry.get("admin")
            or entry.get("is_admin")
            or entry.get("isAdministrator")
            or entry.get("role")
        )
        admin = _normalize_admin_flag(admin_field)

        # Se existir uma lista de roles, inspeciona nome e permissões
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

        users.append({
            "username": username,
            "admin": admin,
            "last_login": last_login,
        })

      if users:
        return users

    except Exception:
      continue

  return []


def create_user(username, password, email="", is_admin=False):
  """Cria um usuário no OpenTAKServer (POST /api/user/add)."""
  url = f"{OTS_URL}/api/user/add"
  payload = {
      "username": username,
      "password": password,
      "confirm_password": password,
      "email": email,
      "administrator": is_admin,
  }

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201]:
    print(f"[+] Usuário '{username}' criado com sucesso.")
    return True
  elif response.status_code == 400 and "exists" in response.text.lower():
    print(f"[!] O usuário '{username}' já existe.")
    return True
  else:
    print(
        f"[-] Erro ao criar usuário '{username}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def delete_user(username):
  """Remove um usuário do OpenTAKServer (POST /api/user/delete)."""
  url = f"{OTS_URL}/api/user/delete"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] Usuário '{username}' removido com sucesso.")
    return True
  elif response.status_code == 404:
    print(f"[!] O usuário '{username}' não foi encontrado.")
    return True
  else:
    print(
        f"[-] Erro ao remover usuário '{username}': {response.status_code} -"
        f" {response.text}"
    )
    return False


def deactivate_user(username):
  """Desativa um usuário no OpenTAKServer (POST /api/user/deactivate)."""
  url = f"{OTS_URL}/api/user/deactivate"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] Usuário '{username}' desativado com sucesso.")
    return True
  elif response.status_code == 404:
    print(f"[!] O usuário '{username}' não foi encontrado.")
    return True
  else:
    print(
        f"[-] Erro ao desativar usuário '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def activate_user(username):
  """Habilita um usuário no OpenTAKServer (POST /api/user/activate)."""
  url = f"{OTS_URL}/api/user/activate"
  payload = {"username": username}

  csrf = get_csrf_token()
  headers = {"X-CSRFToken": csrf, "X-CSRF-TOKEN": csrf} if csrf else {}

  response = session.post(url, json=payload, headers=headers)
  if response.status_code in [200, 201, 204]:
    print(f"[+] Usuário '{username}' habilitado com sucesso.")
    return True
  elif response.status_code == 404:
    print(f"[!] O usuário '{username}' não foi encontrado.")
    return True
  else:
    print(
        f"[-] Erro ao habilitar usuário '{username}': {response.status_code}"
        f" - {response.text}"
    )
    return False


def add_user_to_group(username, group_name, direction="BOTH"):
  """Associa um usuário a um grupo no OpenTAKServer (IN, OUT ou BOTH)."""
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
          f"[+] Usuário '{username}' associado ao grupo '{group_name}'"
          f" ({dir_type})."
      )
    else:
      print(
          f"[-] Erro ao associar '{username}' ao grupo '{group_name}'"
          f" ({dir_type}): {response.status_code}"
      )
      success = False
  return success


def parse_expiration(exp_val):
  """Converte expiração em Unix Epoch timestamp se informada."""
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
    print(f"[-] Formato de data inválido ({exp_val}): {e}")
    return None


def get_qr_string(
    username, app_type="android", exp_timestamp=None, max_uses=None
):
  """Obtém a string do QR code para Android ou iPhone com Referer e CSRF."""
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
          f"[-] Erro ao gerar QR Android para '{username}':"
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
          f"[-] Erro ao obter QR iPhone: {response.status_code} -"
          f" {response.text}"
      )
      return None
  else:
    print(
        f"[-] Opção de aplicativo inválida: '{app_type}'. Escolha entre"
        " 'android' ou 'iphone'."
    )
    return None


def save_qr_code_image(qr_data, output_path):
  """Gera uma imagem PNG a partir da string do QR Code."""
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
  print(f"[+] QR Code salvo em: {output_path}")


def parse_group_entry(item):
  """Normaliza entradas de grupo vindas de strings CLI ('CSAR:IN' ou 'CSAR')

  ou objetos JSON ({"name": "CSAR", "direction": "IN"}).
  Retorna tupla: (group_name, direction).
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
  """Processa lote de usuários/grupos com suporte a direções individuais."""
  os.makedirs("qrcodes", exist_ok=True)
  summary_results = []

  # 1. Coleta grupos únicos para criação prévia
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

  print("\n--- Processando Grupos ---")
  for group_name in groups_to_create:
    create_group(group_name)

  # 2. Criação de Usuários e Vínculos
  print("\n--- Processando Usuários e Gerando QR Codes ---")
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
      print(f"[-] Registro ignorado (dados ausentes): {user_info}")
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
              max_uses if max_uses is not None else "padrão do servidor"
          ),
          "expiration": (
              expiration if expiration is not None else "padrão do servidor"
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
  print(f"\n[+] Relatório consolidado exportado para: {output_summary_file}")


def extract_usernames(data_list):
  """Extrai somente os nomes de usuário de um lote.

  Aceita tanto uma lista de strings quanto o mesmo arquivo JSON original
  usado para criação (lista de objetos com a chave 'username'), ignorando
  os demais campos (senha, grupos, etc.).
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
      print(f"[-] Registro ignorado (username ausente): {item}")
  return usernames


def process_batch_delete(data_list, output_summary_file=None):
  """Processa remoção em lote de usuários (aceita o JSON original de criação)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processando Remoção de Usuários ---")
  for username in usernames:
    success = delete_user(username)
    results.append({"username": username, "deleted": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Relatório consolidado exportado para: {output_summary_file}")

  return results


def process_batch_deactivate(data_list, output_summary_file=None):
  """Processa desativação em lote de usuários (aceita o JSON original de criação)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processando Desativação de Usuários ---")
  for username in usernames:
    success = deactivate_user(username)
    results.append({"username": username, "deactivated": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Relatório consolidado exportado para: {output_summary_file}")

  return results


def process_batch_activate(data_list, output_summary_file=None):
  """Processa habilitação em lote de usuários (aceita o JSON original de criação)."""
  usernames = extract_usernames(data_list)
  results = []

  print("\n--- Processando Habilitação de Usuários ---")
  for username in usernames:
    success = activate_user(username)
    results.append({"username": username, "activated": success})

  if output_summary_file:
    with open(output_summary_file, "w", encoding="utf-8") as f:
      json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Relatório consolidado exportado para: {output_summary_file}")

  return results


def main():
  parser = argparse.ArgumentParser(
      description=(
          "Gerenciador de Usuários, Grupos e QR Codes para OpenTAKServer"
      )
  )
  subparsers = parser.add_subparsers(
      dest="command", help="Comandos disponíveis"
  )

  # Comando: create-user
  cmd_user = subparsers.add_parser(
      "create-user",
      help="Cria usuário(s) e gera QR Code (individual ou em lote)",
  )
  create_target = cmd_user.add_mutually_exclusive_group(required=True)
  create_target.add_argument(
      "-u", "--username", help="Nome de usuário (criação individual)"
  )
  create_target.add_argument(
      "-f",
      "--file",
      help=(
          "Arquivo JSON em lote. Aceita o mesmo formato de"
          " 'users_sample.json', criando grupos, usuários, vínculos e QR"
          " Codes para cada registro."
      ),
  )
  cmd_user.add_argument(
      "-p",
      "--password",
      default=None,
      help="Senha (obrigatório na criação individual, ou seja, com -u)",
  )
  cmd_user.add_argument("-e", "--email", default="", help="E-mail")
  cmd_user.add_argument(
      "-g",
      "--groups",
      nargs="*",
      default=[],
      help=(
          "Lista de grupos. Suporta direção individual: 'GRUPO:IN',"
          " 'GRUPO:OUT' ou 'GRUPO:BOTH' (padrão: BOTH)"
      ),
  )
  cmd_user.add_argument(
      "--admin", action="store_true", help="Perfil Administrador"
  )
  cmd_user.add_argument(
      "--app",
      choices=["android", "iphone"],
      default="android",
      help="Aplicativo alvo (padrão: android)",
  )
  cmd_user.add_argument(
      "--exp",
      default=None,
      help="Data de expiração (YYYY-MM-DD ou dias). Se omitido, não é enviado.",
  )
  cmd_user.add_argument(
      "--max",
      type=int,
      default=None,
      help="Máximo de ativações. Se omitido, não é enviado.",
  )
  cmd_user.add_argument("--save-qr", help="Caminho do arquivo PNG de saída")
  cmd_user.add_argument(
      "-o",
      "--output",
      default="resultado_qr_codes.json",
      help="Arquivo JSON de saída com os resultados (somente em lote)",
  )

  # Comando: qr
  cmd_qr = subparsers.add_parser(
      "qr", help="Gera QR Code para usuário existente"
  )
  cmd_qr.add_argument("-u", "--username", required=True, help="Nome de usuário")
  cmd_qr.add_argument(
      "--app",
      choices=["android", "iphone"],
      default="android",
      help="Aplicativo alvo (padrão: android)",
  )
  cmd_qr.add_argument(
      "--exp",
      default=None,
      help="Expiração (YYYY-MM-DD ou dias). Se omitido, não é enviado.",
  )
  cmd_qr.add_argument(
      "--max",
      type=int,
      default=None,
      help="Máximo de ativações. Se omitido, não é enviado.",
  )
  cmd_qr.add_argument("--save-qr", help="Caminho do arquivo PNG de saída")

  # Comando: create-group
  cmd_group = subparsers.add_parser(
      "create-group", help="Cria um grupo via CLI"
  )
  cmd_group.add_argument("-n", "--name", required=True, help="Nome do grupo")

  # Comando: list-groups
  subparsers.add_parser(
      "list-groups", help="Lista grupos existentes no OpenTAKServer"
  )

  # Comando: list-users
  subparsers.add_parser(
      "list-users", help="Lista usuários existentes com admin e último login"
  )

  # Comando: link
  cmd_link = subparsers.add_parser("link", help="Associa usuário a um grupo")
  cmd_link.add_argument(
      "-u", "--username", required=True, help="Nome de usuário"
  )
  cmd_link.add_argument("-g", "--group", required=True, help="Nome do grupo")
  cmd_link.add_argument(
      "-d",
      "--direction",
      choices=["IN", "OUT", "BOTH"],
      default="BOTH",
      help="Direção da associação (padrão: BOTH)",
  )

  # Comando: delete-user
  cmd_delete = subparsers.add_parser(
      "delete-user", help="Remove um usuário (individual ou em lote)"
  )
  delete_target = cmd_delete.add_mutually_exclusive_group(required=True)
  delete_target.add_argument(
      "-u", "--username", help="Nome de usuário a remover"
  )
  delete_target.add_argument(
      "-f",
      "--file",
      help=(
          "Arquivo JSON em lote. Aceita o mesmo arquivo usado em 'batch',"
          " extraindo somente o campo 'username' de cada registro."
      ),
  )
  cmd_delete.add_argument(
      "-o",
      "--output",
      default=None,
      help="Arquivo JSON de saída com os resultados (somente em lote)",
  )

  # Comando: deactivate-user
  cmd_deactivate = subparsers.add_parser(
      "deactivate-user", help="Desativa um usuário (individual ou em lote)"
  )
  deactivate_target = cmd_deactivate.add_mutually_exclusive_group(
      required=True
  )
  deactivate_target.add_argument(
      "-u", "--username", help="Nome de usuário a desativar"
  )
  deactivate_target.add_argument(
      "-f",
      "--file",
      help=(
          "Arquivo JSON em lote. Aceita o mesmo arquivo usado em 'batch',"
          " extraindo somente o campo 'username' de cada registro."
      ),
  )
  cmd_deactivate.add_argument(
      "-o",
      "--output",
      default=None,
      help="Arquivo JSON de saída com os resultados (somente em lote)",
  )

  # Comando: activate-user
  cmd_activate = subparsers.add_parser(
      "activate-user", help="Habilita um usuário (individual ou em lote)"
  )
  activate_target = cmd_activate.add_mutually_exclusive_group(required=True)
  activate_target.add_argument(
      "-u", "--username", help="Nome de usuário a habilitar"
  )
  activate_target.add_argument(
      "-f",
      "--file",
      help=(
          "Arquivo JSON em lote. Aceita o mesmo arquivo usado em 'batch',"
          " extraindo somente o campo 'username' de cada registro."
      ),
  )
  cmd_activate.add_argument(
      "-o",
      "--output",
      default=None,
      help="Arquivo JSON de saída com os resultados (somente em lote)",
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
            "[!] Modo lote (-f/--file) ativo: os parâmetros"
            f" {', '.join(ignored_flags)} serão ignorados. Defina esses"
            " valores por registro dentro do arquivo JSON."
        )

      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_list(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Erro ao processar arquivo batch: {e}")
    else:
      if not args.password:
        print(
            "[-] O parâmetro -p/--password é obrigatório na criação"
            " individual de usuário (uso com -u/--username)."
        )
        sys.exit(1)

      parsed_groups = [parse_group_entry(g) for g in args.groups]

      # Cria os grupos primeiro (ignora ALL, que será expandido)
      for g_name, _ in parsed_groups:
        if g_name and str(g_name).upper() != "ALL":
          create_group(g_name)

      # Cria o usuário e associa nas direções especificadas
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
          print(f"[+] QR String gerada: {qr_string}")
          output_file = args.save_qr or f"{args.username}_{args.app}.png"
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
      print(f"[+] QR String gerada: {qr_string}")
      output_file = args.save_qr or f"{args.username}_{args.app}.png"
      save_qr_code_image(qr_string, output_file)

  elif args.command == "create-group":
    create_group(args.name)

  elif args.command == "list-groups":
    groups = list_groups()
    if groups:
      print("[+] Grupos existentes:")
      for g in groups:
        print(f" - {g}")
    else:
      print("[!] Nenhum grupo encontrado ou erro ao listar.")

  elif args.command == "list-users":
    users = list_users()
    if users:
      print("[+] Usuários existentes:")
      for user in users:
        admin_flag = "SIM" if user.get("admin") else "NÃO"
        last_login = user.get("last_login") or "N/A"
        print(
            f" - {user.get('username')} | admin={admin_flag} | "
            f"ultimo_login={last_login}"
        )
    else:
      print("[!] Nenhum usuário encontrado ou a API não expõe esse dado.")

  elif args.command == "link":
    if str(args.group).upper() == "ALL":
      existing = list_groups()
      for ex in existing:
        add_user_to_group(args.username, ex, direction=args.direction)
    else:
      add_user_to_group(args.username, args.group, direction=args.direction)

  elif args.command == "delete-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_delete(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Erro ao processar arquivo de remoção em lote: {e}")
    else:
      delete_user(args.username)

  elif args.command == "deactivate-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_deactivate(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Erro ao processar arquivo de desativação em lote: {e}")
    else:
      deactivate_user(args.username)

  elif args.command == "activate-user":
    if args.file:
      try:
        with open(args.file, "r", encoding="utf-8") as f:
          data_list = json.load(f)
        process_batch_activate(data_list, output_summary_file=args.output)
      except Exception as e:
        print(f"[-] Erro ao processar arquivo de habilitação em lote: {e}")
    else:
      activate_user(args.username)


if __name__ == "__main__":
  main()