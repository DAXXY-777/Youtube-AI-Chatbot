# Publishing Signed Windows Releases

`.github/workflows/release-windows.yml` tests pull requests. Pushing a tag such
as `v0.1.0` builds the desktop bundle, signs it, builds/signs an Inno Setup
installer, and publishes that installer as a GitHub Release.

## One-Time Setup

1. Create an empty GitHub repository and push this project to its `main` branch.
2. In **Settings -> Actions -> General**, allow GitHub Actions to create releases
   with `GITHUB_TOKEN` if the repository or organisation has restricted it.
3. Obtain a Windows code-signing certificate from a trusted certificate authority.
   Never commit its `.pfx` file or password.
4. In **Settings -> Secrets and variables -> Actions**, create:

   | Secret | Value |
   | --- | --- |
   | `WINDOWS_CERTIFICATE_BASE64` | Base64 text of the certificate `.pfx`. |
   | `WINDOWS_CERTIFICATE_PASSWORD` | The `.pfx` password. |

Create the Base64 text locally, then paste it into the GitHub Secret field:

```powershell
[Convert]::ToBase64String(
  [IO.File]::ReadAllBytes("C:\path\to\certificate.pfx")
) | Set-Clipboard
```

The workflow fails rather than publishing an unsigned tagged release when either
secret is absent. It timestamps the signature so it remains valid after the
certificate expires.

## Test Locally

```powershell
uv sync --group build
uv run python -m unittest discover -s tests -v
pwsh scripts/build_windows.ps1
```

Install [Inno Setup](https://jrsoftware.org/isinfo.php) only when you also want
to test the installer locally:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" `
  "/DMyAppVersion=0.1.0" `
  installer\YT-Livestream-Chatbot.iss
```

Install the resulting `release\YT-Livestream-Chatbot-Setup-0.1.0.exe` into a
writable test folder, launch it, and confirm it can create `data`, `models`,
and `logs` in that location.

## Publish A Version

1. Update `version` in `pyproject.toml`.
2. Commit and push the version update to `main`.
3. Create a matching semantic tag:

   ```powershell
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Watch **Actions -> Windows release**. It runs `verify`, `build`, then
   `publish`.
5. Download the signed installer from **Releases** once the workflow finishes.

`verify` is read-only. Only the final `publish` job gets `contents: write`,
which reduces the impact of a compromised build dependency. The workflow follows
UV's recommended locked-dependency GitHub Actions integration. [UV GitHub
Actions guide](https://docs.astral.sh/uv/guides/integration/github/)

## Deliberate Non-Features

- The installer does not bundle `cloudflared`, a VPN, a domain, or a tunnel
  account.
- It does not distribute GGUF models. Users download a model after installation.
- It does not manufacture a signing certificate. Certificate ownership and
  GitHub Secrets stay with the release owner.
- It does not host the service. Users can keep it local or point their own
  endpoint at the API listener on port `7861`.

## Troubleshooting

- **GitHub cannot create a release:** verify Actions workflow permissions.
- **Signing fails:** check PFX Base64, password, and timestamp-service access.
- **The installer cannot create data:** reinstall somewhere writable, not
  `Program Files`.
- **The desktop window is blank:** install/repair Microsoft Edge WebView2 Runtime
  and inspect `logs/yt-livestream-chatbot.log` in the install folder.
