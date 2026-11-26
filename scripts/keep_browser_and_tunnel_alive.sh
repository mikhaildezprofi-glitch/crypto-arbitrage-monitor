set -euo pipefail
umask 077

CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
CLOUDFLARE_TUNNEL_HOSTNAME="${CLOUDFLARE_TUNNEL_HOSTNAME:-}"
if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ] && [ -z "$CLOUDFLARE_TUNNEL_HOSTNAME" ]; then
  echo "CLOUDFLARE_TUNNEL_HOSTNAME_REQUIRED_FOR_NAMED_TUNNEL"
  exit 1
fi
if [ -n "$CLOUDFLARE_TUNNEL_HOSTNAME" ] && [[ ! "$CLOUDFLARE_TUNNEL_HOSTNAME" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "CLOUDFLARE_TUNNEL_HOSTNAME_INVALID"
  exit 1
fi

ACCESS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
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

sudo tee /usr/share/novnc/token-vnc.html >/dev/null <<'HTML'
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Private E-ID browser</title>
<style>
html,body,#screen{width:100%;height:100%;margin:0;background:#111;overflow:hidden}
#status{position:fixed;top:8px;left:8px;color:white;background:#222c;padding:6px 9px;border-radius:6px;font:14px sans-serif;z-index:3}
#tools{position:fixed;right:10px;top:8px;z-index:4}
#keyboardToggle{padding:10px 14px;border:0;border-radius:8px;background:#2463eb;color:white;font-size:15px}
#mobileInput{display:none;position:fixed;left:8px;right:8px;bottom:8px;width:calc(100% - 32px);height:44px;box-sizing:border-box;padding:8px 12px;border:2px solid #2463eb;border-radius:8px;background:white;color:#111;font-size:18px;z-index:5}
#mobileInput.visible{display:block}
</style></head>
<body><div id="status">Connecting to remote browser…</div><div id="tools"><button id="keyboardToggle" type="button">⌨ Клавиатура</button></div><div id="screen"></div>
<input id="mobileInput" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Нажмите здесь и вводите текст">
<script type="module">
import RFB from '/ACCESS_TOKEN_PLACEHOLDER/core/rfb.js';
const status = document.getElementById('status');
const keyboardToggle = document.getElementById('keyboardToggle');
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

Xvfb :99 -screen 0 1440x900x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

cleanup() {
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
if [ "$TARGET" = "all" ]; then
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
if [ "$TARGET" = "all" ]; then
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

# All three collectors attach to separate tabs in this one Chromium process.
if [ "$TARGET" = "all" ]; then
  MONEY_STORAGE_STATUS_FILE=/tmp/money-storage-status \
    python3 scripts/money_storage_chromium_bridge.py >/tmp/money-storage-browser.log 2>&1 &
  MONEY_PID=$!
  SBERKASSA_STATUS_FILE=/tmp/sberkassa-sell-status \
    python3 scripts/sberkassa_chromium_probe.py >/tmp/sberkassa-sell-browser.log 2>&1 &
  SBERKASSA_SELL_PID=$!
  SBERKASSA_EXCHANGE_STATUS_FILE=/tmp/sberkassa-exchange-status \
    python3 scripts/sberkassa_exchange_chromium_probe.py >/tmp/sberkassa-exchange-browser.log 2>&1 &
  SBERKASSA_EXCHANGE_PID=$!
  BRIDGE_PID="$MONEY_PID $SBERKASSA_SELL_PID $SBERKASSA_EXCHANGE_PID"
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


curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /tmp/cloudflared
sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
TUNNEL_PID=""

cleanup_all() {
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
  kill -TERM "$BROWSER_PID" "$TUNNEL_PID" 2>/dev/null || true
  wait "$BROWSER_PID" 2>/dev/null || true
  wait "$TUNNEL_PID" 2>/dev/null || true
  cleanup
}
trap cleanup_all EXIT

TUNNEL_URL=""
if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
  TUNNEL_URL="https://$CLOUDFLARE_TUNNEL_HOSTNAME"
  cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" >/tmp/cloudflared.log 2>&1 &
  TUNNEL_PID=$!
  echo "CLOUDFLARE_NAMED_TUNNEL_START=YES"
else
  echo "CLOUDFLARE_NAMED_TUNNEL_NOT_CONFIGURED; using temporary Quick Tunnel fallback"
  for tunnel_attempt in 1 2 3; do
    : > /tmp/cloudflared.log
    cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8080 >/tmp/cloudflared.log 2>&1 &
    TUNNEL_PID=$!
    for i in $(seq 1 60); do
      TUNNEL_URL="$(grep -Eo 'https://[a-zA-Z0-9.-]+\\.trycloudflare\\.com' /tmp/cloudflared.log | head -n 1 || true)"
      if [ -n "$TUNNEL_URL" ]; then break; fi
      if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then break; fi
      sleep 2
    done
    if [ -n "$TUNNEL_URL" ]; then
      echo "CLOUDFLARE_QUICK_TUNNEL_CREATED attempt=$tunnel_attempt"
      break
    fi
    wait "$TUNNEL_PID" 2>/dev/null || true
    TUNNEL_PID=""
    if grep -Eq 'status 429|HTTP 429| 429:' /tmp/cloudflared.log; then
      if [ "$tunnel_attempt" -lt 3 ]; then
        BACKOFF_SECONDS=$((tunnel_attempt * 30))
        echo "CLOUDFLARE_QUICK_TUNNEL_RATE_LIMITED retry=$((tunnel_attempt + 1))/3 backoff_seconds=$BACKOFF_SECONDS"
        sleep "$BACKOFF_SECONDS"
        continue
      fi
      echo "CLOUDFLARE_QUICK_TUNNEL_RATE_LIMIT_EXHAUSTED"
      tail -n 100 /tmp/cloudflared.log
      exit 1
    fi
    echo "CLOUDFLARED_EXITED_BEFORE_TUNNEL_URL attempt=$tunnel_attempt"
    tail -n 100 /tmp/cloudflared.log
    exit 1
  done
fi
if [ -z "$TUNNEL_URL" ]; then
  echo "TUNNEL_URL_NOT_CREATED"
  tail -n 100 /tmp/cloudflared.log
  exit 1
fi

PUBLIC_OK=""
for i in $(seq 1 90); do
  CODE="$(curl -sS --connect-timeout 8 --max-time 15 -o /dev/null -w '%{http_code}' "$TUNNEL_URL/$ACCESS_TOKEN/token-vnc.html" || true)"
  if [ "$CODE" = "200" ]; then PUBLIC_OK=yes; break; fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "CLOUDFLARED_EXITED_DURING_HEALTHCHECK"
    tail -n 100 /tmp/cloudflared.log
    exit 1
  fi
  echo "PUBLIC_TUNNEL_WAIT http=$CODE attempt=$i/90"
  sleep 2
done
if [ -z "$PUBLIC_OK" ]; then
  echo "PUBLIC_TUNNEL_HEALTHCHECK_FAILED"
  tail -n 100 /tmp/cloudflared.log
  exit 1
fi

echo "PUBLIC_TUNNEL_HEALTHCHECK=HTTP_200"

# Verify the actual WebSocket upgrade through Cloudflare and Nginx.
# A page-only HTTP 200 is not enough: it was the source of the
# misleading green health checks in the previous run.
WS_OK=""
for i in $(seq 1 10); do
  curl --http1.1 -sS -D /tmp/eid-ws-headers -o /dev/null --max-time 4 \
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
echo "Complete E-ID only in this remote browser. Treat the URL as a temporary secret."

# Forward only the browser's sanitized diagnostic lines into Actions logs.
# The browser process writes to a private file; without this relay its
# navigation and Cloudflare/E-ID diagnostics remain invisible.
BROWSER_LOG_LINES=0
echo "BROWSER_DIAGNOSTIC_STREAM=STARTED"
for i in $(seq 1 900); do
  if [ "$TARGET" = "all" ]; then
    MS_STATUS="$(cat /tmp/money-storage-status 2>/dev/null || echo WAITING)"
    SS_STATUS="$(cat /tmp/sberkassa-sell-status 2>/dev/null || echo WAITING)"
    SX_STATUS="$(cat /tmp/sberkassa-exchange-status 2>/dev/null || echo WAITING)"
    echo "SHARED_BROWSER_TAB_STATUS money_storage=$MS_STATUS sberkassa_sell=$SS_STATUS sberkassa_exchange=$SX_STATUS"
    if [ "$MS_STATUS" = "OFFERS_READ_OK" ] && [ "$SS_STATUS" = "SBERKASSA_CAPTURE_COMPLETE" ] && [ "$SX_STATUS" = "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE" ]; then
      echo "ALL_THREE_SHARED_BROWSER_TABS_COMPLETE=YES"
      grep -hE '^(OFFERS_READ_OK|SBERKASSA_CAPTURE_|SBERKASSA_EXCHANGE_INSPECTION_COMPLETE=|SBERKASSA_EXCHANGE_DISPLAYED_RATE=|SBERKASSA_SESSION=|SBERKASSA_SESSION_AUTHENTICATED=)' /tmp/money-storage-browser.log /tmp/sberkassa-sell-browser.log /tmp/sberkassa-exchange-browser.log | tail -n 160 || true
      exit 0
    fi
    case "$MS_STATUS" in OFFERS_READ_FAILED|AUTH_REQUIRED|AUTH_TIMEOUT) echo "MONEY_STORAGE_TAB_FAILED=$MS_STATUS"; cat /tmp/money-storage-browser.log; exit 1;; esac
    case "$SS_STATUS" in SBERKASSA_CAPTURE_FAILED|SBERKASSA_CAPTURE_TIMEOUT|AUTH_TIMEOUT) echo "SBERKASSA_SELL_TAB_FAILED=$SS_STATUS"; cat /tmp/sberkassa-sell-browser.log; exit 1;; esac
    case "$SX_STATUS" in SBERKASSA_EXCHANGE_AUTH_TIMEOUT|SBERKASSA_EXCHANGE_SESSION_EXPIRED|SBERKASSA_EXCHANGE_SELECTION_TIMEOUT) echo "SBERKASSA_EXCHANGE_TAB_FAILED=$SX_STATUS"; cat /tmp/sberkassa-exchange-browser.log; exit 1;; esac
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
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "CLOUDFLARED_PROCESS_EXITED"
    tail -n 100 /tmp/cloudflared.log
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
    CODE="$(curl -sS --connect-timeout 8 --max-time 15 -o /dev/null -w '%{http_code}' "$TUNNEL_URL/$ACCESS_TOKEN/token-vnc.html" || true)"
    WS_CODE="$(curl --http1.1 -sS -D /tmp/eid-ws-headers -o /dev/null --max-time 4 \
      -H "Connection: Upgrade" -H "Upgrade: websocket" \
      -H "Sec-WebSocket-Version: 13" \
      -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
      "$TUNNEL_URL/$ACCESS_TOKEN/websockify" >/dev/null 2>&1 || true)"
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
      tail -n 30 /tmp/cloudflared.log || true
      cat /tmp/eid-ws-headers || true
      ss -ltnp '( sport = :5900 or sport = :6080 )' || true
      tail -n 40 /tmp/websockify.log || true
      tail -n 40 /tmp/x11vnc.log || true
    fi
  fi
  sleep 2
done
echo "EID_SESSION_TIMEOUT"
tail -n 80 /tmp/eid-browser.log || true
exit 1
