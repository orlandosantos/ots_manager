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


def add_user_to_group(username, group_name, direction="BOTH"):
  """Associa um usuário a um grupo no OpenTAKServer (IN e OUT)."""
  url = f"{OTS_URL}/api/users/groups"
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
  """Converte expiração em Unix Epoch timestamp se informada.

  Caso contrário, retorna None.
  """
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


def process_batch_list(
    data_list, output_summary_file="resultado_qr_codes.json"
):
  """Processa lote de usuários/grupos e exporta arquivos PNG e JSON consolidado."""
  os.makedirs("qrcodes", exist_ok=True)
  summary_results = []

  groups_to_create = set()
  for item in data_list:
    for g in item.get("groups", []):
      groups_to_create.add(g)

  print("\n--- Processando Grupos ---")
  for group_name in groups_to_create:
    create_group(group_name)

  print("\n--- Processando Usuários e Gerando QR Codes ---")
  for user_info in data_list:
    username = user_info.get("username")
    password = user_info.get("password")
    email = user_info.get("email", "")
    is_admin = user_info.get("administrator", False)
    user_groups = user_info.get("groups", [])
    app_type = user_info.get("app", "android").lower()
    max_uses = user_info.get("max_uses")
    expiration = user_info.get("expiration")

    if not username or not password:
      print(f"[-] Registro ignorado (dados ausentes): {user_info}")
      continue

    created = create_user(username, password, email, is_admin)
    if created:
      for group_name in user_groups:
        add_user_to_group(username, group_name, direction="BOTH")

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
      "create-user", help="Cria usuário e gera QR Code"
  )
  cmd_user.add_argument(
      "-u", "--username", required=True, help="Nome de usuário"
  )
  cmd_user.add_argument("-p", "--password", required=True, help="Senha")
  cmd_user.add_argument("-e", "--email", default="", help="E-mail")
  cmd_user.add_argument("-g", "--groups", nargs="*", default=[], help="Grupos")
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
      help=(
          "Data de expiração (YYYY-MM-DD ou dias). Se omitido, não é enviado ao"
          " servidor."
      ),
  )
  cmd_user.add_argument(
      "--max",
      type=int,
      default=None,
      help=(
          "Quantidade máxima de ativações. Se omitido, não é enviado ao"
          " servidor."
      ),
  )
  cmd_user.add_argument("--save-qr", help="Caminho do arquivo PNG de saída")

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
      help=(
          "Expiração (YYYY-MM-DD ou dias). Se omitido, não é enviado ao"
          " servidor."
      ),
  )
  cmd_qr.add_argument(
      "--max",
      type=int,
      default=None,
      help="Máximo de ativações. Se omitido, não é enviado ao servidor.",
  )
  cmd_qr.add_argument("--save-qr", help="Caminho do arquivo PNG de saída")

  # Comando: create-group
  cmd_group = subparsers.add_parser(
      "create-group", help="Cria um grupo via CLI"
  )
  cmd_group.add_argument("-n", "--name", required=True, help="Nome do grupo")

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

  # Comando: batch
  cmd_batch = subparsers.add_parser(
      "batch", help="Processa arquivo JSON em lote"
  )
  cmd_batch.add_argument(
      "-f", "--file", required=True, help="Arquivo JSON de entrada"
  )
  cmd_batch.add_argument(
      "-o",
      "--output",
      default="resultado_qr_codes.json",
      help="Arquivo JSON de saída com os resultados",
  )

  args = parser.parse_args()

  if not args.command:
    parser.print_help()
    sys.exit(1)

  if not login():
    sys.exit(1)

  if args.command == "create-user":
    for g in args.groups:
      create_group(g)
    if create_user(args.username, args.password, args.email, args.admin):
      for g in args.groups:
        add_user_to_group(args.username, g, direction="BOTH")

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

  elif args.command == "link":
    add_user_to_group(args.username, args.group, direction=args.direction)

  elif args.command == "batch":
    try:
      with open(args.file, "r", encoding="utf-8") as f:
        data_list = json.load(f)
      process_batch_list(data_list, output_summary_file=args.output)
    except Exception as e:
      print(f"[-] Erro ao processar arquivo batch: {e}")


if __name__ == "__main__":
  main()
