# OTS Manager CLI & Batch

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Language: Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)

A Python command-line utility for automating identity, group, and QR Code management in [OpenTAKServer](https://github.com/brian7704/OpenTAKServer) through its REST API.

## Project description

OTS Manager simplifies and standardizes OpenTAKServer administration by providing commands for:

- authenticating through `/api/login`;
- maintaining a requests session with cookies;
- handling CSRF tokens and `Referer`/`Origin` headers;
- creating groups and users;
- associating users with groups in both `IN` and `OUT` directions;
- generating Android ATAK and iPhone iTAK QR Code configuration strings;
- creating PNG QR Codes;
- provisioning multiple users from a JSON file;
- exporting a consolidated JSON report.

> **Version:** 1.0  
> **Author:** Orlando Nascimento Santos  
> **Email:** [onascimento@gmail.com](mailto:onascimento@gmail.com)  
> **License:** MIT

## Important security notice

The example server URL uses HTTP and an IP address. For production environments:

- prefer HTTPS with a valid certificate;
- restrict access through a firewall or VPN;
- use a dedicated account with the least privilege necessary;
- never commit passwords, tokens, QR strings, generated PNGs, or real personal data;
- protect the generated QR Codes because they may provision a device;
- rotate service-account passwords regularly.

## Requirements

- Python 3.9 or later;
- network access to OpenTAKServer;
- an OTS account authorized to create users and groups;
- write permission in the working directory;
- `pip`.

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install requests qrcode pillow
```

Suggested project structure:

```text
ots-manager/
├── ots_manager.py
├── usuarios.json
├── qrcodes/
├── resultado_qr_codes.json
└── .venv/
```

## Configuration

Set the OTS connection variables before running the utility:

```bash
export OTS_URL="http://opentakserver.example.com:5000"
export OTS_USER="admin"
export OTS_PASS="your_password_here"
```

| Variable | Default in the script | Recommendation |
|---|---|---|
| `OTS_URL` | `http://localhost:5000` | Always set explicitly |
| `OTS_USER` | `admin` | Use a named or service account |
| `OTS_PASS` | `admin_password` | Never rely on the default |

Connectivity test:

```bash
curl -i "$OTS_URL/"
```

To avoid exposing the password in shell history:

```bash
read -r -s OTS_PASS
export OTS_PASS
```

## Required and optional fields

The following table describes the fields used by the API and CLI.

| Operation | Required fields | Optional fields and defaults |
|---|---|---|
| Login — `/api/login` | `username`, `password` | No request fields are optional. Values come from `OTS_USER` and `OTS_PASS`. |
| Create group — `/api/groups` | `name` | None. |
| Create user — `/api/user/add` | `username`, `password`, `confirm_password` | `email` is **not required** and may be omitted or empty. `administrator` defaults to `false`. `confirm_password` is generated automatically by the script. |
| Link group — `/api/users/groups` | `username`, `groups[]`, `direction` | In the CLI, `direction` defaults to `BOTH`, which performs one `IN` and one `OUT` request. |
| Android QR — `/api/atak_qr_string` | `username` | `exp` and `max` are **not required**. `nbf` is generated automatically only when `exp` is supplied. If `exp` and `max` are omitted or `null`, they are not sent and the OTS server policy applies. |
| iPhone QR — `/api/itak_qr_string` | Authenticated session | The `GET` request has no user-supplied fields; the configuration is returned by the server. |
| CLI `create-user` | `--username`, `--password` | `--email`, `--groups`, `--admin`, `--app`, `--exp`, `--max`, and `--save-qr` are optional. `--app` defaults to `android`; `--admin` defaults to false. |
| CLI `qr` | `--username` | `--app`, `--exp`, `--max`, and `--save-qr` are optional. `--app` defaults to `android`. |
| CLI `create-group` | `--name` | None. |
| CLI `link` | `--username`, `--group` | `--direction` defaults to `BOTH`. |
| CLI `batch` | `--file` | `--output` defaults to `resultado_qr_codes.json`. Each user record requires `username` and `password`; all other record fields are optional. |

### Batch user fields

| JSON field | Required? | Description |
|---|---:|---|
| `username` | **Yes** | User identifier in OTS. |
| `password` | **Yes** | Initial password. The script also sends `confirm_password` with the same value. |
| `email` | **No** | May be omitted, set to `null`, or set to an empty string, subject to the OTS installation's validation rules. |
| `administrator` | **No** | Defaults to `false`. |
| `groups` | **No** | Group list. Each listed group is associated in `IN` and `OUT`. |
| `app` | **No** | Defaults to `android`; also accepts `iphone`. |
| `expiration` | **No** | Number of days or a `YYYY-MM-DD` date. If omitted or `null`, no expiration is sent. |
| `max_uses` | **No** | Maximum activation count. If omitted or `null`, no limit is sent. |

> `email`, `expiration`, and `max_uses` are not required. The absence of these fields does not prevent user creation or QR Code generation. `username` and `password` are required for every user. `confirm_password` is required by the API but is generated automatically by the script.

## REST API mapping

| Operation | Endpoint | Method | Main data |
|---|---|---:|---|
| Authentication | `/api/login` | `POST` | `username`, `password` |
| Create group | `/api/groups` | `POST` | `name` |
| Create user | `/api/user/add` | `POST` | `username`, `password`, `confirm_password`, `email`, `administrator` |
| Link group | `/api/users/groups` | `PUT` | `username`, `groups[]`, `direction` |
| Android QR Code | `/api/atak_qr_string` | `POST` | `username`, optional `exp`, `nbf`, `max` |
| iPhone QR Code | `/api/itak_qr_string` | `GET` | Returned by the server |

Protected operations require the authenticated session and may require CSRF headers:

```http
Content-Type: application/json
Referer: <OTS_URL>/
Origin: <OTS_URL>
X-CSRFToken: <token>
X-CSRF-TOKEN: <token>
```

## CLI usage

Display help:

```bash
python ots_manager.py --help
python ots_manager.py create-user --help
python ots_manager.py qr --help
```

### Create a user and an Android QR Code

```bash
python ots_manager.py create-user \
  --username "pilot1" \
  --password "StrongPassword123!" \
  --groups CSAR \
  --app android
```

### Create a user and an iPhone QR Code

```bash
python ots_manager.py create-user \
  --username "pilot2" \
  --password "StrongPassword123!" \
  --groups CSAR \
  --app iphone
```

### Create a user with an optional email and administrator profile

```bash
python ots_manager.py create-user \
  --username "operator" \
  --password "StrongPassword123!" \
  --email "operator@example.com" \
  --app android
```

Use `--admin` only when administrator privileges are required.

### Set expiration and activation limit

Both options are optional:

```bash
# Expires in 30 days and allows one activation
python ots_manager.py create-user \
  --username "guest" \
  --password "StrongPassword123!" \
  --groups Visitors \
  --app android \
  --exp 30 \
  --max 1
```

An absolute date is also supported:

```bash
python ots_manager.py qr \
  --username "pilot1" \
  --app android \
  --exp 2026-12-31 \
  --max 2
```

If `--exp` and `--max` are omitted, they are not sent and the server applies its default policy.

### Generate a QR Code for an existing user

```bash
python ots_manager.py qr --username "pilot1" --app android
python ots_manager.py qr --username "pilot2" --app iphone --save-qr pilot2_ios.png
```

### Create a group

```bash
python ots_manager.py create-group --name "Patrol"
```

### Link a user to a group

By default, the command links in both directions:

```bash
python ots_manager.py link --username "pilot1" --group "Patrol"
```

Specific direction:

```bash
python ots_manager.py link --username "pilot1" --group "Patrol" --direction IN
python ots_manager.py link --username "pilot1" --group "Patrol" --direction OUT
```

## Batch provisioning

Create `usuarios.json`:

```json
[
  {
    "username": "operator_alpha",
    "password": "StrongPassword123!",
    "groups": ["CSAR", "Rescue"],
    "app": "android"
  },
  {
    "username": "operator_bravo",
    "password": "StrongPassword456!",
    "email": "bravo@example.com",
    "administrator": false,
    "groups": ["CSAR"],
    "app": "iphone"
  },
  {
    "username": "temporary_operator",
    "password": "TemporaryPassword789!",
    "groups": ["Operations"],
    "app": "android",
    "expiration": 30,
    "max_uses": 1
  }
]
```

The `email`, `expiration`, and `max_uses` keys are optional. If omitted or set to `null`, the corresponding restrictions are not sent to the server.

Run the batch:

```bash
python ots_manager.py batch \
  --file usuarios.json \
  --output resultado_qr_codes.json
```

The batch process:

1. creates all groups found in the input;
2. creates or confirms each user;
3. links groups in `IN` and `OUT`;
4. converts expiration values to Unix Epoch when required;
5. requests the QR Code;
6. saves PNG files in `qrcodes/`;
7. writes the consolidated JSON report.

Example report:

```json
[
  {
    "username": "operator_alpha",
    "app": "android",
    "max_uses": "server default",
    "expiration": "server default",
    "qr_string": "string returned by OTS",
    "qr_image": "qrcodes/operator_alpha_android.png"
  }
]
```

Treat the report as sensitive. For sharing, consider removing the `qr_string` field.

## QR Code validity

### Android

The Android endpoint requires `username` and accepts these optional fields:

| Field | Meaning |
|---|---|
| `exp` | Expiration instant in Unix Epoch. |
| `nbf` | Instant from which the QR Code is valid; generated automatically when `exp` is provided. |
| `max` | Maximum activation count. |

### iPhone

The iPhone endpoint is queried with `GET` and returns the iTAK configuration string. The response may be JSON with `qr_string` or `itak_qr_string`, or plain text.

## Troubleshooting

### Connection failure

```bash
curl -i "$OTS_URL/"
getent hosts <hostname>
```

Check the IP, port, firewall, VPN, and whether the OTS service is running.

### Authentication failure

Check the username, password, URL, login method, and whether the account is enabled.

### HTTP 400 when creating a group or user

The response may indicate invalid data or duplication. The script recognizes duplication when the response contains `exists`; otherwise, inspect the complete response and correct the submitted fields.

### HTTP 401 or 403 on a protected operation

Check:

- whether login created the session;
- whether a CSRF token exists in the cookies or response;
- whether `X-CSRFToken` and `X-CSRF-TOKEN` were sent;
- whether `Referer` and `Origin` match `OTS_URL`;
- whether the account has permission;
- whether the session has expired.

### PNG not generated

```bash
python -c "import qrcode, PIL; print('dependencies OK')"
```

Confirm that `qrcode` and `pillow` are installed and that the destination directory is writable.

### Partially completed batch

Do not rerun a failed batch blindly. Compare the report, inspect which users and groups already exist, and handle duplicates in a controlled manner.

## Development validation

Validate Python syntax before use:

```bash
python -m py_compile ots_manager.py
```

Recommended test areas include expiration parsing, endpoint selection, JSON/text response handling, and payload construction.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for the complete license text.

## Author

**Orlando Nascimento Santos**  
Email: [onascimento@gmail.com](mailto:onascimento@gmail.com)

---

**OTS Manager CLI & Batch — Version 2.0**

Created for OpenTAKServer administration through its REST API.
