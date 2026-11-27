# Private Codespaces E-ID browser

This environment uses GitHub Codespaces private port forwarding. It does not use
Tailscale Funnel or tunnl.gg for the browser session.

## One-time account setup

1. In GitHub Settings, create a Codespaces secret named
   `CHROMIUM_PROFILE_PASSPHRASE` with a unique random passphrase of at least
   32 characters. Grant access only to this repository.
2. Create a Codespace from branch
   `feat/codespaces-private-browser-20261127`.
3. Wait for the dev container setup to finish. Port 8080 is configured as
   HTTPS and private. Do not change its visibility to public.

## Start the browser

In the Codespaces terminal:

```bash
bash .devcontainer/start-private-browser.sh
```

Open the private forwarded port 8080 from the Ports panel. The script prints
the one-time browser path and session-ready path in the private Codespaces
terminal. Append the printed browser path to the forwarded port URL.

The browser opens exactly these three tabs:

- https://storage.money/deals#tab-3
- https://sberkassa.site/deals#tab-3
- https://sberkassa.site/exchange

Complete E-ID/CAPTCHA/MFA yourself. When all three tabs are back at those exact
URLs, click "Проверить вкладки и сохранить авторизацию". The endpoint verifies
the exact HTTPS host, path, and fragment. It does not collect quotes.

## Profile persistence

The working Chromium profile is restored into ephemeral `/tmp/eid-chromium-profile`.
At browser exit it is archived with AES-256 symmetric GPG encryption into
`/workspaces/.codespace-private-state/chromium-profile.tar.gz.gpg`, outside the
Git checkout. The Codespaces workspace volume persists across stop/start and
dev-container rebuilds. The passphrase comes only from the Codespaces secret.
Both the plaintext tar archive and runtime profile are removed after save.

On Codespace restart, `.devcontainer/restore-private-profile.sh` restores the
encrypted archive into ephemeral runtime storage. The browser is not started
automatically; run the command above when needed.

## Security and limits

- Port 8080 must remain **Private**. GitHub authenticates the Codespaces owner
  before granting access; private-port access cookies expire and may require
  reauthentication.
- Do not paste the forwarded URL or session tokens into chat, issues, commits,
  or Actions logs.
- Do not enable public forwarding.
- No quote collectors run in this auth-only mode.
- Codespaces stop/start preserves workspace data, but stopping the Codespace
  stops all processes. The profile archive is the durable encrypted copy.
- A hard kill or abrupt VM failure can prevent the exit-time encryption step.
  After a successful run, verify the encrypted archive exists before stopping
  the Codespace.
