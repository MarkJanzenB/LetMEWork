# Code signing (Authenticode) — optional for early testers

Unsigned builds can still ship as GitHub **Pre-release**. Expect SmartScreen “Windows protected your PC” until reputation builds or you sign.

## When you are ready to sign

1. `dist/LetMeWork.exe` (after PyInstaller)
2. `dist/installer/LetMeWork-Setup-*.exe` (after Inno)

```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\LetMeWork.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\installer\LetMeWork-Setup-0.1.0-beta.1.exe
```

Buy an OV/EV Authenticode cert from a public CA. EV builds SmartScreen trust faster.

Until then: document “More info → Run anyway” for testers, and keep the install practices in README.md (no UPX, no bundled OpenCode binary, official CLI only).
