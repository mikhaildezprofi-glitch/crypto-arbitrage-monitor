set -euo pipefail
umask 077

TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"
if [ -z "$TAILSCALE_AUTHKEY" ]; then
  echo "TAILSCALE_AUTHKEY_SECRET_MISSING"
  exit 1
fi

ACCESS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
rm -f /tmp/manual-auth-ready
VNC_PASSWORD="$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8)))')"
printf '%s\n' "$VNC_PASSWORD" > /tmp/eid-vnc-password
chmod 600 /tmp/eid-vnc-password

sudo tee /etc/nginx/sites-available/eid-browser >/dev/null <<'NGINX'
map $http_upgrade $connection_upgrade {
  default upgrade;
  '' close;
}
server {
  listen 8080;
  server_name _;
  location = /ACCESS_TOKEN_PLACEHOLDER/session-ready {
    proxy_pass http://127.0.0.1:8081/session-ready;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 10s;
  }
  location ^~ /ACCESS_TOKEN_PLACEHOLDER/ {
    rewrite ^/ACCESS_TOKEN_PLACEHOLDER/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:6080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
  }
  location / { return 404; }
}
NGINX
sudo sed -i "s/ACCESS_TOKEN_PLACEHOLDER/$ACCESS_TOKEN/g" /etc/nginx/sites-available/eid-browser

python3 -u - <<'PY' >/tmp/manual-auth-signal.log 2>&1 &
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/session-ready":
            self.send_error(404); return
        Path("/tmp/manual-auth-ready").write_text("ready\n", encoding="utf-8")
        self.send_response(200); self.send_header("Content-Type", "text/plain")
        self.end_headers(); self.wfile.write(b"OK")
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *_args): pass
HTTPServer(("127.0.0.1", 8081), Handler).serve_forever()
PY
AUTH_SIGNAL_PID=$!

sudo tee /usr/share/novnc/token-vnc.html >/dev/null <<'HTML'
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Private E-ID browser</title>
<style>
html,body,#screen{width:100%;height:100%;margin:0;background:#111;overflow:hidden}
#status{position:fixed;top:8px;left:8px;color:white;background:#222c;padding:6px 9px;border-radius:6px;font:14px sans-serif;z-index:3}
#tools{position:fixed;right:10px;top:8px;z-index:4}
#keyboardToggle,#sessionReadyButton{padding:10px 14px;border:0;border-radius:8px;background:#2463eb;color:white;font-size:15px}
#sessionReadyButton{background:#16803c;margin-left:6px}
#sessionReadyButton:disabled{opacity:.65}
#mobileInput{display:none;position:fixed;left:8px;right:8px;bottom:8px;width:calc(100% - 32px);height:44px;box-sizing:border-box;padding:8px 12px;border:2px solid #2463eb;border-radius:8px;background:white;color:#111;font-size:18px;z-index:5}
#mobileInput.visible{display:block}
</style></head>
<body><div id="status">Connecting to remote browser…</div><div id="tools"><button id="keyboardToggle" type="button">⌨ Клавиатура</button><button id="sessionReadyButton" type="button">Авторизация завершена</button></div><div id="screen"></div>
<input id="mobileInput" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Нажмите здесь и вводите текст">
<script type="module">
import RFB from '/ACCESS_TOKEN_PLACEHOLDER/core/rfb.js';
const status = document.getElementById('status');
const keyboardToggle = document.getElementById('keyboardToggle');
const sessionReadyButton = document.getElementById('sessionReadyButton');
const mobileInput = document.getElementById('mobileInput');
const rfb = new RFB(document.getElementById('screen'), 'wss://' + location.host + '/ACCESS_TOKEN_PLACEHOLDER/websockify');
rfb.scaleViewport = true;
rfb.resizeSession = true;
rfb.addEventListener('connect', () => { status.textContent = 'Connected'; });
rfb.addEventListener('disconnect', e => { status.textContent = 'Disconnected' + (e.detail.clean ? '' : ' (connection error)'); });
rfb.addEventListener('credentialsrequired', () => { rfb.sendCredentials({password: 'VNC_PASSWORD_PLACEHOLDER'}); });

// Android/iOS virtual keyboards do not reliably open for a canvas.
// This real input opens the device keyboard; its keystrokes are relayed
// to noVNC's canvas as keyboard events.
function canvas() { return document.querySelector('#screen canvas'); }
function sendKey(key, code, keyCode) {
  const target = canvas();
  if (!target) return;
  for (const type of ['keydown', 'keyup']) {
    target.dispatchEvent(new KeyboardEvent(type, {
      key, code, keyCode, which: keyCode, bubbles: true, cancelable: true
    }));
  }
}
mobileInput.addEventListener('input', () => {
  const value = mobileInput.value;
  for (const char of value) {
    const codePoint = char.codePointAt(0);
    sendKey(char, codePoint > 0xffff ? 'Unidentified' : 'Key' + char.toUpperCase(), codePoint);
  }
  mobileInput.value = '';
});
mobileInput.addEventListener('keydown', event => {
  const map = {
    Enter: ['Enter', 13], Backspace: ['Backspace', 8], Tab: ['Tab', 9],
    Escape: ['Escape', 27], ' ': [' ', 32],
    ArrowUp: ['ArrowUp', 38], ArrowDown: ['ArrowDown', 40],
    ArrowLeft: ['ArrowLeft', 37], ArrowRight: ['ArrowRight', 39]
  };
  if (map[event.key] && event.key !== ' ') {
    event.preventDefault();
    sendKey(event.key, event.key, map[event.key][1]);
  }
});
keyboardToggle.addEventListener('click', () => {
  mobileInput.classList.add('visible');
  mobileInput.focus();
});
sessionReadyButton.addEventListener('click', async () => {
  sessionReadyButton.disabled = true;
  sessionReadyButton.textContent = 'Передаю сигнал…';
  try {
    const response = await fetch('/ACCESS_TOKEN_PLACEHOLDER/session-ready', {
      method: 'POST', credentials: 'same-origin'
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    sessionReadyButton.textContent = 'Сбор данных запущен';
    status.textContent = 'Авторизация отмечена. Запускаю сбор данных…';
  } catch (error) {
    sessionReadyButton.disabled = false;
    sessionReadyButton.textContent = 'Повторить сигнал';
    status.textContent = 'Не удалось передать сигнал: ' + String(error);
  }
});
mobileInput.addEventListener('blur', () => {
  // Keep the input available; the user can reopen the keyboard button.
});
</script></body></html>
HTML
          sudo sed -i "s/ACCESS_TOKEN_PLACEHOLDER/$ACCESS_TOKEN/g; s/VNC_PASSWORD_PLACEHOLDER/$VNC_PASSWORD/g" /usr/share/novnc/token-vnc.html
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/eid-browser /etc/nginx/sites-enabled/eid-browser
sudo nginx -t
sudo nginx
curl -fsS http://127.0.0.1:8081/health >/dev/null
echo "MANUAL_AUTH_SIGNAL_ENDPOINT=READY"

Xvfb :99 -screen 0 1440x900x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

cleanup() {
  [ -n "${AUTH_SIGNAL_PID:-}" ] && kill "$AUTH_SIGNAL_PID" 2>/dev/null || true
  [ -n "${WEBSOCKIFY_PID:-}" ] && kill "$WEBSOCKIFY_PID" 2>/dev/null || true
  [ -n "${VNC_PID:-}" ] && kill "$VNC_PID" 2>/dev/null || true
  [ -n "${XVFB_PID:-}" ] && kill "$XVFB_PID" 2>/dev/null || true
  sudo nginx -s quit 2>/dev/null || true
  rm -f /tmp/eid-http-password /tmp/eid-vnc-password
}
trap cleanup EXIT

# Do not start x11vnc until Xvfb has completed initialization.
DISPLAY_READY=""
for i in $(seq 1 30); do
  if xdpyinfo -display :99 >/dev/null 2>&1; then DISPLAY_READY=yes; break; fi
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "XVFB_PROCESS_EXITED"
    cat /tmp/xvfb.log || true
    exit 1
  fi
  sleep 1
done
if [ -z "$DISPLAY_READY" ]; then
  echo "XVFB_DISPLAY_NOT_READY"
  cat /tmp/xvfb.log || true
  exit 1
fi
echo "XVFB_DISPLAY_HEALTHCHECK=OK"

x11vnc -display :99 -rfbport 5900 -forever -shared -repeat -noxdamage -passwdfile /tmp/eid-vnc-password >/tmp/x11vnc.log 2>&1 &
VNC_PID=$!

# Wait for the RFB listener itself, not merely for the noVNC web page.
VNC_READY=""
for i in $(seq 1 30); do
  if python3 -c 'import socket; s=socket.create_connection(("127.0.0.1",5900),timeout=1); s.close()' 2>/dev/null; then
    VNC_READY=yes
    break
  fi
  if ! kill -0 "$VNC_PID" 2>/dev/null; then
    echo "X11VNC_PROCESS_EXITED"
    tail -n 100 /tmp/x11vnc.log || true
    exit 1
  fi
  sleep 1
done
if [ -z "$VNC_READY" ]; then
  echo "X11VNC_LISTENER_NOT_READY"
  ss -ltnp '( sport = :5900 )' || true
  tail -n 100 /tmp/x11vnc.log || true
  exit 1
fi
echo "X11VNC_LISTENER_HEALTHCHECK=OK"

websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
WEBSOCKIFY_PID=$!
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:6080/vnc.html -o /dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:6080/vnc.html -o /dev/null

LOCAL_PAGE_CODE="$(curl -sS --connect-timeout 3 --max-time 8 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8080/$ACCESS_TOKEN/token-vnc.html" || true)"
if [ "$LOCAL_PAGE_CODE" != "200" ]; then
  echo "LOCAL_TOKEN_PAGE_HEALTHCHECK=FAILED status=$LOCAL_PAGE_CODE"
  exit 1
fi
echo "LOCAL_TOKEN_PAGE_HEALTHCHECK=OK"

# Confirm x11vnc is not merely running as a process: read its RFB banner.
python3 - <<'PY'
import socket, time
last_error = None
for attempt in range(20):
    try:
        with socket.create_connection(("127.0.0.1", 5900), timeout=3) as sock:
            sock.settimeout(3)
            banner = sock.recv(12)
        if banner.startswith(b"RFB "):
            print("LOCAL_VNC_RFB_HEALTHCHECK=OK")
            break
        raise RuntimeError("Unexpected VNC banner: %r" % (banner,))
    except Exception as exc:
        last_error = exc
        time.sleep(1)
else:
    print("LOCAL_VNC_RFB_HEALTHCHECK=FAILED reason=%s" % str(last_error)[:180])
    raise SystemExit(1)
PY

# Launch the downloaded Chromium executable directly. No Playwright
# browser/context/page objects are created; the user operates this
# ordinary visible browser through the noVNC desktop.
CHROMIUM_BIN="$(find "$HOME/.cache/ms-playwright" -type f -name chrome -perm -111 | head -n 1)"
if [ -z "$CHROMIUM_BIN" ]; then
  echo "STANDALONE_CHROMIUM_BINARY_NOT_FOUND"
  find "$HOME/.cache/ms-playwright" -maxdepth 4 -type f -name chrome -print || true
  exit 1
fi
echo "STANDALONE_CHROMIUM=$(basename "$(dirname "$CHROMIUM_BIN")")/chrome"
"$CHROMIUM_BIN" --version
: "${TARGET:?TARGET must be set}"
if [ "$TARGET" = "auth_only" ] || [ "$TARGET" = "all" ]; then
  CHROMIUM_START_URL="https://storage.money/deals#tab-3"
  EXTRA_START_URLS=("https://sberkassa.site/deals#tab-3" "https://sberkassa.site/exchange")
  BRIDGE_SCRIPT="all"
elif [ "$TARGET" = "sberkassa" ]; then
  # Existing ERUB -> RUB deals collector. Keep its scope unchanged.
  CHROMIUM_START_URL="about:blank"
  BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"
elif [ "$TARGET" = "sberkassa_exchange" ]; then
  # Separate authenticated /exchange discovery probe. It blocks all
  # non-GET requests and never changes page controls.
  CHROMIUM_START_URL="about:blank"
  BRIDGE_SCRIPT="scripts/sberkassa_exchange_chromium_probe.py"
else
  # Reuse the saved authenticated session first. The bridge opens the
  # normal account/E-ID route only if the protected offers page rejects it.
  CHROMIUM_START_URL="https://storage.money/deals#tab-3"
  BRIDGE_SCRIPT="scripts/money_storage_chromium_bridge.py"
fi
echo "BROWSER_TARGET=$TARGET"

# The encrypted profile is restored onto a fresh GitHub-hosted runner.
# Chromium's Singleton* symlinks can survive an earlier shutdown and
# contain the previous runner hostname/PID. They are not auth state.
# Never remove them while a browser using this profile is alive.
if pgrep -af '[c]hrome.*--user-data-dir=/tmp/eid-chromium-profile'; then
  echo "CHROMIUM_PROFILE_IN_USE_ON_CURRENT_RUNNER"
  exit 1
fi
for lock_name in SingletonLock SingletonCookie SingletonSocket; do
  lock_path="/tmp/eid-chromium-profile/$lock_name"
  if [ -L "$lock_path" ] || [ -e "$lock_path" ]; then
    rm -f -- "$lock_path"
    echo "CHROMIUM_STALE_PROFILE_LOCK_REMOVED=$lock_name"
  fi
done

CHROMIUM_START_ARGS=("$CHROMIUM_START_URL")
if [ "$TARGET" = "all" ] || [ "$TARGET" = "auth_only" ]; then
  CHROMIUM_START_ARGS+=("${EXTRA_START_URLS[@]}")
fi
DISPLAY=:99 "$CHROMIUM_BIN" \
  --no-sandbox \
  --disable-dev-shm-usage \
  --no-first-run \
  --no-default-browser-check \
  --password-store=basic \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --user-data-dir=/tmp/eid-chromium-profile \
  --window-size=1440,900 \
  "${CHROMIUM_START_ARGS[@]}" >/tmp/chromium.log 2>&1 &
BROWSER_PID=$!

CDP_READY=""
for i in $(seq 1 60); do
  if curl -fsS --connect-timeout 2 --max-time 3 http://127.0.0.1:9222/json/version >/tmp/chromium-cdp-version.json; then
    CDP_READY=yes
    break
  fi
  if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "STANDALONE_CHROMIUM_EXITED"
    tail -n 100 /tmp/chromium.log || true
    exit 1
  fi
  sleep 1
done
if [ -z "$CDP_READY" ]; then
  echo "STANDALONE_CHROMIUM_CDP_NOT_READY"
  tail -n 100 /tmp/chromium.log || true
  exit 1
fi
echo "STANDALONE_CHROMIUM_HEALTHCHECK=OK"

if [ "$TARGET" = "all" ]; then
  python3 - <<'PY'
import json, time, urllib.request
expected = {("storage.money", "/deals"), ("sberkassa.site", "/deals"), ("sberkassa.site", "/exchange")}
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=3) as response:
            targets = json.load(response)
        found = set()
        for item in targets:
            if item.get("type") != "page":
                continue
            from urllib.parse import urlparse
            parsed = urlparse(item.get("url", ""))
            if parsed.hostname in {"storage.money", "sberkassa.site"}:
                found.add((parsed.hostname, parsed.path.rstrip("/") or "/"))
        if expected.issubset(found):
            print("SHARED_CHROMIUM_THREE_TARGET_TABS=VERIFIED")
            for host, path in sorted(expected):
                print(f"SHARED_CHROMIUM_TAB={host}{path}")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("SHARED_CHROMIUM_THREE_TARGET_TABS_NOT_FOUND")
PY
fi

# The collectors can be restarted after the user confirms that all three tabs
# are manually authenticated. They always attach to the same Chromium profile.
start_all_probes() {
  rm -f /tmp/money-storage-status /tmp/sberkassa-sell-status /tmp/sberkassa-exchange-status
  MONEY_STORAGE_STATUS_FILE=/tmp/money-storage-status \
    python3 scripts/money_storage_chromium_bridge.py >>/tmp/money-storage-browser.log 2>&1 &
  MONEY_PID=$!
  SBERKASSA_STATUS_FILE=/tmp/sberkassa-sell-status \
    python3 scripts/sberkassa_chromium_probe.py >>/tmp/sberkassa-sell-browser.log 2>&1 &
  SBERKASSA_SELL_PID=$!
  SBERKASSA_EXCHANGE_STATUS_FILE=/tmp/sberkassa-exchange-status \
    python3 scripts/sberkassa_exchange_chromium_probe.py >>/tmp/sberkassa-exchange-browser.log 2>&1 &
  SBERKASSA_EXCHANGE_PID=$!
  BRIDGE_PID="$MONEY_PID $SBERKASSA_SELL_PID $SBERKASSA_EXCHANGE_PID"
}
# The shared monitor reads this file even in all-tabs mode; create it before polling.
: > /tmp/eid-browser.log

if [ "$TARGET" = "auth_only" ]; then
  : > /tmp/money-storage-browser.log
  : > /tmp/sberkassa-sell-browser.log
  : > /tmp/sberkassa-exchange-browser.log
  echo "AUTH_ONLY_MODE=YES"
  echo "AUTH_ONLY_COLLECTORS=DISABLED"
  echo "CHROMIUM_SINGLE_PROCESS=YES"
  echo "CHROMIUM_SHARED_PROFILE=YES"
  echo "CHROMIUM_EXPECTED_TABS=3"
elif [ "$TARGET" = "all" ]; then
  : > /tmp/money-storage-browser.log
  : > /tmp/sberkassa-sell-browser.log
  : > /tmp/sberkassa-exchange-browser.log
  start_all_probes
  echo "CHROMIUM_SINGLE_PROCESS=YES"
  echo "CHROMIUM_SHARED_PROFILE=YES"
  echo "CHROMIUM_EXPECTED_TABS=3"
elif [ "$TARGET" = "money_storage" ] && [ "$INSPECT_CURRENCY_FORM" = "true" ]; then
  MONEY_STORAGE_FORM_INSPECTION=1 python3 "$BRIDGE_SCRIPT" >/tmp/eid-browser.log 2>&1 &
elif [ "$TARGET" = "sberkassa" ] && [ "$COLLECTION_EVENT_NAME" = "push" ]; then
  # Push-triggered test uses the previously saved session only. If it
  # expired, fail closed instead of waiting for a manual login.
  SBERKASSA_NONINTERACTIVE=1 python3 "$BRIDGE_SCRIPT" >/tmp/eid-browser.log 2>&1 &
else
  # Default Money Storage mode is the original authenticated, read-only
  # quote capture. Access-only diagnostics require an explicit input.
  python3 "$BRIDGE_SCRIPT" >/tmp/eid-browser.log 2>&1 &
fi
BRIDGE_PID=$!


# Join this ephemeral GitHub-hosted runner to the tailnet.
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up \
  --authkey="$TAILSCALE_AUTHKEY" \
  --hostname="gha-${GITHUB_RUN_ID}" \
  --advertise-tags=tag:ci \
  --accept-dns=false
TUNNEL_PID=""

write_run_diagnostics() {
  MONEY_PID="${MONEY_PID:-}" SBERKASSA_SELL_PID="${SBERKASSA_SELL_PID:-}" SBERKASSA_EXCHANGE_PID="${SBERKASSA_EXCHANGE_PID:-}" python3 - <<'PY'
import json, os, signal
from pathlib import Path
workspace = Path(os.environ.get("GITHUB_WORKSPACE", "."))
targets = {
  "money_storage": ("/tmp/money-storage-status", "/tmp/money-storage-browser.log"),
  "sberkassa_erub_rub": ("/tmp/sberkassa-sell-status", "/tmp/sberkassa-sell-browser.log"),
  "sberkassa_rub_usdt": ("/tmp/sberkassa-exchange-status", "/tmp/sberkassa-exchange-browser.log"),
}
result = {
  "schema_version": 2, "target": os.environ.get("TARGET", "all"), "read_only": True,
  "overall_limit_seconds": 1200, "manual_auth_limit_seconds": 600, "tabs": {}
}
for name, (status_path, log_path) in targets.items():
    status_file, log_file = Path(status_path), Path(log_path)
    status = status_file.read_text(errors="replace").strip() if status_file.exists() else "NO_STATUS"
    lines = log_file.read_text(errors="replace").splitlines() if log_file.exists() else []
    markers = [line for line in lines if any(token in line for token in (
        "START", "READY", "NAV=", "HTTP_DIAG", "REQUEST", "AUTH_", "EID_",
        "OFFERS_READ_", "SBERKASSA_CAPTURE_", "SBERKASSA_EXCHANGE_", "QUOTE_FIELDS",
        "PAGE_UPDATE_MARKERS", "JSON_SCHEMA", "ERROR", "TIMEOUT"
    ))]
    if os.environ.get("TARGET") == "auth_only": diagnosis = "not_run_auth_only"
    elif status.endswith("_COMPLETE") or status == "OFFERS_READ_OK": diagnosis = "completed"
    elif status in ("NO_STATUS", "", "WAITING"): diagnosis = "collector_did_not_write_status"
    elif "AUTH" in status or "LOGIN" in status: diagnosis = "authentication_or_session"
    elif "TIMEOUT" in status: diagnosis = "timeout"
    elif "FAILED" in status: diagnosis = "collector_failure"
    else: diagnosis = "stopped_at_last_recorded_stage"
    pid_env = {
        "money_storage": "MONEY_PID",
        "sberkassa_erub_rub": "SBERKASSA_SELL_PID",
        "sberkassa_rub_usdt": "SBERKASSA_EXCHANGE_PID"
    }[name]
    raw_pid = os.environ.get(pid_env, "")
    process_alive = None
    if raw_pid.isdigit():
        try:
            os.kill(int(raw_pid), 0)
            process_alive = True
        except ProcessLookupError:
            process_alive = False
        except PermissionError:
            process_alive = True
    result["tabs"][name] = {
        "status": status, "diagnosis": diagnosis, "process_pid": int(raw_pid) if raw_pid.isdigit() else None,
        "process_alive_at_diagnostic_time": process_alive, "log_exists": log_file.exists(),
        "log_line_count": len(lines), "last_log_line": lines[-1] if lines else None,
        "last_stage_marker": markers[-1] if markers else None,
        "last_progress_markers": markers[-30:], "diagnostic_tail": lines[-100:]
    }
(workspace / "browser-session-diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

cleanup_all() {
  write_run_diagnostics || true
  # Stop Chromium first and wait for it to flush profile databases
  # before the following workflow step encrypts the profile.
  if [ "$TARGET" = "all" ]; then
    kill -TERM "${MONEY_PID:-}" "${SBERKASSA_SELL_PID:-}" "${SBERKASSA_EXCHANGE_PID:-}" 2>/dev/null || true
    wait "${MONEY_PID:-}" 2>/dev/null || true
    wait "${SBERKASSA_SELL_PID:-}" 2>/dev/null || true
    wait "${SBERKASSA_EXCHANGE_PID:-}" 2>/dev/null || true
  else
    kill -TERM "${BRIDGE_PID:-}" 2>/dev/null || true
    wait "${BRIDGE_PID:-}" 2>/dev/null || true
  fi
  kill -TERM "$BROWSER_PID" 2>/dev/null || true
  wait "$BROWSER_PID" 2>/dev/null || true
  sudo tailscale funnel --https=443 off >/dev/null 2>&1 || true
  sudo tailscale down >/dev/null 2>&1 || true
  cleanup
}
trap cleanup_all EXIT

TUNNEL_URL=""
: > /tmp/tailscale-funnel.log
sudo tailscale funnel --bg --https=443 http://127.0.0.1:8080 2>&1 | tee /tmp/tailscale-funnel.log
TUNNEL_HOST="$(sudo tailscale status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["Self"]["DNSName"].rstrip("."))')"
if [ -z "$TUNNEL_HOST" ] || [[ ! "$TUNNEL_HOST" =~ \.ts\.net$ ]]; then
  echo "TAILSCALE_FUNNEL_HOSTNAME_NOT_AVAILABLE"
  cat /tmp/tailscale-funnel.log
  exit 1
fi
TUNNEL_URL="https://$TUNNEL_HOST"
echo "TAILSCALE_FUNNEL_CREATED=YES"
echo "TAILSCALE_FUNNEL_HOSTNAME=$TUNNEL_HOST"

PUBLIC_OK=""
TUNNEL_IP=""
for i in $(seq 1 90); do
  # The runner's configured resolver can retain a negative answer for a
  # newly-created *.ts.net name. Resolve through independent public DoH,
  # then pin curl to that IP while preserving HTTPS SNI and Host.
  TUNNEL_IP="$(python3 scripts/resolve_tailscale_funnel_ipv4.py "$TUNNEL_HOST" 2>/dev/null || true)"
  if [ -n "$TUNNEL_IP" ]; then
    CODE="$(curl --resolve "$TUNNEL_HOST:443:$TUNNEL_IP" -sS --connect-timeout 8 --max-time 15 -o /dev/null -w '%{http_code}' "$TUNNEL_URL/$ACCESS_TOKEN/token-vnc.html" || true)"
  else
    CODE="DNS_WAIT"
  fi
  if [ "$CODE" = "200" ]; then PUBLIC_OK=yes; break; fi
  if ! sudo tailscale status >/dev/null 2>&1; then
    echo "TAILSCALE_DAEMON_UNAVAILABLE_DURING_HEALTHCHECK"
    tail -n 100 /tmp/tailscale-funnel.log
    exit 1
  fi
  echo "PUBLIC_TUNNEL_WAIT http=$CODE attempt=$i/90"
  sleep 2
done
if [ -z "$PUBLIC_OK" ]; then
  echo "TAILSCALE_FUNNEL_HEALTHCHECK_FAILED"
  tail -n 100 /tmp/tailscale-funnel.log
  exit 1
fi

echo "PUBLIC_TUNNEL_HEALTHCHECK=HTTP_200"

# Verify the actual WebSocket upgrade through Tailscale Funnel and Nginx.
# A page-only HTTP 200 is not enough: it was the source of the
# misleading green health checks in the previous run.
WS_OK=""
for i in $(seq 1 10); do
  curl --resolve "$TUNNEL_HOST:443:$TUNNEL_IP" --http1.1 -sS -D /tmp/eid-ws-headers -o /dev/null --max-time 4 \
    -H "Connection: Upgrade" \
    -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Version: 13" \
    -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
    "$TUNNEL_URL/$ACCESS_TOKEN/websockify" || true
  if grep -qE '^HTTP/[0-9.]+ 101' /tmp/eid-ws-headers; then
    WS_OK=yes
    break
  fi
  echo "PUBLIC_WEBSOCKET_WAIT attempt=$i/10"
  cat /tmp/eid-ws-headers || true
  sleep 2
done
if [ -z "$WS_OK" ]; then
  echo "PUBLIC_WEBSOCKET_HEALTHCHECK_FAILED"
  tail -n 80 /tmp/websockify.log || true
  tail -n 80 /tmp/x11vnc.log || true
  exit 1
fi
echo "PUBLIC_WEBSOCKET_HEALTHCHECK=HTTP_101"

echo "REMOTE_BROWSER_URL=$TUNNEL_URL/$ACCESS_TOKEN/token-vnc.html"
echo "REMOTE_BROWSER_AUTH=automatic via temporary per-run access token"
echo "VNC_AUTH=automatic; credentials are not printed"
echo if [ "$TARGET" = "auth_only" ]; then
  echo "MANUAL_AUTH_BUTTON=AVAILABLE; complete provider sign-in in all three tabs, then press 'Авторизация завершена' to save the encrypted session."
  echo "AUTH_ONLY_WAIT_LIMIT_SECONDS=600"
else
  echo "MANUAL_AUTH_BUTTON=AVAILABLE; inspect all three tabs, complete provider sign-in manually, then press 'Авторизация завершена'."
fi

# Forward only the browser's sanitized diagnostic lines into Actions logs.
# The browser process writes to a private file; without this relay its
# navigation and Cloudflare/E-ID diagnostics remain invisible.
BROWSER_LOG_LINES=0
echo "BROWSER_DIAGNOSTIC_STREAM=STARTED"
for i in $(seq 1 600); do
  if [ "$TARGET" = "auth_only" ]; then
    if [ -f /tmp/manual-auth-ready ]; then
      echo "AUTH_ONLY_MANUAL_CONFIRMATION=RECEIVED"
      echo "AUTH_ONLY_COLLECTION=NOT_STARTED"
      echo "AUTH_ONLY_PROFILE_SAVE=NEXT_WORKFLOW_STEP"
      exit 0
    fi
    if [ $((i % 15)) -eq 0 ]; then
      echo "AUTH_ONLY_WAIT elapsed_seconds=$((i * 2)) limit_seconds=1200"
    fi
  elif [ "$TARGET" = "all" ]; then
    MS_STATUS="$(cat /tmp/money-storage-status 2>/dev/null || echo WAITING)"
    SS_STATUS="$(cat /tmp/sberkassa-sell-status 2>/dev/null || echo WAITING)"
    SX_STATUS="$(cat /tmp/sberkassa-exchange-status 2>/dev/null || echo WAITING)"
    echo "SHARED_BROWSER_TAB_STATUS money_storage=$MS_STATUS sberkassa_sell=$SS_STATUS sberkassa_exchange=$SX_STATUS"
     echo "SHARED_BROWSER_PROCESS_STATE money_storage=$(kill -0 "$MONEY_PID" 2>/dev/null && echo alive || echo exited) sberkassa_sell=$(kill -0 "$SBERKASSA_SELL_PID" 2>/dev/null && echo alive || echo exited) sberkassa_exchange=$(kill -0 "$SBERKASSA_EXCHANGE_PID" 2>/dev/null && echo alive || echo exited)"
    if [ "$MS_STATUS" = "OFFERS_READ_OK" ] && [ "$SS_STATUS" = "SBERKASSA_CAPTURE_COMPLETE" ] && [ "$SX_STATUS" = "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE" ]; then
      echo "ALL_THREE_SHARED_BROWSER_TABS_COMPLETE=YES"
      grep -hE '^(OFFERS_READ_OK|SBERKASSA_CAPTURE_|SBERKASSA_EXCHANGE_INSPECTION_COMPLETE=|SBERKASSA_EXCHANGE_DISPLAYED_RATE=|SBERKASSA_SESSION=|SBERKASSA_SESSION_AUTHENTICATED=)' /tmp/money-storage-browser.log /tmp/sberkassa-sell-browser.log /tmp/sberkassa-exchange-browser.log | tail -n 160 || true
      exit 0
    fi
    AUTH_FAILURE=NO
    case "$MS_STATUS" in AUTH_REQUIRED|AUTH_TIMEOUT|MONEY_STORAGE_RETURN_TIMEOUT) AUTH_FAILURE=YES;; esac
    case "$SS_STATUS" in AUTH_TIMEOUT) AUTH_FAILURE=YES;; esac
    case "$SX_STATUS" in SBERKASSA_EXCHANGE_AUTH_TIMEOUT|SBERKASSA_EXCHANGE_SESSION_EXPIRED) AUTH_FAILURE=YES;; esac
    if [ "$AUTH_FAILURE" = "YES" ] && [ "${MANUAL_AUTH_WAITED:-no}" = "no" ]; then
      echo "MANUAL_AUTH_REQUIRED=YES"
      echo "MANUAL_AUTH_INSTRUCTIONS=Complete sign-in in all three tabs, verify the pages, then press the green 'Авторизация завершена' button in the remote browser."
      kill -TERM "${MONEY_PID:-}" "${SBERKASSA_SELL_PID:-}" "${SBERKASSA_EXCHANGE_PID:-}" 2>/dev/null || true
      wait "${MONEY_PID:-}" 2>/dev/null || true
      wait "${SBERKASSA_SELL_PID:-}" 2>/dev/null || true
      wait "${SBERKASSA_EXCHANGE_PID:-}" 2>/dev/null || true
      MANUAL_AUTH_WAITED=yes
      AUTH_SIGNAL_RECEIVED=no
      for wait_index in $(seq 1 300); do
        if [ -f /tmp/manual-auth-ready ]; then AUTH_SIGNAL_RECEIVED=yes; break; fi
        if ! kill -0 "$BROWSER_PID" 2>/dev/null || ! sudo tailscale status >/dev/null 2>&1; then
          echo "MANUAL_AUTH_HANDOFF_INTERRUPTED browser_or_tunnel_unavailable"
          break
        fi
        if [ $((wait_index % 15)) -eq 0 ]; then
          echo "MANUAL_AUTH_WAIT elapsed_seconds=$((wait_index * 2)) limit_seconds=600"
        fi
        sleep 2
      done
      if [ "$AUTH_SIGNAL_RECEIVED" != "yes" ]; then
        echo "MANUAL_AUTH_TIMEOUT=600_SECONDS"
        exit 1
      fi
      echo "MANUAL_AUTH_SIGNAL=RECEIVED"
      start_all_probes
      continue
    fi
    case "$MS_STATUS" in OFFERS_READ_FAILED) echo "MONEY_STORAGE_TAB_FAILED=$MS_STATUS"; cat /tmp/money-storage-browser.log; exit 1;; esac
    case "$SS_STATUS" in SBERKASSA_CAPTURE_FAILED|SBERKASSA_CAPTURE_TIMEOUT) echo "SBERKASSA_SELL_TAB_FAILED=$SS_STATUS"; cat /tmp/sberkassa-sell-browser.log; exit 1;; esac
    case "$SX_STATUS" in SBERKASSA_EXCHANGE_SELECTION_TIMEOUT) echo "SBERKASSA_EXCHANGE_TAB_FAILED=$SX_STATUS"; cat /tmp/sberkassa-exchange-browser.log; exit 1;; esac
    if [ "$AUTH_FAILURE" = "YES" ] && [ "${MANUAL_AUTH_WAITED:-no}" = "yes" ]; then
      echo "MANUAL_AUTH_RETRY_FAILED money_storage=$MS_STATUS sberkassa_sell=$SS_STATUS sberkassa_exchange=$SX_STATUS"
      grep -hE '^(OFFERS_READ_|AUTH_REQUIRED|AUTH_TIMEOUT|MONEY_STORAGE_RETURN_TIMEOUT|SBERKASSA_CAPTURE_|SBERKASSA_EXCHANGE_|HTTP_DIAG |NAV=)' /tmp/money-storage-browser.log /tmp/sberkassa-sell-browser.log /tmp/sberkassa-exchange-browser.log | tail -n 180 || true
      exit 1
    fi
    if ! kill -0 "$MONEY_PID" 2>/dev/null && [ "$MS_STATUS" != "OFFERS_READ_OK" ]; then cat /tmp/money-storage-browser.log; exit 1; fi
    if ! kill -0 "$SBERKASSA_SELL_PID" 2>/dev/null && [ "$SS_STATUS" != "SBERKASSA_CAPTURE_COMPLETE" ]; then cat /tmp/sberkassa-sell-browser.log; exit 1; fi
    if ! kill -0 "$SBERKASSA_EXCHANGE_PID" 2>/dev/null && [ "$SX_STATUS" != "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE" ]; then cat /tmp/sberkassa-exchange-browser.log; exit 1; fi
  else
    STATUS="$(cat /tmp/eid-auth-status 2>/dev/null || echo WAITING_FOR_LOGIN)"
  fi
  if [ "$TARGET" != "all" ] && [ "$STATUS" = "FORM_INSPECTION_COMPLETE" ]; then
    echo "FORM_INSPECTION_COMPLETE: the page itself sent a request containing from=ECR&to=USDT; inspect PAGE_REQUEST for the exact endpoint and parameter location."
    grep -E "^(PAGE_DIAG deals_form=|PAGE_REQUEST |FORM_INSPECTION_READY)" /tmp/eid-browser.log | tail -n 120 || true
    exit 0
  fi
  if [ "$TARGET" != "all" ] && { [ "$STATUS" = "MONEY_STORAGE_RETURNED" ] || [ "$STATUS" = "MONEY_STORAGE_SESSION_CANDIDATE" ]; }; then
    echo "Money Storage profile handoff milestone completed: $STATUS"
    grep -E '^(EID_STATE=|CLOUDFLARE_STATE=|NAV=|PAGE_DIAG deals_form=|PAGE_REQUEST |FORM_INSPECTION_READY|MONEY_STORAGE_RETURNED |MONEY_STORAGE_SESSION_CANDIDATE )' /tmp/eid-browser.log | tail -n 120 || true
    exit 0
  fi
  if [ "$TARGET" != "all" ] && { [ "$STATUS" = "OFFERS_READ_OK" ] || [ "$STATUS" = "SBERKASSA_CAPTURE_COMPLETE" ] || [ "$STATUS" = "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE" ]; }; then
    echo "Authenticated read-only browser inspection completed for target=$TARGET."
    echo "BROWSER_DIAGNOSTICS_FINAL:"
    grep -E '^(SESSION_REUSE_CHECK=|EID_HANDOFF=|EID_STATE=|CLOUDFLARE_STATE=|SBERKASSA_SESSION=|SBERKASSA_SESSION_AUTHENTICATED=|SESSION_REUSE_OR_EID_TIMEOUT=|SBERKASSA_CAPTURE_|SBERKASSA_EXCHANGE_|NAV=|HTTP_DIAG |REQUEST |QUOTE_FIELDS |PAGE_UPDATE_MARKERS |EXCHANGE_JSON )' /tmp/eid-browser.log | tail -n 160 || true
    exit 0
  fi
  if [ "$TARGET" != "all" ] && { [ "$STATUS" = "OFFERS_READ_FAILED" ] || [ "$STATUS" = "AUTH_TIMEOUT" ] || [ "$STATUS" = "MONEY_STORAGE_RETURN_TIMEOUT" ] || [ "$STATUS" = "SBERKASSA_CAPTURE_FAILED" ] || [ "$STATUS" = "SBERKASSA_CAPTURE_TIMEOUT" ] || [ "$STATUS" = "SBERKASSA_EXCHANGE_AUTH_TIMEOUT" ] || [ "$STATUS" = "SBERKASSA_EXCHANGE_SELECTION_TIMEOUT" ]; }; then
    echo "BROWSER_DIAGNOSTICS:"
    grep -E 'OFFERS_READ_|AUTH_|SBERKASSA_|NAV=|REQUEST |QUOTE_FIELDS |PAGE_UPDATE_MARKERS |HTTP_DIAG ' /tmp/eid-browser.log | tail -n 120 || true
    exit 1
  fi
  if ! sudo tailscale status >/dev/null 2>&1; then
    echo "TAILSCALE_DAEMON_UNAVAILABLE"
    tail -n 100 /tmp/tailscale-funnel.log
    exit 1
  fi
  if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "STANDALONE_CHROMIUM_PROCESS_EXITED"
    tail -n 100 /tmp/chromium.log || true
    exit 1
  fi
  if [ "$TARGET" != "all" ] && ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo "CHROMIUM_SESSION_BRIDGE_EXITED"
    tail -n 100 /tmp/eid-browser.log || true
    exit 1
  fi
  if [ $((i % 15)) -eq 0 ]; then
    TUNNEL_IP="$(python3 scripts/resolve_tailscale_funnel_ipv4.py "$TUNNEL_HOST" 2>/dev/null || true)"
    CODE="DNS_WAIT"
    if [ -n "$TUNNEL_IP" ]; then
      CODE="$(curl --resolve "$TUNNEL_HOST:443:$TUNNEL_IP" -sS --connect-timeout 8 --max-time 15 -o /dev/null -w '%{http_code}' "$TUNNEL_URL/$ACCESS_TOKEN/token-vnc.html" || true)"
    fi
    rm -f /tmp/eid-ws-headers
    WS_CODE="DNS_WAIT"
    if [ -n "$TUNNEL_IP" ]; then
      WS_CODE="$(curl --resolve "$TUNNEL_HOST:443:$TUNNEL_IP" --http1.1 -sS -D /tmp/eid-ws-headers -o /dev/null --max-time 4 \
      -H "Connection: Upgrade" -H "Upgrade: websocket" \
      -H "Sec-WebSocket-Version: 13" \
      -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
      "$TUNNEL_URL/$ACCESS_TOKEN/websockify" >/dev/null 2>&1 || true)"
    fi
    if grep -qE '^HTTP/[0-9.]+ 101' /tmp/eid-ws-headers; then WS_STATUS=101; else WS_STATUS=FAILED; fi
    echo "PUBLIC_TUNNEL_HEALTHCHECK interval=30s http=$CODE websocket=$WS_STATUS"
    if [ "$TARGET" = "all" ]; then
      for LOG in /tmp/money-storage-browser.log /tmp/sberkassa-sell-browser.log /tmp/sberkassa-exchange-browser.log; do
        echo "SHARED_TAB_LOG=$(basename "$LOG")"
        grep -E '^(INITIAL_NAVIGATION=|BROWSER_READY=|SESSION_REUSE_CHECK=|EID_HANDOFF=|SBERKASSA_SESSION=|SBERKASSA_SESSION_AUTHENTICATED=|OFFERS_READ_|SBERKASSA_CAPTURE_|SBERKASSA_EXCHANGE_|NAV=|HTTP_DIAG |REQUEST |PAGE_UPDATE_MARKERS |AUTH_REQUIRED|AUTH_TIMEOUT)' "$LOG" | tail -n 35 || true
      done
    fi
    CURRENT_BROWSER_LINES="$(wc -l < /tmp/eid-browser.log 2>/dev/null || echo 0)"
    if [ "$CURRENT_BROWSER_LINES" -gt "$BROWSER_LOG_LINES" ]; then
      echo "BROWSER_DIAGNOSTICS_UPDATE:"
      sed -n "$((BROWSER_LOG_LINES + 1)),${CURRENT_BROWSER_LINES}p" /tmp/eid-browser.log | grep -E '^(INITIAL_NAVIGATION=|BROWSER_READY=|INITIAL_PAGE_TITLE=|SESSION_REUSE_CHECK=|EID_HANDOFF=|EID_STATE=|MONEY_STORAGE_RETURNED |MONEY_STORAGE_SESSION_CANDIDATE |CLOUDFLARE_STATE=|SBERKASSA_SESSION=|SBERKASSA_SESSION_AUTHENTICATED=|SESSION_REUSE_OR_EID_TIMEOUT=|NAV=|HTTP_DIAG |REQUEST |QUOTE_FIELDS |JSON_SCHEMA |PAGE_UPDATE_MARKERS |SBERKASSA_|CLOUDFLARE_CHALLENGE_DETECTED=|ACCESS_RESPONSE_CLASSIFICATION |PAGE_DIAG |BOT_OR_ACCESS_CHALLENGE_SUSPECTED=|AUTH_PROGRESS |AUTH_PAGE_STATE |ACCESS_DENIED_PAGE_SUSPECTED=|AUTH_RETURNED_TO_ACCOUNT|OFFERS_READ_|AUTH_TIMEOUT|MONEY_STORAGE_RETURN_TIMEOUT|PAGE_DIAG_UNAVAILABLE=|HTTP_DIAG_ERROR=)' || true
      BROWSER_LOG_LINES="$CURRENT_BROWSER_LINES"
    fi
    if [ "$CODE" != "200" ] || [ "$WS_STATUS" != "101" ]; then
      tail -n 30 /tmp/tailscale-funnel.log || true
      cat /tmp/eid-ws-headers || true
      ss -ltnp '( sport = :5900 or sport = :6080 )' || true
      tail -n 40 /tmp/websockify.log || true
      tail -n 40 /tmp/x11vnc.log || true
    fi
  fi
  sleep 2
done
echo "EID_SESSION_TIMEOUT limit_seconds=1200"
write_run_diagnostics || true
for LOG in /tmp/money-storage-browser.log /tmp/sberkassa-sell-browser.log /tmp/sberkassa-exchange-browser.log; do echo "FINAL_DIAGNOSTIC_LOG=$LOG"; tail -n 100 "$LOG" 2>/dev/null || true; done
tail -n 80 /tmp/eid-browser.log || true
exit 1
